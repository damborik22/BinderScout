"""F43(c): `Evaluator/scripts/discover_tool_csvs.py` must match the layout the
configurator actually writes.

`bindmaster configure` generates run scripts that aggregate every tool into
``runs/<name>/<tool>/sequences.csv`` (see the ``check_outputs`` lines in
``write_run_all``), and Protein-Hunter's own ``boltz_ph/design.py`` writes its raw
summaries one level deeper, in ``protein_hunter/<run-name>/``.

The discovery helper's globs were written against ad-hoc SPARK layouts
(``**/pxdesign/summary.csv``, ``**/protein_hunter_*/summary_all_runs.csv``) and so
matched neither: ``pxdesign/`` holds a ``sequences.csv``, and ``protein_hunter``
does not match ``protein_hunter_*`` (that pattern needs the trailing underscore).
Result: `--tool-csv` was emitted for neither tool and the report fell back to a
degraded per-tool view.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "Evaluator" / "scripts" / "discover_tool_csvs.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("discover_tool_csvs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def discover():
    return _load_script()


@pytest.fixture
def canonical_run(tmp_path):
    """The directory tree `bindmaster configure` + `run_all.sh` produce."""
    run = tmp_path / "runs" / "CALCA_helix"
    files = [
        "pxdesign/sequences.csv",
        "proteina_complexa/sequences.csv",
        "rfd3/sequences.csv",
        "protein_hunter/sequences.csv",
        "protein_hunter/CALCA_helix/summary_all_runs.csv",
        "protein_hunter/CALCA_helix/summary_high_iptm.csv",
        "mosaic/designs.csv",
    ]
    for rel in files:
        p = run / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("sequence\nACDEFGHIKLMNPQRSTVWY\n")
    return tmp_path


def _found(discover, base: Path, tool: str) -> Path | None:
    return discover.find_best([base], discover._TOOL_PATTERNS[tool])


def test_pxdesign_is_found_in_the_canonical_layout(discover, canonical_run):
    hit = _found(discover, canonical_run, "pxdesign")
    assert hit is not None, "pxdesign/sequences.csv is what run_pxdesign.sh writes"
    assert hit.name == "sequences.csv"


def test_protein_hunter_is_found_in_the_canonical_layout(discover, canonical_run):
    hit = _found(discover, canonical_run, "protein_hunter")
    assert hit is not None, "protein_hunter/ does not match the old protein_hunter_* glob"


def test_protein_hunter_nested_summary_is_reachable(discover, canonical_run):
    """boltz_ph writes summary_all_runs.csv under save_dir/<name>/, not directly
    under save_dir — the old pattern also had the depth wrong."""
    matches = list(canonical_run.glob("**/protein_hunter*/**/summary_all_runs.csv"))
    assert [p.name for p in matches] == ["summary_all_runs.csv"]
    assert any("protein_hunter*/**" in p for p in discover._TOOL_PATTERNS["protein_hunter"])


def test_legacy_pxdesign_summary_csv_still_matches(discover, tmp_path):
    """Single-length PXDesign runs write summary.csv; do not regress them."""
    p = tmp_path / "old" / "pxdesign" / "summary.csv"
    p.parent.mkdir(parents=True)
    p.write_text("sequence\nACDE\n")
    assert _found(discover, tmp_path, "pxdesign") == p


def test_ad_hoc_protein_hunter_suffixed_dirs_still_match(discover, tmp_path):
    """The versioned dirs CLAUDE.md tells operators to create for param sweeps
    (protein_hunter_v2_700x5/) must keep matching."""
    p = tmp_path / "runs" / "x" / "protein_hunter_v2_700x5" / "summary_all_runs.csv"
    p.parent.mkdir(parents=True)
    p.write_text("sequence\nACDE\n")
    assert _found(discover, tmp_path, "protein_hunter") == p


def test_pdb_dir_discovery_sees_the_canonical_protein_hunter_dir(discover, canonical_run):
    """--tool-pdb-dir used the same protein_hunter_* glob, so it missed too."""
    ph = canonical_run / "runs" / "CALCA_helix" / "protein_hunter"
    (ph / "design_0.pdb").write_text("ATOM\n")
    hit = discover.find_best_dir([canonical_run], discover._TOOL_PDB_DIR_PATTERNS["protein_hunter"])
    assert hit == ph


def test_unchanged_tools_still_resolve(discover, canonical_run):
    """Guard the patterns this fix did not touch."""
    for tool in ("mosaic", "rfd3", "proteina_complexa"):
        assert _found(discover, canonical_run, tool) is not None, tool
