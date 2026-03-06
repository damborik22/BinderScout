"""
Parse PXDesign output summary.csv and map to BindMaster unified scoring.
"""

from __future__ import annotations

import csv
from pathlib import Path

COLUMN_MAP = {
    "af2_ipTM": "af2_iptm",
    "af2_ipAE": "af2_ipae",
    "af2_pLDDT": "af2_plddt",
    "af2_binder_RMSD": "af2_binder_rmsd",
    "ptx_ipTM": "ptx_iptm",
    "ptx_pTM": "ptx_ptm",
    "ptx_complex_RMSD": "ptx_complex_rmsd",
    "AF2-IG-success": "passes_af2ig_strict",
    "AF2-IG-easy-success": "passes_af2ig_easy",
    "Protenix-success": "passes_protenix_strict",
    "Protenix-basic-success": "passes_protenix_basic",
}

FILTER_THRESHOLDS = {
    "AF2-IG-easy": {
        "af2_ipae": ("<", 10.85),
        "af2_iptm": (">", 0.50),
        "af2_plddt": (">", 0.80),
        "af2_binder_rmsd": ("<", 3.50),
    },
    "AF2-IG": {
        "af2_ipae": ("<", 7.00),
        "af2_plddt": (">", 0.90),
        "af2_binder_rmsd": ("<", 1.50),
    },
    "Protenix-basic": {
        "ptx_iptm": (">", 0.80),
        "ptx_ptm": (">", 0.80),
        "ptx_complex_rmsd": ("<", 2.50),
    },
    "Protenix": {
        "ptx_iptm": (">", 0.85),
        "ptx_ptm": (">", 0.88),
        "ptx_complex_rmsd": ("<", 2.50),
    },
}


def parse_summary_csv(summary_csv: Path) -> list[dict]:
    """Parse PXDesign summary.csv into a list of design record dicts."""
    if not summary_csv.exists():
        raise FileNotFoundError(f"PXDesign summary not found: {summary_csv}")

    records = []
    with open(summary_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record = {}
            for csv_col, bm_field in COLUMN_MAP.items():
                raw = row.get(csv_col)
                if raw is None or raw == "":
                    record[bm_field] = None
                elif bm_field.startswith("passes_"):
                    record[bm_field] = str(raw).strip().lower() in ("true", "1", "yes")
                else:
                    try:
                        record[bm_field] = float(raw)
                    except (ValueError, TypeError):
                        record[bm_field] = None

            record["design_file"] = row.get("design_file") or row.get("file") or row.get("id")
            records.append(record)

    return records


def get_passing_designs(
    summary_csv: Path,
    filter_name: str = "Protenix-basic",
) -> list[dict]:
    """Return only designs passing a specific filter."""
    records = parse_summary_csv(summary_csv)
    filter_key = {
        "AF2-IG-easy": "passes_af2ig_easy",
        "AF2-IG": "passes_af2ig_strict",
        "Protenix-basic": "passes_protenix_basic",
        "Protenix": "passes_protenix_strict",
    }.get(filter_name)

    if not filter_key:
        raise ValueError(f"Unknown filter '{filter_name}'. Choose from: AF2-IG-easy, AF2-IG, Protenix-basic, Protenix")

    return [r for r in records if r.get(filter_key) is True]


def summarize_run(summary_csv: Path) -> dict:
    """Print a quick summary of a PXDesign run."""
    records = parse_summary_csv(summary_csv)
    n_total = len(records)

    summary = {
        "total_designs": n_total,
        "passes_af2ig_easy": sum(1 for r in records if r.get("passes_af2ig_easy")),
        "passes_af2ig_strict": sum(1 for r in records if r.get("passes_af2ig_strict")),
        "passes_protenix_basic": sum(1 for r in records if r.get("passes_protenix_basic")),
        "passes_protenix_strict": sum(1 for r in records if r.get("passes_protenix_strict")),
    }

    print(f"\n[pxdesign] Run summary ({summary_csv.parent.name}):")
    print(f"  Total designs:      {n_total:>6}")
    print(
        f"  AF2-IG easy pass:   {summary['passes_af2ig_easy']:>6} "
        f"({100 * summary['passes_af2ig_easy'] / max(n_total, 1):.1f}%)"
    )
    print(
        f"  AF2-IG strict pass: {summary['passes_af2ig_strict']:>6} "
        f"({100 * summary['passes_af2ig_strict'] / max(n_total, 1):.1f}%)"
    )
    print(
        f"  Protenix basic:     {summary['passes_protenix_basic']:>6} "
        f"({100 * summary['passes_protenix_basic'] / max(n_total, 1):.1f}%)"
    )
    print(
        f"  Protenix strict:    {summary['passes_protenix_strict']:>6} "
        f"({100 * summary['passes_protenix_strict'] / max(n_total, 1):.1f}%)"
    )

    return summary
