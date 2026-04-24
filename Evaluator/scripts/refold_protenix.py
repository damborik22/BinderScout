"""Standalone batch refolder for Protenix v0.5.0.

Run inside the `bindmaster_pxdesign` conda env (which ships Protenix v0.5.0
pinned by the PXDesign installer).

Emits a CSV with one row per (target, binder) pair using the top-ranked
Protenix sample (highest ranking_score). Columns are engine-neutral
(``iptm``, ``ptm``, ``plddt_binder_mean``, ``pae_bt_mean``, ...); the merger
prefixes them with ``protenix_`` when aggregating across engines.

pLDDT is rescaled from Protenix native 0–100 to 0–1 so downstream code can
compare engines on the same scale.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

import numpy as np


def refold_batch(
    binder_sequences: list[str],
    target_sequence: str,
    output_dir: str | os.PathLike,
    output_csv: str | os.PathLike,
    *,
    num_samples: int = 5,
    num_seeds: int = 1,
    use_msa: bool = False,
    n_cycle: int = 10,
    n_step: int = 200,
    skip_indices: set[int] | None = None,
) -> None:
    """Refold each binder against target using Protenix; write metrics CSV.

    The top-ranked sample (by ``ranking_score``) is selected per binder; PAE is
    saved as a .npy sidecar and the CIF path is recorded in the CSV.
    """
    skip_indices = skip_indices or set()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_root = out_dir / "predictions"
    predictions_root.mkdir(parents=True, exist_ok=True)

    jobs = _build_job_jsons(binder_sequences, target_sequence, skip_indices=skip_indices)
    if not jobs:
        print("[protenix] Nothing to do (all indices skipped).")
        return

    # Protenix's inference_jsons reads a JSON file path; write to a temp file.
    json_fd, json_path = tempfile.mkstemp(prefix="protenix_batch_", suffix=".json", dir=out_dir)
    os.close(json_fd)
    Path(json_path).write_text(json.dumps([j for _, j in jobs], indent=2))

    seeds = tuple(range(101, 101 + num_seeds))

    print(
        f"[protenix] Running {len(jobs)} binder(s) with {num_samples} sample(s) "
        f"per seed × {len(seeds)} seed(s)  [use_msa={use_msa}, n_cycle={n_cycle}, "
        f"n_step={n_step}]"
    )

    # Protenix imports trigger CUDA init; import lazily.
    from configs.configs_inference import inference_configs  # type: ignore
    from runner.batch_inference import inference_jsons  # type: ignore

    # Force Protenix to dump the full_data JSON — it contains the token-pair
    # PAE matrix we need for DunbrackLab ipSAE computation. Default is False.
    inference_configs["need_atom_confidence"] = True

    inference_jsons(
        json_file=json_path,
        out_dir=str(predictions_root),
        use_msa=use_msa,
        seeds=seeds,
        n_cycle=n_cycle,
        n_step=n_step,
        n_sample=num_samples,
    )
    try:
        Path(json_path).unlink()
    except OSError:
        pass

    _write_csv(jobs, predictions_root, out_dir, Path(output_csv), seeds=seeds)


def _build_job_jsons(
    binder_sequences: list[str],
    target_sequence: str,
    *,
    skip_indices: set[int],
) -> list[tuple[int, dict]]:
    """Build one Protenix entry per (target, binder) pair.

    Returns a list of (idx, dict) where idx is a 1-based binder index and dict
    is the per-job Protenix schema entry.
    """
    jobs: list[tuple[int, dict]] = []
    for i, seq in enumerate(binder_sequences, start=1):
        if i in skip_indices:
            continue
        name = f"design_{i:04d}"
        jobs.append(
            (
                i,
                {
                    "name": name,
                    "sequences": [
                        {"proteinChain": {"sequence": target_sequence, "count": 1}},
                        {"proteinChain": {"sequence": seq, "count": 1}},
                    ],
                },
            )
        )
    return jobs


def _write_csv(
    jobs: list[tuple[int, dict]],
    predictions_root: Path,
    out_dir: Path,
    output_csv: Path,
    *,
    seeds: tuple[int, ...],
) -> None:
    """Parse Protenix outputs and write a flat metrics CSV."""
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
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

    rows: list[dict[str, str]] = []
    for idx, job in jobs:
        name = job["name"]
        target_seq = job["sequences"][0]["proteinChain"]["sequence"]
        binder_seq = job["sequences"][1]["proteinChain"]["sequence"]
        binder_len = len(binder_seq)
        target_len = len(target_seq)

        row = {
            "run_id": name,
            "idx": str(idx),
            "sequence": binder_seq,
            "target_sequence": target_seq,
            "binder_length": str(binder_len),
        }

        best = _load_top_sample(
            predictions_root=predictions_root,
            dataset_name=Path(predictions_root).stem if False else "",
            sample_name=name,
            seeds=seeds,
        )
        if best is None:
            print(f"[protenix] No output found for {name} — row will have NaNs")
            for col in fieldnames[5:]:
                row.setdefault(col, "")
            rows.append(row)
            continue

        summary = best["summary"]
        pae = best["pae"]  # shape [N_tokens, N_tokens], [target | binder]
        cif_path = best["cif"]

        # chain_plddt is already in [0, 1]; convention: chain 0 = target, 1 = binder.
        chain_plddt = summary.get("chain_plddt") or []
        plddt_target_mean = float(chain_plddt[0]) if len(chain_plddt) > 0 else float("nan")
        plddt_binder_mean = float(chain_plddt[1]) if len(chain_plddt) > 1 else float("nan")

        plddt_binder_min = _binder_atom_plddt_min(best.get("full_data"), binder_chain_asym_id=1)

        pae_split = _split_pae(pae, target_len, binder_len)
        pae_file = out_dir / f"{name}_pae.npy"
        np.save(pae_file, pae)

        row.update(
            {
                "iptm": _fmt(summary.get("iptm")),
                "ptm": _fmt(summary.get("ptm")),
                "ranking_score": _fmt(summary.get("ranking_score")),
                "plddt_binder_mean": _fmt(plddt_binder_mean),
                "plddt_binder_min": _fmt(plddt_binder_min),
                "plddt_target_mean": _fmt(plddt_target_mean),
                "pae_bt_mean": _fmt(pae_split["bt_mean"]),
                "pae_tb_mean": _fmt(pae_split["tb_mean"]),
                "pae_bb_mean": _fmt(pae_split["bb_mean"]),
                "pae_overall_mean": _fmt(pae_split["overall_mean"]),
                "pae_max": _fmt(pae_split["max"]),
                "cif": str(cif_path) if cif_path else "",
                "pdb": "",
                "pae_file": str(pae_file),
            }
        )
        rows.append(row)

    with output_csv.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[protenix] Wrote {len(rows)} row(s) → {output_csv}")


def _load_top_sample(
    *,
    predictions_root: Path,
    dataset_name: str,
    sample_name: str,
    seeds: tuple[int, ...],
) -> dict | None:
    """Locate and load the highest-ranked Protenix sample for *sample_name*.

    Protenix writes sorted-by-ranking-score samples with rank 0 as the best.
    We take sample_0 from the first seed that exists.

    Protenix v0.5.0 writes to either layout depending on the caller:
      (a) ``<predictions_root>/<sample_name>/seed_<seed>/predictions/``
      (b) ``<predictions_root>/<dataset_name>/<sample_name>/seed_<seed>/predictions/``
    We probe both.
    """
    for seed in seeds:
        candidates = [
            predictions_root / sample_name / f"seed_{seed}" / "predictions",
            *predictions_root.glob(f"*/{sample_name}/seed_{seed}/predictions"),
        ]
        pred_dir = next((c for c in candidates if c.is_dir()), None)
        if pred_dir is None:
            continue
        cif = next(pred_dir.glob(f"{sample_name}_seed_{seed}_sample_0.cif"), None)
        summary_fp = next(
            pred_dir.glob(f"{sample_name}_seed_{seed}_summary_confidence_sample_0.json"),
            None,
        )
        if cif is None or summary_fp is None:
            continue
        try:
            summary = json.loads(Path(summary_fp).read_text())
        except (OSError, json.JSONDecodeError):
            continue

        # Protenix stores token-pair PAE in a separate *_full_data_*.json when
        # inference_configs["need_atom_confidence"] was True at infer time.
        full_data_fp = next(
            pred_dir.glob(f"{sample_name}_full_data_sample_0.json"),
            None,
        ) or next(
            pred_dir.glob(f"{sample_name}_seed_{seed}_full_data_sample_0.json"),
            None,
        )
        full_data = None
        if full_data_fp is not None:
            try:
                full_data = json.loads(Path(full_data_fp).read_text())
            except (OSError, json.JSONDecodeError):
                full_data = None
        pae = _extract_pae_from_full(full_data) if full_data else _extract_pae(summary, full_data_fp)
        return {"summary": summary, "pae": pae, "cif": cif, "full_data": full_data}

    return None


def _extract_pae_from_full(full_data: dict) -> np.ndarray:
    arr = full_data.get("token_pair_pae") or full_data.get("pae")
    if arr is None:
        return np.zeros((0, 0))
    return np.asarray(arr, dtype=np.float32)


def _binder_atom_plddt_min(full_data: dict | None, *, binder_chain_asym_id: int) -> float:
    """Minimum atom pLDDT within the binder chain, rescaled to [0, 1].

    Protenix's atom_plddt is in 0–100 range; divide by 100 to match Boltz-2.
    Returns NaN when full_data is unavailable.
    """
    if not full_data:
        return float("nan")
    atom_plddt = full_data.get("atom_plddt")
    atom_to_token = full_data.get("atom_to_token_idx")
    token_asym = full_data.get("token_asym_id")
    if atom_plddt is None or atom_to_token is None or token_asym is None:
        return float("nan")

    atom_plddt = np.asarray(atom_plddt, dtype=np.float32)
    atom_to_token = np.asarray(atom_to_token, dtype=np.int64)
    token_asym = np.asarray(token_asym, dtype=np.int64)
    if atom_plddt.size == 0 or atom_to_token.size == 0:
        return float("nan")

    binder_token_mask = token_asym == binder_chain_asym_id
    if not np.any(binder_token_mask):
        return float("nan")

    is_binder_atom = binder_token_mask[atom_to_token]
    binder_vals = atom_plddt[is_binder_atom]
    if binder_vals.size == 0:
        return float("nan")
    return float(binder_vals.min()) / 100.0


def _extract_pae(summary: dict, full_data_fp: Path | None = None) -> np.ndarray:
    """Pull the PAE matrix out of a Protenix full_data_*.json if available.

    Protenix v0.5.0 writes ``token_pair_pae`` into the full_data JSON, which
    only exists when ``inference_configs["need_atom_confidence"] == True``.
    Falls back to an empty array when the full_data file is absent.
    """
    if full_data_fp is not None:
        try:
            full = json.loads(Path(full_data_fp).read_text())
        except (OSError, json.JSONDecodeError):
            return np.zeros((0, 0))
        arr = full.get("token_pair_pae") or full.get("pae")
        if arr is not None:
            return np.asarray(arr, dtype=np.float32)

    # Fall back to whatever is in summary (older versions), else empty
    arr = summary.get("token_pair_pae") or summary.get("pae")
    if arr is None:
        return np.zeros((0, 0))
    return np.asarray(arr, dtype=np.float32)


def _split_pae(pae: np.ndarray, target_len: int, binder_len: int) -> dict[str, float]:
    """Summarise a PAE matrix into bt/tb/bb/overall/max scalars.

    Protenix PAE follows input chain order → [target | binder].
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
        # Protenix may insert extra tokens (ions, ligands); trust shape.
        target_len = max(total - binder_len, 0)

    pae_tt = pae[:target_len, :target_len]
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
        "tt_mean": _mean(pae_tt),
    }


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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequences", required=True, help="FASTA (or plain text, one seq per line)")
    parser.add_argument("--target-seq", required=True, help="Target amino acid sequence")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--output-dir", default="./refold_protenix", help="Output dir for structures/PAE")
    parser.add_argument("--num-samples", type=int, default=5)
    parser.add_argument("--num-seeds", type=int, default=1)
    parser.add_argument("--use-msa", action="store_true")
    parser.add_argument("--n-cycle", type=int, default=10)
    parser.add_argument("--n-step", type=int, default=200)
    args = parser.parse_args()

    seqs: list[str] = []
    for line in Path(args.sequences).read_text().splitlines():
        s = line.strip()
        if not s or s.startswith(">"):
            continue
        seqs.append(s)
    refold_batch(
        binder_sequences=seqs,
        target_sequence=args.target_seq,
        output_dir=args.output_dir,
        output_csv=args.output,
        num_samples=args.num_samples,
        num_seeds=args.num_seeds,
        use_msa=args.use_msa,
        n_cycle=args.n_cycle,
        n_step=args.n_step,
    )
