"""CLI subcommand: binder-compare hits.

Build the wet-lab "Selected Hits" workbook from one or more ``candidates.csv``.

Two numbers drive the selection, and they are the only ones you normally change:

  --per-tool N   each tool's own top-N designs        (12 for a full campaign)
  --refolded N   NEW designs taken off our ranking    (30 for a full campaign)

An Adaptyv order is ``--per-tool 2 --refolded 11``.

Usage:
    binder-compare hits \\
        --candidates CALCA=CALCA_.../candidates.csv \\
        --candidates 2VDY=2VDY_.../candidates.csv \\
        --per-tool 12 --refolded 30 \\
        --meta CALCA='name:Calcitonin;uniprot:P01258' \\
        --meta 2VDY='name:Corticosteroid-binding globulin;uniprot:P08185;pdb:2VDY' \\
        --extra 2VDY:rfd3=3 \\
        -o BinderScout_Selected_Hits.xlsx

Section B lists designs our ranking picked that a per-tool block already covered;
those rows are the record that the pick was accounted for and do not count
toward ``--refolded``. See :mod:`binder_comparison.comparison.hits`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from ..comparison.hits import HITS_COLUMNS, hits_summary, select_hits
from ..io.read import read_csv_safe

_ENGINES = "Boltz-2, AlphaFold3, ESMFold2"
_TOOLS = "BindCraft, BoltzGen, Mosaic, Proteina-Complexa, PXDesign, Protein Hunter, RFDiffusion3"


def _kv(spec: str, what: str) -> tuple[str, str]:
    if "=" not in spec:
        print(f"Error: --{what} needs TARGET=VALUE, got {spec!r}", file=sys.stderr)
        sys.exit(2)
    k, v = spec.split("=", 1)
    return k.strip(), v.strip()


def _meta(spec: str) -> dict[str, str]:
    out = {}
    for part in spec.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _write_sheet(xl, sheet: str, hits: pd.DataFrame, meta: dict, summary: dict, version: str) -> None:
    """Header block, then the table — laid out like the hand-built sheets."""
    head = [
        [meta.get("name", sheet), meta.get("uniprot", ""), meta.get("pdb", "")],
        ["BinderScout version", version, ""],
        ["Number of the designs to be tested", summary["distinct_designs_to_test"], ""],
        ["Dashboard:", meta.get("dashboard", "RESULTS"), ""],
        ["", "", ""],
        [f"Per tool: top {summary['per_tool_n']} · Refolded: top {summary['refolded_n']} new", "", ""],
        [
            f"{summary['per_tool']} per-tool + {summary['refolded_new']} refolded "
            f"({summary['already_covered']} refold picks already covered above, listed for the record)",
            "",
            "",
        ],
        [f"Re-folding / re-scoring: {_ENGINES}", "", ""],
        [f"Global ranking: mean-ipTM of {_ENGINES}", "", ""],
    ]
    for note in [v for k, v in meta.items() if k.startswith("note")]:
        head.append([note, "", ""])
    head.append(["", "", ""])

    pd.DataFrame(head).to_excel(xl, sheet_name=sheet, index=False, header=False, startrow=1, startcol=1)
    hits.to_excel(xl, sheet_name=sheet, index=False, startrow=len(head) + 2, startcol=1)
    ws = xl.sheets[sheet]
    for col, width in zip("BCDEFGHIJKL", (6, 26, 20, 22, 16, 18, 12, 16, 20, 10, 60), strict=False):
        ws.column_dimensions[col].width = width


def run(args: argparse.Namespace) -> None:
    metas = dict(_kv(m, "meta") for m in (args.meta or []))
    extras: dict[str, dict[str, int]] = {}
    for spec in args.extra or []:
        lhs, n = _kv(spec, "extra")
        if ":" not in lhs:
            print(f"Error: --extra needs TARGET:tool=N, got {spec!r}", file=sys.stderr)
            sys.exit(2)
        tgt, tool = lhs.split(":", 1)
        extras.setdefault(tgt.strip(), {})[tool.strip()] = int(n)

    out = Path(args.output)
    tables: dict[str, tuple[pd.DataFrame, dict]] = {}
    for spec in args.candidates:
        target, path = _kv(spec, "candidates")
        p = Path(path)
        if not p.exists():
            print(f"Error: candidates file not found: {p}", file=sys.stderr)
            sys.exit(1)
        cand = read_csv_safe(p)
        missing = [c for c in ("Set", "Method", "Primary sequence") if c not in cand.columns]
        if missing:
            print(f"Error: {p} is not a candidates.csv (missing {missing})", file=sys.stderr)
            sys.exit(1)
        hits = select_hits(
            cand, target=target, per_tool=args.per_tool, refolded=args.refolded, extra=extras.get(target)
        )
        s = hits_summary(hits)
        s["per_tool_n"], s["refolded_n"] = args.per_tool, args.refolded
        if s["refolded_new"] < args.refolded:
            print(
                f"[hits] {target}: refold block exhausted at {s['refolded_new']} new designs "
                f"(asked for {args.refolded}) — widen the refold block to get more.",
                file=sys.stderr,
            )
        tables[target] = (hits, s)
        print(
            f"[hits] {target}: {s['rows']} rows = {s['per_tool']} per-tool + {s['refolded_new']} refolded "
            f"+ {s['already_covered']} already covered → {s['distinct_designs_to_test']} distinct designs to test"
        )
        if args.csv:
            csv_path = out.with_name(f"{out.stem}_{target}.csv")
            hits.to_csv(csv_path, index=False)
            print(f"  {csv_path}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        info = pd.DataFrame(
            [
                ["Version", "Date", "Contents"],
                [args.version, args.date or "", f"Implemented 7 methods: {_TOOLS}"],
                ["", "", f"Re-folding: {_ENGINES}"],
                ["", "", f"Re-scoring: {_ENGINES}"],
                ["", "", f"Global ranking: mean-ipTM of {_ENGINES}"],
                ["", "", f"Selection: top {args.per_tool} per tool + top {args.refolded} new by our ranking"],
            ]
        )
        info.to_excel(xl, sheet_name="BinderScout", index=False, header=False, startrow=3, startcol=1)
        for target, (hits, s) in tables.items():
            _write_sheet(xl, target[:31], hits, _meta(metas.get(target, "")), s, args.version)
    print(f"[hits] Written → {out}")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "hits",
        help="Build the wet-lab Selected Hits workbook from candidates.csv (top-N per tool + top-M refolded).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--candidates",
        required=True,
        action="append",
        metavar="TARGET=CSV",
        help="A target's candidates.csv, e.g. CALCA=report/candidates.csv. Repeat for one sheet per target.",
    )
    p.add_argument("--per-tool", type=int, default=12, help="Each tool's own top-N designs (default 12).")
    p.add_argument("--refolded", type=int, default=30, help="NEW designs taken off our ranking (default 30).")
    p.add_argument(
        "--extra",
        action="append",
        metavar="TARGET:tool=N",
        help="Extra per-tool slots, e.g. 2VDY:rfd3=3 for deliberately testing more of one tool.",
    )
    p.add_argument(
        "--meta",
        action="append",
        metavar="TARGET=k:v;k:v",
        help="Sheet header fields: name, uniprot, pdb, dashboard, note1, note2…",
    )
    p.add_argument("--version", default="1.0", help="BinderScout version written into the sheets (default 1.0).")
    p.add_argument("--date", default="", help="Date written into the info sheet.")
    p.add_argument("--csv", action="store_true", help="Also write one CSV per target beside the workbook.")
    p.add_argument("--output", "-o", required=True, metavar="XLSX", help="Output .xlsx path")
    p.set_defaults(func=run)


__all__ = ["HITS_COLUMNS", "add_parser", "run"]
