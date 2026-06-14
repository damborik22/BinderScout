"""CLI subcommand: binder-compare autosize

Decide whether enough INDEPENDENT designs (backbones, not sequences) have cleared
the ESMFold2 chain-pair interface iPTM gate, and how many more to generate if not.

This is the deployment-agnostic verdict step. It consumes an ESMFold2 refold CSV
(``binder-compare refold-esmfold2`` output) and prints a JSON Verdict. The loop
wrapper (generate the suggested batch locally, or write the "need M more" signal
into PROGRESS.md for a remote worker) calls this each round.

Usage:
    binder-compare autosize \\
        --esmfold2-results esmfold2_results.csv \\
        --designs          sequences_native_metrics.csv  \\  # for backbone dedup
        --n-target 50 --threshold 0.75 \\
        --budget-spent 12.5 --budget-cap 80
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..comparison.autosize import (
    GATE_TIERS,
    autosize_decision,
    count_independent_passers,
    resolve_gate_threshold,
    run_autosize_loop,
)
from ..comparison.scoring import add_chain_iptm_interface, add_design_groups
from ..io.read import read_csv_safe

DEFAULT_SCORE_COL = "chain_iptm_interface"


def run(args: argparse.Namespace) -> None:
    # Resolve the gate cutoff once, before either path: an explicit --threshold overrides
    # the named --tier. Record which was used so the Verdict is self-documenting.
    args.tier_label = "explicit" if args.threshold is not None else args.tier
    args.threshold = resolve_gate_threshold(args.tier, args.threshold)

    if args.loop:
        _run_loop(args)
        return

    passers, n_independent = _score_pool(args, require=True)
    verdict = autosize_decision(
        have=passers,
        n_independent=n_independent,
        n_target=args.n_target,
        budget_spent=args.budget_spent,
        budget_cap=args.budget_cap,
        margin=args.margin,
    )
    _emit(verdict, args)


def _score_pool(args: argparse.Namespace, *, require: bool) -> tuple[int, int]:
    """Read the ESMFold2 results, derive the gate metric, dedup to backbones, count.

    ``require=True`` (single-shot) errors out on a missing file/column; ``require=False``
    (loop, where the pool may not exist on the cold-start round) returns (0, 0) instead.
    """
    results_path = Path(args.esmfold2_results)
    if not results_path.exists():
        if require:
            print(f"Error: ESMFold2 results not found: {results_path}", file=sys.stderr)
            sys.exit(1)
        return 0, 0

    df = read_csv_safe(results_path)
    # Derive the gate metric from the raw refold columns (iptm_pair / iptm_pair_min).
    df = add_chain_iptm_interface(df, prefix="")
    if args.score_col not in df.columns:
        if require:
            print(
                f"Error: score column '{args.score_col}' not in results and could not be derived "
                f"(need iptm_pair/iptm_pair_min for the default). Columns: {list(df.columns)}",
                file=sys.stderr,
            )
            sys.exit(1)
        return 0, 0

    df = _attach_design_groups(df, args.designs)
    return count_independent_passers(df, threshold=args.threshold, score_col=args.score_col, group_col="design_group")


def _emit(verdict, args: argparse.Namespace, *, history: list | None = None) -> None:
    payload = verdict.to_dict()
    payload["threshold"] = args.threshold
    payload["tier"] = args.tier_label
    payload["score_col"] = args.score_col
    if history is not None:
        payload["rounds"] = len(history)
    print(json.dumps(payload, indent=2))
    if args.output:
        out = {"final": payload, "history": [v.to_dict() for v in history]} if history else payload
        Path(args.output).write_text(json.dumps(out, indent=2))


def _shell(template: str, **subs: object) -> None:
    cmd = template
    for key, val in subs.items():
        cmd = cmd.replace("{" + key + "}", str(val))
    print(f"[autosize] $ {cmd}", file=sys.stderr)
    subprocess.run(cmd, shell=True, check=True)


def _run_loop(args: argparse.Namespace) -> None:
    """generate → refold → score → decide, until complete / budget / max-rounds.

    --generate-cmd (with a {batch} placeholder) produces that many more designs and
    refreshes the FASTA + --designs sidecar; --refold-cmd refolds the current designs
    into --esmfold2-results (it MUST pass --resume so only new designs are folded)."""
    if not args.generate_cmd:
        print("Error: --loop requires --generate-cmd", file=sys.stderr)
        sys.exit(1)

    def _score() -> tuple[int, int]:
        if args.refold_cmd:
            _shell(args.refold_cmd)
        return _score_pool(args, require=False)

    def _generate(n: int) -> None:
        _shell(args.generate_cmd, batch=n)

    history = run_autosize_loop(
        generate=_generate,
        score_pool=_score,
        n_target=args.n_target,
        budget_cap=args.budget_cap,
        gpu_h_per_design=args.gpu_h_per_design,
        margin=args.margin,
        max_rounds=args.max_rounds,
    )
    final = history[-1]
    print(
        f"[autosize] loop ended after {len(history)} round(s): {final.stop_reason} "
        f"({final.have}/{final.n_target} independent designs)",
        file=sys.stderr,
    )
    _emit(final, args, history=history)


def _attach_design_groups(df, designs_csv: str | None):
    """Add a ``design_group`` column so the count is per backbone, not per sequence.

    Prefers an extract sidecar CSV (``--designs``: sequence, binder_id, source_tool)
    joined by sequence; falls back to binder_id already on the frame; else counts
    per-row (no dedup) with a warning.
    """
    if "binder_id" not in df.columns and designs_csv:
        designs = read_csv_safe(designs_csv)
        if "sequence" in designs.columns and "binder_id" in designs.columns:
            keep = ["sequence", "binder_id"] + (["source_tool"] if "source_tool" in designs.columns else [])
            df = df.merge(designs[keep].drop_duplicates("sequence"), on="sequence", how="left")

    if "binder_id" in df.columns:
        return add_design_groups(df)

    print(
        "[autosize] WARNING: no binder_id (pass --designs with the extract sidecar) — "
        "counting per-row, so multiple sequences of one backbone are NOT collapsed.",
        file=sys.stderr,
    )
    df = df.copy()
    df["design_group"] = [str(i) for i in range(len(df))]
    return df


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "autosize",
        help="Decide whether enough independent designs cleared the ESMFold2 gate; size the next batch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--esmfold2-results", required=True, metavar="CSV", help="ESMFold2 refold CSV (binder-compare refold-esmfold2)"
    )
    p.add_argument(
        "--designs",
        metavar="CSV",
        help="Extract sidecar (sequence, binder_id, source_tool) for backbone dedup. "
        "Without it, designs are counted per-row.",
    )
    p.add_argument("--n-target", type=int, required=True, metavar="N", help="Target number of INDEPENDENT designs")
    p.add_argument(
        "--tier",
        choices=sorted(GATE_TIERS),
        default="default",
        help="Named gate cutoff for the chain-pair interface iPTM: "
        + ", ".join(f"{k}={v}" for k, v in sorted(GATE_TIERS.items()))
        + ". A binder-vs-non-binder screen, not an affinity bar — calibrate on an unfamiliar target.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="X",
        help="Explicit gate cutoff; overrides --tier.",
    )
    p.add_argument(
        "--score-col",
        default=DEFAULT_SCORE_COL,
        metavar="COL",
        help=f"Gate metric column (default {DEFAULT_SCORE_COL}, the ESMFold2 chain-pair interface iPTM).",
    )
    p.add_argument("--budget-spent", type=float, default=0.0, metavar="H", help="GPU-hours spent so far (default 0)")
    p.add_argument(
        "--budget-cap", type=float, default=None, metavar="H", help="GPU-hour cap; stop with 'budget' if reached"
    )
    p.add_argument(
        "--margin", type=float, default=1.2, metavar="F", help="Safety factor on the next batch (default 1.2)"
    )
    p.add_argument("--output", "-o", metavar="JSON", help="Also write the Verdict JSON here")

    loop = p.add_argument_group("loop mode (--loop): drive generate → refold → decide until done")
    loop.add_argument("--loop", action="store_true", help="Run the closed loop instead of a single verdict")
    loop.add_argument(
        "--generate-cmd",
        metavar="CMD",
        help="Shell command to generate the next batch; '{batch}' is replaced with the count. "
        "Must refresh the FASTA + --designs sidecar so the next refold sees the new designs.",
    )
    loop.add_argument(
        "--refold-cmd",
        metavar="CMD",
        help="Shell command run each round to refold current designs into --esmfold2-results "
        "(MUST pass --resume so only new designs are folded).",
    )
    loop.add_argument(
        "--gpu-h-per-design", type=float, default=0.0, metavar="H", help="GPU-hours per design, for budget accounting"
    )
    loop.add_argument(
        "--max-rounds", type=int, default=100, metavar="N", help="Safety cap on loop rounds (default 100)"
    )
    p.set_defaults(func=run)
