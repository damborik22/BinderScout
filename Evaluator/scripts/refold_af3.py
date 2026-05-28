"""Standalone batch refolder for AlphaFold 3 v3.0.2 (Google DeepMind).

Run inside the ``binder-eval-af3`` conda env on DGX Spark (aarch64 / Blackwell).

Emits a CSV with one row per binder using the top-ranked AF3 sample (highest
ranking_score).  Columns are engine-neutral (``iptm``, ``ptm``, ``plddt_binder_mean``,
``pae_bt_mean``, …); the merger prefixes them with ``af3_`` when aggregating
across engines.

PAE ordering: [target | binder] — target is chain A (first in input JSON),
binder is chain B.  This matches Protenix convention so the same
``ordering="target_binder"`` is used downstream in scoring.py.

pLDDT is rescaled from AF3 native 0–100 to 0–1 so downstream code can
compare engines on the same scale.

AF3 is invoked with ``--run_data_pipeline=false`` (no MSA/template search)
because binder sequences are de novo with no evolutionary homologs.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import gemmi
import numpy as np


def refold_batch(
    binder_sequences: list[str],
    target_sequence: str,
    output_dir: str | os.PathLike,
    output_csv: str | os.PathLike,
    *,
    num_seeds: int = 1,
    num_samples: int = 5,
    model_dir: str | None = None,
    skip_indices: set[int] | None = None,
) -> None:
    """Refold each binder against target using AlphaFold 3; write metrics CSV.

    The top-ranked sample (by ``ranking_score``) is selected per binder; PAE is
    saved as a .npy sidecar and the CIF/PDB paths are recorded in the CSV.
    """
    skip_indices = skip_indices or set()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_root = out_dir / "predictions"
    predictions_root.mkdir(parents=True, exist_ok=True)

    model_dir = _resolve_model_dir(model_dir)

    jobs: list[tuple[int, str]] = []
    for i, seq in enumerate(binder_sequences, start=1):
        if i not in skip_indices:
            jobs.append((i, seq))
    if not jobs:
        print("[af3] Nothing to do (all indices skipped).")
        return

    print(
        f"[af3] Running {len(jobs)} binder(s) with {num_samples} sample(s) "
        f"per seed × {num_seeds} seed(s)  [model_dir={model_dir}]"
    )

    # Process one binder at a time so partial results are saved incrementally.
    fieldnames = _csv_fieldnames()
    csv_path = Path(output_csv).resolve()
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
            fh.flush()

        for idx, binder_seq in jobs:
            binder_len = len(binder_seq)
            target_len = len(target_sequence)
            print(f"[af3] Binder #{idx}  length={binder_len} aa")

            try:
                af3_out = _run_single(
                    idx=idx,
                    binder_seq=binder_seq,
                    target_seq=target_sequence,
                    predictions_root=predictions_root,
                    model_dir=model_dir,
                    num_seeds=num_seeds,
                    num_samples=num_samples,
                )
            except Exception as exc:
                print(f"[af3] ERROR on binder #{idx}: {exc}")
                row = _empty_row(idx, binder_seq, target_sequence)
                writer.writerow(row)
                fh.flush()
                continue

            if af3_out is None:
                print(f"[af3] No output found for binder #{idx}")
                row = _empty_row(idx, binder_seq, target_sequence)
                writer.writerow(row)
                fh.flush()
                continue

            # Parse confidence outputs
            summary = af3_out["summary"]
            confidences = af3_out["confidences"]
            cif_path = af3_out["cif"]

            # PAE matrix: [num_tokens, num_tokens] — already residue-level for proteins
            pae = np.asarray(confidences["pae"], dtype=np.float32)
            pae_file = out_dir / f"af3_{idx:04d}_pae.npy"
            np.save(pae_file, pae)

            # pLDDT: per-atom (0-100), extract CA atoms via gemmi, normalise to 0-1
            atom_plddts = np.asarray(confidences["atom_plddts"], dtype=np.float32)
            plddt_per_res = _extract_ca_plddt(cif_path, atom_plddts) / 100.0

            # Split pLDDT into target/binder (target is first chain)
            plddt_target = plddt_per_res[:target_len]
            plddt_binder = plddt_per_res[target_len:]

            # PAE block statistics: [target | binder] ordering
            pae_split = _split_pae(pae, target_len, binder_len)

            # Summary metrics
            iptm = summary.get("iptm", float("nan"))
            ptm = summary.get("ptm", float("nan"))
            ranking_score = summary.get("ranking_score", float("nan"))

            # Convert CIF to PDB via gemmi
            pdb_path = out_dir / f"af3_{idx:04d}.pdb"
            _cif_to_pdb(cif_path, pdb_path)

            row = {
                "run_id": f"af3_{idx:04d}",
                "idx": str(idx),
                "sequence": binder_seq,
                "target_sequence": target_sequence,
                "binder_length": str(binder_len),
                "iptm": _fmt(iptm),
                "ptm": _fmt(ptm),
                "ranking_score": _fmt(ranking_score),
                "plddt_binder_mean": _fmt(float(plddt_binder.mean())) if plddt_binder.size else "",
                "plddt_binder_min": _fmt(float(plddt_binder.min())) if plddt_binder.size else "",
                "plddt_target_mean": _fmt(float(plddt_target.mean())) if plddt_target.size else "",
                "pae_bt_mean": _fmt(pae_split["bt_mean"]),
                "pae_tb_mean": _fmt(pae_split["tb_mean"]),
                "pae_bb_mean": _fmt(pae_split["bb_mean"]),
                "pae_overall_mean": _fmt(pae_split["overall_mean"]),
                "pae_max": _fmt(pae_split["max"]),
                "cif": str(cif_path),
                "pdb": str(pdb_path),
                "pae_file": str(pae_file),
            }

            print(
                f"  iptm={iptm:.4f}  ranking_score={ranking_score:.3f}  "
                f"plddt_binder={float(plddt_binder.mean()):.3f}  "
                f"pae_bt={pae_split['bt_mean']:.2f}  pae_tb={pae_split['tb_mean']:.2f}"
            )
            writer.writerow(row)
            fh.flush()

    print(f"[af3] Wrote {len(jobs)} row(s) → {csv_path}")


# ---------------------------------------------------------------------------
# AF3 invocation
# ---------------------------------------------------------------------------


def _run_single(
    *,
    idx: int,
    binder_seq: str,
    target_seq: str,
    predictions_root: Path,
    model_dir: str,
    num_seeds: int,
    num_samples: int,
) -> dict | None:
    """Run AF3 on a single binder-target pair and return parsed outputs."""
    job_name = f"af3_{idx:04d}"

    # Build AF3 input JSON — target first (chain A), binder second (chain B)
    # to match Protenix convention ([target | binder] PAE ordering).
    # Open-source AF3 dialect: single object (not wrapped in list — that
    # signals AlphaFold Server format).
    af3_input = {
        "name": job_name,
        "modelSeeds": list(range(1, num_seeds + 1)),
        "sequences": [
            {"protein": {"id": "A", "sequence": target_seq, "unpairedMsa": "", "pairedMsa": "", "templates": []}},
            {"protein": {"id": "B", "sequence": binder_seq, "unpairedMsa": "", "pairedMsa": "", "templates": []}},
        ],
        "dialect": "alphafold3",
        "version": 4,
    }

    # Write input JSON to temp file
    input_dir = predictions_root / job_name
    input_dir.mkdir(parents=True, exist_ok=True)
    json_path = input_dir / "input.json"
    json_path.write_text(json.dumps(af3_input, indent=2))

    output_dir = input_dir / "output"

    # Invoke AF3 via run_alphafold.py (official Google DeepMind entry point).
    # The script lives in the cloned alphafold3 repo; resolve via AF3_REPO_DIR
    # env var or default to <BindMaster>/alphafold3/.
    af3_script = _resolve_af3_script()
    cmd = [
        sys.executable,
        str(af3_script),
        f"--json_path={json_path}",
        f"--model_dir={model_dir}",
        f"--output_dir={output_dir}",
        "--run_data_pipeline=false",
        "--force_output_dir",
        f"--num_diffusion_samples={num_samples}",
    ]

    print(f"  [af3] Running: {Path(cmd[1]).name} ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [af3] STDERR: {result.stderr[-500:]}" if result.stderr else "  [af3] No stderr")
        raise RuntimeError(f"AF3 exited with code {result.returncode}")

    # Find the top-ranked output
    return _load_top_sample(output_dir, job_name)


def _load_top_sample(output_dir: Path, job_name: str) -> dict | None:
    """Locate and load the top-ranked AF3 sample outputs.

    AF3 v3.0.2 writes top-ranked prediction to the output root:
      <output_dir>/<job_name>/<job_name>_confidences.json
      <output_dir>/<job_name>/<job_name>_summary_confidences.json
      <output_dir>/<job_name>/<job_name>_model.cif
    """
    # Try top-level first (top-ranked sample copied to root by AF3)
    candidates = [
        output_dir / job_name,
        output_dir,
    ]
    # Also check seed subdirectories
    for seed_dir in sorted(output_dir.glob(f"{job_name}/seed-*_sample-*")):
        candidates.append(seed_dir)
    for seed_dir in sorted(output_dir.glob("seed-*_sample-*")):
        candidates.append(seed_dir)

    for d in candidates:
        if not d.is_dir():
            continue

        confidences_fp = _find_file(d, "*confidences.json", exclude="summary")
        summary_fp = _find_file(d, "*summary_confidences.json")
        cif_fp = _find_file(d, "*model.cif")

        if confidences_fp and summary_fp and cif_fp:
            try:
                confidences = json.loads(confidences_fp.read_text())
                summary = json.loads(summary_fp.read_text())
            except (OSError, json.JSONDecodeError) as e:
                print(f"  [af3] Failed to parse JSON in {d}: {e}")
                continue
            return {"confidences": confidences, "summary": summary, "cif": cif_fp}

    return None


def _find_file(directory: Path, pattern: str, *, exclude: str | None = None) -> Path | None:
    """Find a single file matching *pattern* in *directory*, optionally excluding a substring."""
    for fp in directory.glob(pattern):
        if exclude and exclude in fp.name:
            continue
        return fp
    return None


# ---------------------------------------------------------------------------
# Output parsing helpers
# ---------------------------------------------------------------------------


def _extract_ca_plddt(cif_path: Path, atom_plddts: np.ndarray) -> np.ndarray:
    """Extract per-residue pLDDT by selecting CA atoms from the mmCIF structure.

    Returns array of shape [num_residues] in 0-100 scale (AF3 native).
    """
    st = gemmi.read_structure(str(cif_path))
    model = st[0]

    ca_indices: list[int] = []
    atom_idx = 0
    for chain in model:
        for residue in chain:
            found_ca = False
            for atom in residue:
                if atom.name == "CA":
                    ca_indices.append(atom_idx)
                    found_ca = True
                atom_idx += 1
            # For non-protein residues without CA, skip
            if not found_ca:
                pass  # no CA atom — likely a ligand token, not protein

    if not ca_indices:
        return np.zeros(0, dtype=np.float32)

    ca_indices_arr = np.array(ca_indices, dtype=np.int64)
    # Guard against index out of bounds (AF3 may have fewer atoms than expected)
    valid = ca_indices_arr < len(atom_plddts)
    return atom_plddts[ca_indices_arr[valid]]


def _split_pae(pae: np.ndarray, target_len: int, binder_len: int) -> dict[str, float]:
    """Summarise a PAE matrix into bt/tb/bb/overall/max scalars.

    AF3 PAE follows input chain order → [target | binder].
    """
    if pae.ndim != 2 or pae.size == 0:
        return {
            "bt_mean": float("nan"),
            "tb_mean": float("nan"),
            "bb_mean": float("nan"),
            "overall_mean": float("nan"),
            "max": float("nan"),
        }
    total = pae.shape[0]
    if total != target_len + binder_len:
        target_len = max(total - binder_len, 0)

    pae_tb = pae[:target_len, target_len:]
    pae_bt = pae[target_len:, :target_len]
    pae_bb = pae[target_len:, target_len:]

    def _mean(a: np.ndarray) -> float:
        return float(a.mean()) if a.size else float("nan")

    return {
        "bt_mean": _mean(pae_bt),
        "tb_mean": _mean(pae_tb),
        "bb_mean": _mean(pae_bb),
        "overall_mean": float(pae.mean()),
        "max": float(pae.max()),
    }


def _cif_to_pdb(cif_path: Path, pdb_path: Path) -> None:
    """Convert mmCIF to PDB format using gemmi."""
    try:
        st = gemmi.read_structure(str(cif_path))
        st.write_pdb(str(pdb_path))
    except Exception as e:
        print(f"  [af3] CIF→PDB conversion failed: {e}")


def _resolve_af3_script() -> Path:
    """Locate run_alphafold.py from the cloned google-deepmind/alphafold3 repo."""
    # Check AF3_REPO_DIR env var
    env_repo = os.environ.get("AF3_REPO_DIR")
    if env_repo:
        script = Path(env_repo) / "run_alphafold.py"
        if script.is_file():
            return script

    # Default: <BindMaster>/alphafold3/run_alphafold.py
    # scripts/ is inside Evaluator/, so BindMaster root is 2 levels up
    bindmaster_root = Path(__file__).resolve().parent.parent.parent
    script = bindmaster_root / "alphafold3" / "run_alphafold.py"
    if script.is_file():
        return script

    raise FileNotFoundError(
        "Cannot find run_alphafold.py. Clone the official AF3 repo:\n"
        "  git clone --depth 1 --branch v3.0.2 "
        "https://github.com/google-deepmind/alphafold3.git ~/BindMaster/alphafold3\n"
        "Or set AF3_REPO_DIR to the repo root."
    )


def _resolve_model_dir(override: str | None) -> str:
    """Resolve the AF3 model parameters directory."""
    if override:
        p = Path(override)
        if p.is_dir():
            return str(p)
        raise FileNotFoundError(f"AF3 model_dir not found: {p}")

    # Check environment variable
    env_dir = os.environ.get("AF3_MODEL_DIR")
    if env_dir and Path(env_dir).is_dir():
        return env_dir

    # Default locations
    for candidate in [
        Path.home() / ".alphafold3" / "models",
        Path.home() / "af3_models",
        Path("/opt/alphafold3/models"),
    ]:
        if candidate.is_dir() and any(candidate.iterdir()):
            return str(candidate)

    raise FileNotFoundError(
        "AF3 model parameters not found. Set AF3_MODEL_DIR or pass --model-dir. "
        "Download from: https://github.com/google-deepmind/alphafold3"
    )


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def _csv_fieldnames() -> list[str]:
    return [
        "run_id",
        "idx",
        "sequence",
        "target_sequence",
        "binder_length",
        "iptm",
        "ptm",
        "ranking_score",
        "plddt_binder_mean",
        "plddt_binder_min",
        "plddt_target_mean",
        "pae_bt_mean",
        "pae_tb_mean",
        "pae_bb_mean",
        "pae_overall_mean",
        "pae_max",
        "cif",
        "pdb",
        "pae_file",
    ]


def _empty_row(idx: int, binder_seq: str, target_seq: str) -> dict[str, str]:
    row = {
        "run_id": f"af3_{idx:04d}",
        "idx": str(idx),
        "sequence": binder_seq,
        "target_sequence": target_seq,
        "binder_length": str(len(binder_seq)),
    }
    for col in _csv_fieldnames()[5:]:
        row.setdefault(col, "")
    return row


def _fmt(v) -> str:
    """Stringify a numeric metric; empty string for None/NaN."""
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if np.isnan(f):
        return ""
    return f"{f:.6g}"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequences", required=True, help="FASTA (or plain text, one seq per line)")
    parser.add_argument("--target-seq", required=True, help="Target amino acid sequence")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--output-dir", default="./refold_af3", help="Output dir for structures/PAE")
    parser.add_argument("--model-dir", default=None, help="AF3 model parameters directory")
    parser.add_argument("--num-seeds", type=int, default=1)
    parser.add_argument("--num-samples", type=int, default=5)
    parser.add_argument("--resume", action="store_true", help="Skip binders already in output CSV")
    args = parser.parse_args()

    seqs: list[str] = []
    for line in Path(args.sequences).read_text().splitlines():
        s = line.strip()
        if not s or s.startswith(">"):
            continue
        seqs.append(s)

    skip: set[int] = set()
    if args.resume and Path(args.output).exists():
        import csv as csv_mod

        with open(args.output) as f:
            for row in csv_mod.DictReader(f):
                v = row.get("idx")
                if v:
                    try:
                        skip.add(int(v))
                    except ValueError:
                        pass
        if skip:
            print(f"[af3] Resuming — skipping {len(skip)} already-completed binders")

    refold_batch(
        binder_sequences=seqs,
        target_sequence=args.target_seq,
        output_dir=args.output_dir,
        output_csv=args.output,
        model_dir=args.model_dir,
        num_seeds=args.num_seeds,
        num_samples=args.num_samples,
        skip_indices=skip,
    )
