"""Compare refold-engine panels on a labelled pool (AF3-replacement benchmark, step 0).

Joins a merged refold CSV (one row per design, ``id`` plus per-engine ``*_pae_iptm`` columns) to measured
binding labels and reports, per panel (the row mean of the named columns), the per-target ROC AUC with its
macro average and median. Every panel after the first is compared with the first (the baseline) by a paired
bootstrap and judged by the fixed pass rule in ``binder_comparison.comparison.panel_benchmark``.

    panel_benchmark.py --merged adaptyv_merged.csv --pool adaptyv \\
        --panel boltz_pae_iptm,af3_pae_iptm,esmfold2_pae_iptm --panel boltz_pae_iptm,esmfold2_pae_iptm \\
        --out panels.json

Labels come from the private registry (``--pool``, ``$BINDERSCOUT_BENCHMARK_STORE``) unless ``--labels-csv``
is given (columns ``id``, ``target`` and the label column, ``--label-column``, default ``binds``).

What is refused (exit 2, naming the counts), because each would put a wrong number behind a right-looking name:

* a merged id that has no row at all in the label source;
* a requested panel column that is not in the merged CSV;
* a blank value in a BASELINE panel column on a measured design;
* a label value that is not 0/1.

A blank in a CANDIDATE panel is not refused: it flows through to the pass rule, whose clause d fails any
candidate that left a labelled design without a score. Refusing there would hide the shortfall that the
verdict is meant to report.

Never read as negatives: designs whose registry outcome is not ``bound``/``not_bound`` (not tested, excluded)
and designs with a null label in ``--labels-csv``. Both are dropped and counted in the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from binder_comparison import benchmarks
from binder_comparison.comparison import panel_benchmark as pb

_MEASURED = ("bound", "not_bound")


class Refusal(Exception):
    """A condition under which no number should be produced."""


def _load_labels(pool: str, labels_csv: str | None, label_col: str) -> tuple[pd.DataFrame, pd.Series]:
    """(every label row as id, target, binds; mask of the rows that were measured)."""
    if labels_csv:
        df = pd.read_csv(labels_csv)
        missing = [c for c in ("id", "target", label_col) if c not in df.columns]
        if missing:
            raise Refusal(f"{labels_csv}: missing column(s) {missing}")
        return df[["id", "target", label_col]].rename(columns={label_col: "binds"}), pd.Series(True, index=df.index)
    df = benchmarks.load_labels(pool)
    return df[["id", "target", label_col]].rename(columns={label_col: "binds"}), df["outcome"].isin(_MEASURED)


def _booleans(col: pd.Series) -> pd.Series:
    bad = col.dropna()[~col.dropna().isin([0, 1])]
    if len(bad):
        raise Refusal(f"label column holds {len(bad)} value(s) that are not 0/1, e.g. {bad.iloc[0]!r}")
    return col.map(lambda v: None if pd.isna(v) else bool(v)).astype(object)


def _clean(obj):
    """JSON-safe copy: NaN/inf become null (a bare NaN is not valid JSON)."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, float | np.floating):
        return float(obj) if np.isfinite(obj) else None
    return obj


def _summary(df: pd.DataFrame, cols: list[str]) -> dict:
    auc = pb.per_target_auc(df, pb.panel_consensus(df, cols))
    finite = [v for v in auc.values() if np.isfinite(v)]
    return {
        "columns": cols,
        "n_per_target": {str(t): int(n) for t, n in df["target"].value_counts().sort_index().items()},
        "per_target_auc": auc,
        "macro_auc": float(np.mean(finite)) if finite else float("nan"),
        "median_auc": float(np.median(finite)) if finite else float("nan"),
    }


def run(args: argparse.Namespace) -> dict:
    panels = [[c.strip() for c in p.split(",") if c.strip()] for p in args.panel]
    names = [",".join(p) for p in panels]
    if len(set(names)) != len(names):
        raise Refusal("the same panel was given twice")

    merged = pd.read_csv(args.merged)
    absent = sorted({c for p in panels for c in p} - set(merged.columns))
    if "id" not in merged.columns or absent:
        raise Refusal(f"{args.merged}: missing column(s) {absent or ['id']}")

    # A merged design the label source has no row for is a join failure. One it has but did not measure
    # (not tested, excluded) is dropped and counted. A design is keyed by id, and by target as well when the
    # merged CSV carries one, since a design can be screened against more than one target.
    labels, measured = _load_labels(args.pool, args.labels_csv, args.label_column)
    keys = ["id", "target"] if "target" in merged.columns else ["id"]
    known = pd.MultiIndex.from_frame(labels[keys])
    ghosts = ~pd.MultiIndex.from_frame(merged[keys]).isin(known)
    if ghosts.any():
        raise Refusal(
            f"{int(ghosts.sum())} merged id(s) have no label row in {args.labels_csv or args.pool}, "
            f"e.g. {list(merged.loc[ghosts, 'id'][:3])}"
        )
    labels["binds"] = _booleans(labels["binds"].where(measured))
    labels["measured"] = measured
    try:
        df = merged.merge(labels, on=keys, how="left", validate="many_to_one")
    except pd.errors.MergeError as exc:
        raise Refusal(f"label source has more than one row for a design ({keys}): {exc}") from exc
    n_unmeasured = int((~df["measured"]).sum())
    n_null = int((df["measured"] & df["binds"].isna()).sum())
    df = df[df["measured"] & df["binds"].notna()].reset_index(drop=True)
    if n_null:
        print(f"{n_null} design(s) have a null label in the label source: dropped, not counted as negatives")
    if n_unmeasured:
        print(f"{n_unmeasured} design(s) were not measured (not tested or excluded): dropped")

    base = panels[0]
    blank = int(df[base].isna().any(axis=1).sum())
    if blank:
        raise Refusal(f"{blank} measured design(s) have a blank value in baseline panel column(s) {base}")

    result = {
        "pool": args.labels_csv or args.pool,
        "baseline": names[0],
        "n_designs": len(df),
        "n_dropped_unmeasured": n_unmeasured,
        "n_dropped_null_label": n_null,
        "panels": {},
    }
    for name, cols in zip(names, panels, strict=True):
        entry = _summary(df, cols)
        print(f"{name}: n per target {entry['n_per_target']}, macro AUC {entry['macro_auc']:.4f}")
        if name != names[0]:
            diff = pb.paired_bootstrap_diff(
                df, pb.panel_consensus(df, cols), pb.panel_consensus(df, base), n_boot=args.n_boot, seed=args.seed
            )
            ok, failed = pb.passes(diff)
            entry["paired_bootstrap_diff"] = diff
            entry["passes"] = {"ok": ok, "failed_clauses": failed}
        result["panels"][name] = entry
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--merged", required=True, help="Merged refold CSV: an 'id' column and the panel columns")
    parser.add_argument("--pool", default="adaptyv", help="Registered benchmark pool (default: adaptyv)")
    parser.add_argument(
        "--panel",
        action="append",
        required=True,
        help="Comma-separated panel columns; repeat. The first is the baseline the others are compared with",
    )
    parser.add_argument("--labels-csv", default=None, help="Read labels from this CSV (id, target, label column)")
    parser.add_argument("--label-column", default="binds", help="Label column name (default: binds)")
    parser.add_argument("--n-boot", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except Refusal as exc:
        print(f"panel_benchmark: refused: {exc}", file=sys.stderr)
        return 2
    Path(args.out).write_text(json.dumps(_clean(result), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
