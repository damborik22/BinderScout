"""Regression tests for F27 — the TUI knew only 4 of the 7 design tools.

``tui/app.py`` hardcoded ``("mosaic", "boltzgen", "bindcraft", "pxdesign")`` in
three separate loops (run-status line, curses status view, fallback status view)
plus a fourth 4-entry literal in ``_detect_tools``. A run that produced
Proteina-Complexa, RFD3 or Protein-Hunter designs therefore showed as having no
tool output, while ``configurator.cmd_status`` listed all seven.

These tests pin both halves of the fix: all seven tools are known, and there is
exactly ONE place that enumerates them.
"""

import ast
import sys
from pathlib import Path

import tui.app as app

REPO_ROOT = Path(__file__).resolve().parents[2]

# The seven design tools, spelled out here on purpose: this is the spec the TUI
# must meet, so the behavioural tests below stay independent of app.TOOL_SEQUENCE.
# (output subdir under runs/<name>/, display label)
EXPECTED_TOOLS = [
    ("mosaic", "Mosaic"),
    ("boltzgen", "BoltzGen"),
    ("bindcraft", "BindCraft"),
    ("pxdesign", "PXDesign"),
    ("proteina_complexa", "Proteina-Complexa"),
    ("rfd3", "RFD3"),
    ("protein_hunter", "Protein-Hunter"),
]
EXPECTED_SUBDIRS = {subdir for subdir, _label in EXPECTED_TOOLS}


def _normalise(text: str) -> str:
    """Fold labels and subdir names together ("Proteina-Complexa" ~ proteina_complexa)."""
    return text.lower().replace("-", "_")


def _tool_name_literals(source: str) -> list[tuple[str, ...]]:
    """Tuple/list literals that enumerate tool names inline — the F27 defect.

    A collection of plain strings containing two or more tool names is a
    hardcoded tool list. ``TOOL_SEQUENCE`` itself is a list of *tuples*, and each
    inner tuple names exactly one tool, so the table does not match.
    """
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Tuple | ast.List):
            strings = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(EXPECTED_SUBDIRS.intersection(strings)) >= 2:
                hits.append(tuple(strings))
    return hits


def test_only_one_hardcoded_tool_list_in_the_tui():
    """No loop may re-enumerate the tools; every surface must iterate the table."""
    hits = _tool_name_literals(Path(app.__file__).read_text())
    assert hits == [], f"tool names enumerated outside TOOL_SEQUENCE: {hits}"


def test_tool_sequence_knows_all_seven_tools():
    assert len(app.TOOL_SEQUENCE) == 7
    subdirs = [subdir for subdir, _label, _marker in app.TOOL_SEQUENCE]
    assert set(subdirs) == EXPECTED_SUBDIRS
    assert len(subdirs) == len(set(subdirs)), "duplicate output subdir in TOOL_SEQUENCE"
    assert [(subdir, label) for subdir, label, _marker in app.TOOL_SEQUENCE] == EXPECTED_TOOLS


def test_run_status_line_reports_every_tool(tmp_path):
    """A run with output from all seven tools must name all seven."""
    run_dir = tmp_path / "runs" / "CALCA"
    for subdir, _label in EXPECTED_TOOLS:
        (run_dir / subdir).mkdir(parents=True)
        (run_dir / subdir / "sequences.csv").write_text("")

    line = _normalise(app._run_status_line(run_dir))

    for subdir, label in EXPECTED_TOOLS:
        assert _normalise(label) in line, f"{label} missing from run status line: {line}"
        assert subdir in line


def test_run_status_line_ignores_empty_tool_dirs(tmp_path):
    """An empty (or absent) tool dir must not be reported as having output."""
    run_dir = tmp_path / "runs" / "CALCA"
    (run_dir / "rfd3").mkdir(parents=True)  # created but empty
    (run_dir / "protein_hunter" / "CALCA").mkdir(parents=True)  # PH's {name}/ subdir

    assert app._run_status_line(run_dir) == "Protein-Hunter"
    assert "configured" in app._run_status_line(tmp_path / "runs" / "never-launched")


def test_detect_tools_covers_all_seven(tmp_path):
    """The header "Tools:" bar must list all seven, not just the original four."""
    for _subdir, label, marker in app.TOOL_SEQUENCE:
        if label == "RFD3":
            continue  # left uninstalled to prove the check is not vacuously true
        path = tmp_path / marker
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    detected = app._detect_tools(tmp_path)

    assert [_normalise(name) for name in detected] == [_normalise(label) for _s, label in EXPECTED_TOOLS]
    assert detected["Proteina-Complexa"] is True
    assert detected["Protein-Hunter"] is True
    assert detected["RFD3"] is False


def test_tui_and_configurator_tool_tables_agree():
    """Drift guard: an 8th tool added to the configurator must reach the TUI too.

    The TUI is stdlib-only and standalone, so it cannot import the configurator —
    the two tables are maintained separately and only this test ties them.
    """
    sys.path.insert(0, str(REPO_ROOT / "configurator"))
    import configurator as conf

    conf_pairs = [(subdir, label) for _key, _script, label, subdir in conf.TOOL_SEQUENCE]
    tui_pairs = [(subdir, label) for subdir, label, _marker in app.TOOL_SEQUENCE]
    assert tui_pairs == conf_pairs
