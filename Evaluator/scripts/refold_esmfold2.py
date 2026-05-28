"""Standalone batch refolder for ESMFold2 (biohub).

Run inside the ``binder-eval-esmfold2`` conda env.  Loads the model once,
iterates over binder sequences, and writes one CSV row per binder using
``ESMFold2InputBuilder().fold(...)`` with the target as chain A and the
binder as chain B (PAE ordering ``target_binder`` — same convention as
Protenix and AF3).

Two checkpoints are supported:
  * ``fast`` → ``biohub/ESMFold2-Fast`` — single-sequence, inference-optimised.
  * ``full`` → ``biohub/ESMFold2``     — larger, multimer- and MSA-capable.

pLDDT is normalised to the 0-1 scale on emit (auto-detected: divide by 100
if max > 1.5) so the downstream report can compare engines directly.

Binders are sorted by length ascending so JIT-cached graphs from the
shorter, faster jobs warm up the cache before larger ones run, reducing
peak VRAM pressure.
"""

from __future__ import annotations

import csv
import gc
import os
import sys
from pathlib import Path
from typing import Any

import gemmi
import numpy as np

# --- model identifiers ------------------------------------------------------

_MODEL_IDS: dict[str, str] = {
    "fast": "biohub/ESMFold2-Fast",
    "full": "biohub/ESMFold2",
}


def refold_batch(
    binder_sequences: list[str],
    target_sequence: str,
    output_dir: str | os.PathLike,
    output_csv: str | os.PathLike,
    *,
    model_name: str = "fast",
    num_loops: int = 3,
    num_sampling_steps: int = 50,
    num_diffusion_samples: int = 1,
    seed: int = 0,
    skip_indices: set[int] | None = None,
) -> None:
    """Refold each binder against *target_sequence* using ESMFold2.

    The PAE matrix is saved as a sidecar ``.npy``; the predicted complex is
    written as both CIF (native) and PDB (gemmi-converted).
    """
    skip_indices = skip_indices or set()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[int, str]] = []
    for i, seq in enumerate(binder_sequences, start=1):
        if i not in skip_indices:
            jobs.append((i, seq))
    if not jobs:
        print("[esmfold2] Nothing to do (all indices skipped).")
        return

    # Sort jobs by binder length ascending (shorter first → warmer cache when
    # bigger jobs arrive; matches the Boltz-2 OOM mitigation).
    jobs.sort(key=lambda t: len(t[1]))

    repo_id = _resolve_repo_id(model_name)
    print(
        f"[esmfold2] Loading {repo_id}  "
        f"(loops={num_loops}, sampling_steps={num_sampling_steps}, "
        f"diffusion_samples={num_diffusion_samples}, seed={seed})"
    )

    model, build_fn = _load_model_and_builder(repo_id)

    fieldnames = _csv_fieldnames()
    csv_path = Path(output_csv).resolve()
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0

    target_len = len(target_sequence)
    pae_units_logged = False

    with csv_path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
            fh.flush()

        for idx, binder_seq in jobs:
            binder_len = len(binder_seq)
            print(f"[esmfold2] Binder #{idx}  length={binder_len} aa")

            try:
                result = build_fn(
                    model=model,
                    target_seq=target_sequence,
                    binder_seq=binder_seq,
                    num_loops=num_loops,
                    num_sampling_steps=num_sampling_steps,
                    num_diffusion_samples=num_diffusion_samples,
                    seed=seed,
                )
            except Exception as exc:
                print(f"[esmfold2] ERROR on binder #{idx}: {exc}")
                writer.writerow(_empty_row(idx, binder_seq, target_sequence))
                fh.flush()
                _free_torch_cache()
                continue

            try:
                pae = _to_numpy(getattr(result, "pae", None))
                plddt = _to_numpy(getattr(result, "plddt", None))
                iptm = _scalar(getattr(result, "iptm", float("nan")))
                ptm = _scalar(getattr(result, "ptm", float("nan")))
                complex_obj = getattr(result, "complex", None)
                cif_str = complex_obj.to_mmcif() if complex_obj is not None else None
            except Exception as exc:
                print(f"[esmfold2] ERROR extracting outputs for #{idx}: {exc}")
                writer.writerow(_empty_row(idx, binder_seq, target_sequence))
                fh.flush()
                _free_torch_cache()
                continue

            if pae is None or pae.size == 0:
                print(f"[esmfold2] No PAE returned for #{idx}; recording empty row.")
                writer.writerow(_empty_row(idx, binder_seq, target_sequence))
                fh.flush()
                _free_torch_cache()
                continue

            # Sanity-log PAE units once (DunbrackLab 10 Å cutoff assumes Å).
            if not pae_units_logged:
                pae_units_logged = True
                print(f"  [esmfold2] PAE range (binder #{idx}): min={float(pae.min()):.3f}  max={float(pae.max()):.3f}")

            plddt_per_res = _normalise_plddt(plddt)

            cif_path = out_dir / f"esmfold2_{idx:04d}_model.cif"
            pdb_path = out_dir / f"esmfold2_{idx:04d}.pdb"
            pae_path = out_dir / f"esmfold2_{idx:04d}_pae.npy"
            np.save(pae_path, pae.astype(np.float32, copy=False))

            if cif_str:
                cif_path.write_text(cif_str)
                _cif_to_pdb(cif_path, pdb_path)

            # Target tokens come first (chain A in the input builder).
            plddt_target = plddt_per_res[:target_len] if plddt_per_res.size else plddt_per_res
            plddt_binder = plddt_per_res[target_len:] if plddt_per_res.size else plddt_per_res

            pae_split = _split_pae(pae, target_len, binder_len)

            row = {
                "run_id": f"esmfold2_{idx:04d}",
                "idx": str(idx),
                "sequence": binder_seq,
                "target_sequence": target_sequence,
                "binder_length": str(binder_len),
                "iptm": _fmt(iptm),
                "ptm": _fmt(ptm),
                "plddt_binder_mean": _fmt(float(plddt_binder.mean())) if plddt_binder.size else "",
                "plddt_binder_min": _fmt(float(plddt_binder.min())) if plddt_binder.size else "",
                "plddt_target_mean": _fmt(float(plddt_target.mean())) if plddt_target.size else "",
                "pae_bt_mean": _fmt(pae_split["bt_mean"]),
                "pae_tb_mean": _fmt(pae_split["tb_mean"]),
                "pae_bb_mean": _fmt(pae_split["bb_mean"]),
                "pae_overall_mean": _fmt(pae_split["overall_mean"]),
                "pae_max": _fmt(pae_split["max"]),
                "cif": str(cif_path) if cif_str else "",
                "pdb": str(pdb_path) if cif_str and pdb_path.exists() else "",
                "pae_file": str(pae_path),
            }

            print(
                f"  iptm={iptm:.4f}  ptm={ptm:.4f}  "
                f"plddt_binder={float(plddt_binder.mean()) if plddt_binder.size else float('nan'):.3f}  "
                f"pae_bt={pae_split['bt_mean']:.2f}  pae_tb={pae_split['tb_mean']:.2f}"
            )
            writer.writerow(row)
            fh.flush()
            _free_torch_cache()

    print(f"[esmfold2] Wrote {len(jobs)} row(s) → {csv_path}")


# ---------------------------------------------------------------------------
# Model loading + per-binder fold
# ---------------------------------------------------------------------------


def _load_model_and_builder(repo_id: str):
    """Import ESMFold2, instantiate the model on CUDA, and return a fold callable.

    The fold callable encapsulates the ``ProteinInput`` + ``StructurePredictionInput``
    + ``ESMFold2InputBuilder().fold(...)`` pattern documented on the HF model card.
    """
    try:
        import torch
    except ImportError as exc:  # pragma: no cover — install-time issue
        raise RuntimeError(
            "PyTorch not installed in the ESMFold2 env — run "
            "`pip install --index-url https://download.pytorch.org/whl/cu130 torch` "
            "(use the wheel index matching your CUDA)."
        ) from exc

    try:
        from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model
    except ImportError as exc:
        raise RuntimeError(
            "ESMFold2Model not available in transformers — install a version "
            "that ships ESMFold2 support (`pip install 'transformers>=4.50'`)."
        ) from exc

    try:
        from esm.models.esmfold2 import (
            ESMFold2InputBuilder,
            ProteinInput,
            StructurePredictionInput,
        )
    except ImportError as exc:
        raise RuntimeError(
            "biohub esm SDK not available — install with `pip install "
            "'esm @ git+https://github.com/Biohub/esm.git@c94ed8d'`."
        ) from exc

    if not torch.cuda.is_available():
        raise RuntimeError("ESMFold2 requires CUDA — no GPU detected.")

    model = ESMFold2Model.from_pretrained(repo_id).cuda().eval()
    builder = ESMFold2InputBuilder()

    def _fold(
        *,
        model: Any,
        target_seq: str,
        binder_seq: str,
        num_loops: int,
        num_sampling_steps: int,
        num_diffusion_samples: int,
        seed: int,
    ) -> Any:
        spi = StructurePredictionInput(
            sequences=[
                ProteinInput(id="A", sequence=target_seq),
                ProteinInput(id="B", sequence=binder_seq),
            ]
        )
        with torch.no_grad():
            return builder.fold(
                model,
                spi,
                num_loops=num_loops,
                num_sampling_steps=num_sampling_steps,
                num_diffusion_samples=num_diffusion_samples,
                seed=seed,
            )

    return model, _fold


def _resolve_repo_id(model_name: str) -> str:
    key = (model_name or "fast").lower()
    if key not in _MODEL_IDS:
        raise ValueError(f"Unknown --esmfold2-model {model_name!r}; expected one of {sorted(_MODEL_IDS)}.")
    return _MODEL_IDS[key]


def _free_torch_cache() -> None:
    """Release between-binder GPU caches to keep VRAM headroom on long batches."""
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass
    gc.collect()


# ---------------------------------------------------------------------------
# Output parsing helpers
# ---------------------------------------------------------------------------


def _to_numpy(value: Any) -> np.ndarray | None:
    """Best-effort conversion of a result attribute to a numpy array."""
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return value
    detach = getattr(value, "detach", None)
    if callable(detach):
        try:
            return detach().cpu().numpy()
        except Exception:
            pass
    try:
        return np.asarray(value)
    except Exception:
        return None


def _scalar(value: Any) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    arr = _to_numpy(value)
    if arr is None:
        return float("nan")
    if arr.size == 0:
        return float("nan")
    return float(arr.reshape(-1).mean())


def _normalise_plddt(plddt: np.ndarray | None) -> np.ndarray:
    """Return per-residue pLDDT on the 0-1 scale (rescale if the source is 0-100)."""
    if plddt is None:
        return np.zeros(0, dtype=np.float32)
    arr = np.asarray(plddt, dtype=np.float32).reshape(-1)
    if arr.size and float(arr.max()) > 1.5:
        arr = arr / 100.0
    return arr


def _split_pae(pae: np.ndarray, target_len: int, binder_len: int) -> dict[str, float]:
    """Summarise a PAE matrix into bt/tb/bb/overall/max scalars.

    Token order: [target | binder] (target first in the input builder).
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
    try:
        st = gemmi.read_structure(str(cif_path))
        st.write_pdb(str(pdb_path))
    except Exception as e:
        print(f"  [esmfold2] CIF→PDB conversion failed: {e}")


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
        "run_id": f"esmfold2_{idx:04d}",
        "idx": str(idx),
        "sequence": binder_seq,
        "target_sequence": target_seq,
        "binder_length": str(len(binder_seq)),
    }
    for col in _csv_fieldnames()[5:]:
        row.setdefault(col, "")
    return row


def _fmt(v) -> str:
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
    parser.add_argument("--output-dir", default="./refold_esmfold2", help="Directory for structures + PAE .npy files")
    parser.add_argument(
        "--model", default="fast", choices=sorted(_MODEL_IDS), help="ESMFold2 checkpoint (default fast)"
    )
    parser.add_argument("--num-loops", type=int, default=3)
    parser.add_argument("--num-sampling-steps", type=int, default=50)
    parser.add_argument("--num-diffusion-samples", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resume", action="store_true", help="Skip binders already in output CSV")
    args = parser.parse_args()

    seqs: list[str] = []
    for line in Path(args.sequences).read_text().splitlines():
        s = line.strip()
        if not s or s.startswith(">"):
            continue
        seqs.append(s)

    if not seqs:
        print(f"[esmfold2] No sequences found in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    skip: set[int] = set()
    if args.resume and Path(args.output).exists():
        with open(args.output) as f:
            for row in csv.DictReader(f):
                v = row.get("idx")
                if v:
                    try:
                        skip.add(int(v))
                    except ValueError:
                        pass
        if skip:
            print(f"[esmfold2] Resuming — skipping {len(skip)} already-completed binders")

    refold_batch(
        binder_sequences=seqs,
        target_sequence=args.target_seq,
        output_dir=args.output_dir,
        output_csv=args.output,
        model_name=args.model,
        num_loops=args.num_loops,
        num_sampling_steps=args.num_sampling_steps,
        num_diffusion_samples=args.num_diffusion_samples,
        seed=args.seed,
        skip_indices=skip,
    )
