#!/usr/bin/env python3
"""Auto-discover per-tool native CSVs for `binder-compare report`.

Scans one or more base directories for known per-tool output file patterns
and emits ``--tool-csv NAME=PATH`` flags on stdout (one flag per line, ready
to be appended to a bash arg array).

When multiple candidates match a tool (e.g. BM4 Mosaic + BM2 Mosaic), the
**most recently modified** file wins — so a fresh re-run of a tool naturally
overrides an older one.

Usage:
    python discover_tool_csvs.py <base_dir> [<base_dir>...]
"""
from __future__ import annotations

import sys
from pathlib import Path

# tool name → list of glob patterns relative to each base dir.
# First-match-wins WITHIN a tool's pattern list; mtime-newest wins ACROSS
# multiple matches.
_TOOL_PATTERNS: dict[str, list[str]] = {
    "bindcraft":         ["**/bindcraft_default/outputs/final_design_stats.csv",
                          "**/bindcraft/outputs/final_design_stats.csv"],
    "boltzgen":          ["**/boltzgen/outputs/final_ranked_designs/final_designs_metrics_*.csv",
                          "**/boltzgen/outputs/**/final_designs_metrics_*.csv"],
    "mosaic":            ["**/mosaic/designs.csv"],
    "pxdesign":          ["**/pxdesign/pxdesign_top700.csv",   # SPARK-style pre-ranked top-N
                          "**/pxdesign/summary.csv"],
    "rfd3":              ["**/rfd3/rfd3_top700.csv",
                          "**/rfd3/sequences.csv"],
    "proteina_complexa": ["**/proteina_complexa/proteina_complexa_top700.csv",
                          "**/proteina_complexa/sequences.csv"],
    "protein_hunter":    ["**/protein_hunter_merged/protein_hunter_top700.csv",
                          "**/protein_hunter_*/summary_all_runs.csv"],
}

# tool → list of directory glob patterns to look for native design PDBs/CIFs.
# We emit `--tool-pdb-dir tool=<dir>` so the report's per-tool 3D viewer can
# load the tool's *original* design structures instead of falling back to
# refolded ones. Mosaic has no native PDBs (TOP_K=0). RFD3 / Protein-Hunter
# PDBs typically live on BM1 and aren't copied to BM5; the refold viewer
# handles those cases.
_TOOL_PDB_DIR_PATTERNS: dict[str, list[str]] = {
    "bindcraft":         ["**/bindcraft_default/outputs/Accepted",
                          "**/bindcraft_default/outputs/MPNN",
                          "**/bindcraft/outputs/Accepted"],
    "boltzgen":          ["**/boltzgen/outputs/final_ranked_designs/final_*_designs",
                          "**/boltzgen/outputs/final_ranked_designs"],
    "pxdesign":          ["**/pxdesign"],     # has nested outputs_len*/ subdirs; per-tool viewer rglobs
    "proteina_complexa": ["**/proteina_complexa/raw_evaluation_results",
                          "**/proteina_complexa"],
    "rfd3":              ["**/rfd3"],
    "protein_hunter":    ["**/protein_hunter_merged",
                          "**/protein_hunter_*"],
}


def find_best(base_dirs: list[Path], patterns: list[str]) -> Path | None:
    """Return the most-recently-modified file matching any pattern, or None."""
    candidates: list[Path] = []
    for base in base_dirs:
        if not base.is_dir():
            continue
        for pat in patterns:
            candidates.extend(p for p in base.glob(pat) if p.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _has_structural_data(d: Path, max_check: int = 5000) -> bool:
    """True if directory contains at least one .pdb / .cif (recursive)."""
    n = 0
    for p in d.rglob("*"):
        if not p.is_file():
            continue
        n += 1
        if n > max_check:
            return False  # don't scan forever
        suf = p.suffix.lower()
        if suf in (".pdb", ".cif"):
            return True
    return False


def find_best_dir(base_dirs: list[Path], patterns: list[str]) -> Path | None:
    """Most-recently-modified DIRECTORY matching any pattern THAT CONTAINS PDB/CIF.

    A pattern-match without any structural files is ignored — otherwise the
    auto-discoverer happily returns an empty `rfd3/` left over from CSV-only
    extracts and blocks the report from finding actual PDBs elsewhere.
    """
    candidates: list[Path] = []
    for base in base_dirs:
        if not base.is_dir():
            continue
        for pat in patterns:
            for p in base.glob(pat):
                if p.is_dir() and _has_structural_data(p):
                    candidates.append(p)
    if not candidates:
        return None

    def newest_mtime(d: Path) -> float:
        try:
            return max((c.stat().st_mtime for c in d.rglob("*") if c.is_file()), default=d.stat().st_mtime)
        except (OSError, ValueError):
            return d.stat().st_mtime

    return max(candidates, key=newest_mtime)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: discover_tool_csvs.py BASE_DIR [BASE_DIR ...]", file=sys.stderr)
        return 1
    base_dirs = [Path(a).resolve() for a in argv[1:]]
    for tool, patterns in _TOOL_PATTERNS.items():
        hit = find_best(base_dirs, patterns)
        if hit is not None:
            # One arg per line; bash reads with `mapfile`/`while read`.
            print(f"--tool-csv\n{tool}={hit}")
    # Native PDB directories (optional; only useful for the per-tool 3D viewer
    # that loads design-time structures). Missing dirs are silently skipped,
    # in which case the report falls back to its refold-PDB viewer.
    for tool, patterns in _TOOL_PDB_DIR_PATTERNS.items():
        hit_dir = find_best_dir(base_dirs, patterns)
        if hit_dir is not None:
            print(f"--tool-pdb-dir\n{tool}={hit_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
