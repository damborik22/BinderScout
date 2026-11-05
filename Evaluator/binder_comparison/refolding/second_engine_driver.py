"""Shared driver for the per-candidate second-engine refold scripts (the AF3-replacement benchmark).

Every candidate script (``Evaluator/scripts/refold_<engine>.py``) is a thin adapter: it builds the
engine's input, runs the engine, and parses what comes back. Everything that decides whether two
engines' panels are like-for-like lives HERE, once, so it cannot drift between scripts:

* the common CLI and ``--resume`` (keyed on the binder sequence; a blank row is re-run);
* the shared target MSA (``prepare_target_msa``) and the ``target_msa_mode.json`` /
  ``refold_run_info.json`` sidecars;
* the per-design loop: a failed design is a BLANK row (reason on stderr), never a zero, and the
  designs after it still run;
* the exit-code contract: every design failed -> ``RuntimeError`` (exit 1 by traceback); some
  failed -> ``PartialRefoldFailure`` -> exit 3 with the count; no target MSA -> exit 2;
* the PAE: refused if its size is not ``n_binder + n_target`` or it holds a non-finite value,
  re-blocked to ``[binder|target]`` and saved as ``<binder_id>_<engine>_pae.npy``;
* the CSV row (``write_refold_row``, the AF3 header, unprefixed), with the pae_* summaries taken
  from the re-blocked matrix.

An adapter is any object with the attributes and methods of :class:`EngineAdapter`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Protocol

import numpy as np

from binder_comparison.io.design_ids import parse_fasta_pairs, structure_stems
from binder_comparison.refolding.errors import PartialRefoldFailure
from binder_comparison.refolding.second_engine import to_binder_target_pae, write_refold_row
from binder_comparison.refolding.target_msa import MissingTargetMSA, prepare_target_msa

#: Lines of the engine's own stderr kept in a failure reason.
STDERR_TAIL_LINES = 10


class EngineError(RuntimeError):
    """An engine run failed; ``stderr`` is its raw standard error, of which the tail is reported."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


class EngineAdapter(Protocol):
    """What a candidate script supplies to :func:`run_cli`."""

    #: Engine name; used in file names (``<binder_id>_<name>_pae.npy``), run ids and run_info.
    name: str
    #: ``--help`` description (usually the script's docstring).
    description: str
    #: Row/column order of the PAE the engine returns: ``"target_binder"`` or ``"binder_target"``.
    native_pae_order: str
    #: File name the target MSA is written under (some engines pick alignments by file name).
    target_msa_filename: str

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add the engine-specific flags."""

    def configure(self, args: argparse.Namespace) -> None:
        """Read the engine-specific flags; raise (before any work) if they cannot be satisfied."""

    def engine_version(self) -> str: ...

    def weights_id(self) -> str:
        """The checkpoint actually used (valid after ``configure``)."""

    def predict_one(
        self,
        *,
        query_id: str,
        binder_seq: str,
        target_seq: str,
        target_msa_path: Path | None,
        work_dir: Path,
        num_seeds: int,
        num_samples: int,
    ) -> dict:
        """Fold one binder against the target and return its top sample, or raise.

        The dict holds ``pae`` (token-level, ``native_pae_order``), ``summary`` (``iptm``, ``ptm``,
        ``sample_ranking_score`` as the engine reports them), ``plddt_target`` / ``plddt_binder``
        (per residue, 0-100), ``cif`` (path to the structure; a ``.pdb`` file is also accepted)
        and optionally ``seed``. Raise :class:`EngineError` to attach the engine's stderr.
        """


def stderr_tail(text: str | None, n: int = STDERR_TAIL_LINES) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _reason(exc: Exception) -> str:
    """Why a design failed: the exception text plus the tail of the engine's stderr, if it has one."""
    tail = stderr_tail(getattr(exc, "stderr", ""))
    return f"{exc}\n--- last lines of engine stderr ---\n{tail}" if tail else str(exc)


def run_cli(adapter: EngineAdapter, argv: list[str] | None = None) -> int:
    """Parse the common + engine flags, run the batch, return the process exit code."""
    parser = argparse.ArgumentParser(
        description=adapter.description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sequences", required=True, help="FASTA (or plain text, one seq per line)")
    parser.add_argument("--target-seq", required=True, help="Target amino acid sequence")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--output-dir", default=f"./refold_{adapter.name}", help="Output dir for structures/PAE")
    parser.add_argument("--num-seeds", type=int, default=1)
    parser.add_argument("--num-samples", type=int, default=5)
    parser.add_argument("--resume", action="store_true", help="Skip binders already scored in the output CSV")
    parser.add_argument("--no-msa", action="store_true", help="Disable target MSA (single-sequence mode)")
    parser.add_argument(
        "--allow-no-msa",
        action="store_true",
        help="Proceed single-sequence if the shared target MSA cannot be obtained (air-gapped nodes). "
        "Default is to abort -- scores from an MSA-less engine are not comparable to the others.",
    )
    parser.add_argument("--msa-cache-dir", default=None, help="Override MSA cache directory")
    adapter.add_args(parser)
    args = parser.parse_args(argv)
    adapter.configure(args)

    # The header's first token is the binder_id, as 'extract' writes it; saved structures are named after it.
    pairs = parse_fasta_pairs(Path(args.sequences).read_text())
    seqs = [seq for _, seq in pairs]
    ids = [binder_id for binder_id, _ in pairs]

    skip: set[int] = set()
    if args.resume and Path(args.output).exists():
        from binder_comparison.refolding.resume import resume_plan

        skip, n_rerun = resume_plan(args.output, seqs)
        if skip:
            print(f"[{adapter.name}] Resuming -- skipping {len(skip)} already-completed binders")
        if n_rerun:
            print(f"[{adapter.name}] Resuming -- RE-RUNNING {n_rerun} binder(s) whose previous row was blank")

    try:
        refold_batch(
            adapter,
            binder_sequences=seqs,
            binder_ids=ids,
            target_sequence=args.target_seq,
            output_dir=args.output_dir,
            output_csv=args.output,
            num_seeds=args.num_seeds,
            num_samples=args.num_samples,
            skip_indices=skip,
            use_msa=not args.no_msa,
            msa_cache_dir=args.msa_cache_dir,
            allow_no_msa=args.allow_no_msa,
        )
    except MissingTargetMSA as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except PartialRefoldFailure as exc:
        # 3, not 1: the valid rows are on disk and worth keeping, so a wrapper can tell
        # "re-run these indices" from "this environment is broken".
        print(f"\n{exc}", file=sys.stderr)
        return 3
    return 0


def refold_batch(
    adapter: EngineAdapter,
    *,
    binder_sequences: list[str],
    target_sequence: str,
    output_dir: str | Path,
    output_csv: str | Path,
    num_seeds: int = 1,
    num_samples: int = 5,
    skip_indices: set[int] | None = None,
    binder_ids: list[str | None] | None = None,
    use_msa: bool = True,
    msa_cache_dir: str | Path | None = None,
    allow_no_msa: bool = False,
) -> None:
    """Refold each binder against the target with ``adapter``; append rows to ``output_csv``."""
    name = adapter.name
    skip_indices = skip_indices or set()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_root = out_dir / "predictions"
    predictions_root.mkdir(parents=True, exist_ok=True)

    jobs = [(i, seq) for i, seq in enumerate(binder_sequences, start=1) if i not in skip_indices]
    if not jobs:
        print(f"[{name}] Nothing to do (all indices skipped).")
        return

    # Raises MissingTargetMSA (abort) if the shared MSA cannot be had and no opt-out was given;
    # also writes target_msa_mode.json into out_dir.
    target_msa, msa_mode = prepare_target_msa(
        target_sequence,
        engine=name,
        cache_dir=msa_cache_dir,
        out_dir=out_dir,
        use_msa=use_msa,
        allow_no_msa=allow_no_msa,
    )
    target_msa_path: Path | None = None
    if target_msa:
        target_msa_path = out_dir / "msas" / "target" / adapter.target_msa_filename
        target_msa_path.parent.mkdir(parents=True, exist_ok=True)
        target_msa_path.write_text(target_msa)
        print(f"[{name}] Target MSA loaded: {target_msa.count('>')} sequences, {len(target_msa)} bytes")

    run_info = {
        "engine": name,
        "engine_version": adapter.engine_version(),
        "weights_id": adapter.weights_id(),
        "n_samples": num_samples,
        "n_seeds": num_seeds,
        "seeds": None,  # filled from the seeds the engine reports having used
        "target_msa_mode": msa_mode,
    }
    _write_run_info(out_dir, run_info)

    print(
        f"[{name}] Running {len(jobs)} binder(s) with {num_samples} sample(s) per seed x {num_seeds} seed(s) "
        f"[weights={run_info['weights_id']}, target_msa={msa_mode}]"
    )

    stems = structure_stems(binder_ids, [f"{name}_{i:04d}" for i in range(1, len(binder_sequences) + 1)], engine=name)
    csv_path = Path(output_csv).resolve()
    failed_idx: list[int] = []
    seeds_seen: set[int] = set()
    first_reason: str | None = None
    for idx, binder_seq in jobs:
        print(f"[{name}] Binder #{idx}  length={len(binder_seq)} aa")
        row = {
            "run_id": f"{name}_{idx:04d}",
            "idx": str(idx),
            "sequence": binder_seq,
            "target_sequence": target_sequence,
            "binder_length": str(len(binder_seq)),
        }
        try:
            pred = adapter.predict_one(
                query_id=row["run_id"],
                binder_seq=binder_seq,
                target_seq=target_sequence,
                target_msa_path=target_msa_path,
                work_dir=predictions_root / row["run_id"],
                num_seeds=num_seeds,
                num_samples=num_samples,
            )
            row.update(_score_prediction(adapter, pred, binder_seq, target_sequence, out_dir, stems[idx - 1]))
            if pred.get("seed") is not None:
                seeds_seen.add(int(pred["seed"]))
        except Exception as exc:
            reason = _reason(exc)
            print(f"[{name}] ERROR on binder #{idx}: {reason}", file=sys.stderr, flush=True)
            failed_idx.append(idx)
            first_reason = first_reason or reason
            row = {k: row[k] for k in ("run_id", "idx", "sequence", "target_sequence", "binder_length")}
        write_refold_row(csv_path, row)

    run_info["seeds"] = sorted(seeds_seen) if seeds_seen else None
    _write_run_info(out_dir, run_info)
    print(f"[{name}] Wrote {len(jobs)} row(s) -> {csv_path}")

    n_failed = len(failed_idx)
    if n_failed == len(jobs):
        raise RuntimeError(
            f"All {len(jobs)} binder(s) failed -- {name} produced no usable output. This is an environment "
            f"fault, not bad input. First error: {first_reason}. Common causes: not enough free VRAM, "
            f"the {name} weights not downloaded, or a CUDA/torch mismatch."
        )
    if n_failed:
        raise PartialRefoldFailure(
            f"{n_failed} of {len(jobs)} binder(s) failed -- {name} wrote a BLANK row for each and the rest are "
            f"valid. Exiting non-zero because a blank row is not a score: it drops that design below the "
            f"cross-engine gate for a non-quality reason. First error: {first_reason}. "
            f"Failed design indices: {', '.join(str(i) for i in sorted(failed_idx))}. Re-run with --resume."
        )


def _score_prediction(
    adapter: EngineAdapter, pred: dict, binder_seq: str, target_seq: str, out_dir: Path, stem: str
) -> dict[str, str]:
    """Turn one model result into CSV cells and save the PAE.

    Raises (so the row stays blank and NOTHING is saved) on any inconsistency: a PAE of the wrong
    size or with a non-finite value, a pLDDT of the wrong length, or a non-finite iptm.
    """
    nb, nt = len(binder_seq), len(target_seq)
    summary = pred["summary"]
    # to_binder_target_pae refuses any size other than nb + nt.
    pae = to_binder_target_pae(np.asarray(pred["pae"], dtype=np.float32), nb, nt, order=adapter.native_pae_order)
    if not np.isfinite(pae).all():
        raise ValueError("PAE contains non-finite values; refusing to score it")
    plddt_binder = np.asarray(pred["plddt_binder"], dtype=np.float32) / 100.0
    plddt_target = np.asarray(pred["plddt_target"], dtype=np.float32) / 100.0
    if len(plddt_binder) != nb or len(plddt_target) != nt:
        raise ValueError(
            f"pLDDT has {len(plddt_target)} target / {len(plddt_binder)} binder CA values, expected {nt} / {nb}"
        )
    iptm = summary.get("iptm")
    if iptm is None or not np.isfinite(float(iptm)):
        raise ValueError(f"{adapter.name} reported iptm={iptm!r}; a missing or non-finite iptm is not a score")

    pae_file = out_dir / f"{stem}_pae.npy"
    np.save(pae_file, pae)
    structure = Path(pred.get("cif") or pred["structure"])
    if structure.suffix == ".pdb":
        cif_cell, pdb_cell = "", str(structure)
    else:
        pdb_path = out_dir / f"{stem}.pdb"
        cif_cell, pdb_cell = str(structure), (str(pdb_path) if _cif_to_pdb(structure, pdb_path, adapter.name) else "")

    bt, tb, bb = pae[:nb, nb:], pae[nb:, :nb], pae[:nb, :nb]  # [binder | target] blocks
    return {
        "iptm": _fmt(iptm),
        "ptm": _fmt(summary.get("ptm")),
        "ranking_score": _fmt(summary.get("sample_ranking_score")),
        "plddt_binder_mean": _fmt(plddt_binder.mean()) if nb else "",
        "plddt_binder_min": _fmt(plddt_binder.min()) if nb else "",
        "plddt_target_mean": _fmt(plddt_target.mean()) if nt else "",
        "pae_bt_mean": _fmt(bt.mean()),
        "pae_tb_mean": _fmt(tb.mean()),
        "pae_bb_mean": _fmt(bb.mean()),
        "pae_overall_mean": _fmt(pae.mean()),
        "pae_max": _fmt(pae.max()),
        "cif": cif_cell,
        "pdb": pdb_cell,
        "pae_file": str(pae_file),
    }


def _write_run_info(out_dir: Path, info: dict) -> None:
    (out_dir / "refold_run_info.json").write_text(json.dumps(info, indent=2) + "\n")


def _cif_to_pdb(cif_path: Path, pdb_path: Path, name: str) -> bool:
    """Best-effort mmCIF to PDB via gemmi; False (and a message) when it cannot."""
    try:
        import gemmi

        gemmi.read_structure(str(cif_path)).write_pdb(str(pdb_path))
        return True
    except Exception as exc:
        print(f"  [{name}] CIF->PDB conversion failed: {exc}")
        return False


def _fmt(v) -> str:
    """Stringify a numeric metric; empty string for None/NaN."""
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return "" if np.isnan(f) else f"{f:.6g}"
