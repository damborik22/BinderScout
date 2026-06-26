"""CLI subcommand: binder-compare prefilter

Rank designs by a cheap single-engine (Boltz-2) fold-back *interface* score, for
tools that emit no native interface metric of their own — most importantly RFD3,
which can otherwise only be ranked by ``mpnn_sequence_recovery`` (a sequence
proxy with no binding signal).

This is the standard RFdiffusion recipe — diffusion gives geometry, a fold-back
gives the rank (Bennett et al. 2023; the 2025 3,766-binder meta-analysis found
ipSAE the best single in-silico predictor of experimental binding). Run the
cheap Boltz-2 fold-back over *all* designs, rank by the interface score, and
select the top-N to carry into the full cross-engine refold — instead of letting
sequence-recovery decide which RFD3 designs are worth the expensive AF3 pass.

Two-step recipe (Boltz-2 runs in the Mosaic venv; this ranks the result in the
``binder-eval`` env):

    Mosaic/.venv/bin/binder-compare refold-boltz2 \\
        --sequences rfd3_designs.fasta --target-seq SEQ -o rfd3_boltz2.csv
    binder-compare prefilter \\
        --boltz2-results rfd3_boltz2.csv --sequences rfd3_designs.fasta \\
        --metric ipsae_min --top 50 --tool rfd3 -o rfd3_selection.csv

The output is sorted best-first and carries a ``sequence`` column, so it drops
straight into ``binder-compare report --tool-csv rfd3=rfd3_selection.csv`` (the
native section + candidates.csv then rank RFD3 by the fold-back, not recovery).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from ..comparison.scoring import add_boltz_ipsae_from_files, add_iptm_from_pae_files
from ..io.read import read_fasta
from ..io.write import write_csv

# user-facing metric name → (PAE-recomputed column, raw fallback column)
_METRIC_COLS = {
    "ipsae_min": ("boltz_pae_ipsae_min", "ipsae_min"),
    "iptm": ("boltz_pae_iptm", "iptm"),
}


def _fasta_metadata(fasta_path: str | Path) -> dict[str, dict]:
    """Map UPPER(sequence) → {binder_id, source_tool} from an extract FASTA."""
    meta: dict[str, dict] = {}
    for header, seq in read_fasta(fasta_path):
        tokens = header.split()
        binder_id = tokens[0] if tokens else header
        source_tool = ""
        for tok in tokens[1:]:
            if tok.startswith("source="):
                source_tool = tok.split("=", 1)[1]
        meta.setdefault(seq.strip().upper(), {"binder_id": binder_id, "source_tool": source_tool})
    return meta


def build_selection(
    df: pd.DataFrame, metric_col: str, fasta_meta: dict[str, dict] | None, tool: str, top: int | None
) -> pd.DataFrame:
    """Sort designs best-first by ``metric_col``, de-dupe by sequence, format output.

    Pure (no I/O); ``df`` must already carry ``metric_col`` + ``sequence`` (and
    ``binder_length``). Returns a select-style frame ranked best-first.
    """
    work = df.copy()
    work["_metric"] = pd.to_numeric(work.get(metric_col), errors="coerce")
    work["_seqkey"] = work.get("sequence", "").astype(str).str.strip().str.upper()
    work = work.sort_values("_metric", ascending=False, na_position="last")
    work = work[~work["_seqkey"].duplicated(keep="first")].reset_index(drop=True)
    if top is not None:
        work = work.head(top)

    fasta_meta = fasta_meta or {}

    def _bid(r):
        m = fasta_meta.get(r["_seqkey"], {})
        return m.get("binder_id") or r.get("run_id", "") or r["_seqkey"][:12]

    def _tool(r):
        m = fasta_meta.get(r["_seqkey"], {})
        return m.get("source_tool") or tool

    out = pd.DataFrame(
        {
            "design_id": [_bid(r) for _, r in work.iterrows()],
            "tool": [_tool(r) for _, r in work.iterrows()],
            "native_metric": metric_col,
            "native_value": work["_metric"].round(4).values,
            "length": work.get("binder_length").values if "binder_length" in work else "",
            "sequence": work.get("sequence").values if "sequence" in work else "",
            "boltz_pae_iptm": pd.to_numeric(work.get("boltz_pae_iptm"), errors="coerce").round(4).values
            if "boltz_pae_iptm" in work
            else "",
            "boltz_pae_ipsae_min": pd.to_numeric(work.get("boltz_pae_ipsae_min"), errors="coerce").round(4).values
            if "boltz_pae_ipsae_min" in work
            else "",
        }
    )
    return out


def run(args: argparse.Namespace) -> None:
    df = pd.read_csv(args.boltz2_results)
    base_dir = Path(args.boltz2_results).resolve().parent

    # Recompute the canonical interface metrics from the Boltz-2 PAE files (same
    # numbers the evaluator's consensus uses). Boltz-2 PAE is [binder|target].
    if "pae_file" in df.columns:
        df = add_boltz_ipsae_from_files(df, pae_file_col="pae_file", base_dir=base_dir)
        df = add_iptm_from_pae_files(
            df, pae_file_col="pae_file", ordering="binder_target", prefix="boltz", base_dir=base_dir
        )

    pae_col, raw_col = _METRIC_COLS[args.metric]
    if pae_col in df.columns and pd.to_numeric(df[pae_col], errors="coerce").notna().any():
        metric_col = pae_col
    elif raw_col in df.columns:
        print(
            f"[prefilter] WARNING: {pae_col} unavailable (no PAE files?) — "
            f"falling back to the raw Boltz-2 '{raw_col}' column.",
            file=sys.stderr,
        )
        metric_col = raw_col
    else:
        print(f"[prefilter] ERROR: neither {pae_col} nor {raw_col} present in {args.boltz2_results}", file=sys.stderr)
        sys.exit(1)

    fasta_meta = _fasta_metadata(args.sequences) if args.sequences else None
    out = build_selection(df, metric_col, fasta_meta, args.tool, args.top)
    write_csv(out, args.output)

    n_nonzero = int((pd.to_numeric(out["native_value"], errors="coerce") > 0).sum())
    top_val = out["native_value"].iloc[0] if len(out) else "n/a"
    print(f"[prefilter] ranked {len(out)} design(s) by Boltz-2 fold-back '{metric_col}' (best first)")
    print(f"[prefilter]   {n_nonzero}/{len(out)} form an interface (>0); top score = {top_val}")
    print(f"[prefilter]   wrote {args.output} — use as: report --tool-csv {args.tool}={args.output}")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "prefilter",
        help="Rank designs by a Boltz-2 fold-back interface score (for tools with no native metric, e.g. RFD3).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--boltz2-results", required=True, metavar="CSV", help="Output from 'refold-boltz2' on the designs")
    p.add_argument(
        "--sequences",
        "-s",
        metavar="FASTA",
        help="Extract FASTA — attaches binder_id/source_tool by sequence (optional)",
    )
    p.add_argument(
        "--metric",
        choices=list(_METRIC_COLS),
        default="ipsae_min",
        help="Interface metric to rank by (default: ipsae_min — best single predictor; 'iptm' also available)",
    )
    p.add_argument(
        "--tool", default="rfd3", metavar="NAME", help="Tool tag for the output 'tool' column (default: rfd3)"
    )
    p.add_argument("--top", type=int, default=None, metavar="N", help="Keep only the top N (default: keep all, ranked)")
    p.add_argument("--output", "-o", required=True, metavar="CSV", help="Output selection CSV (ranked best-first)")
    p.set_defaults(func=run)
