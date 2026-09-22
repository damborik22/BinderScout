"""Every tool must appear in every per-tool lookup that gates rendering.

Registering a design tool means adding its key to thirteen separate dicts plus a
CSS block, spread over six modules. Nothing checked that, so the eighth tool was
added to twelve of them and the report emitted ``class="tool-bindcraft2"`` nine
times with no rule defining it — shipped, and invisible, because an unstyled
span still renders, just unstyled.

These tests derive the expected set from ``CANONICAL_TOOL_ORDER`` rather than
restating it, so the next tool is caught by adding one entry rather than by
remembering to update a spec list here too.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))

from binder_comparison.cli import report as cli_report
from binder_comparison.comparison import candidates, hits, tool_classification
from binder_comparison.visualization import plots, top30_slim
from binder_comparison.visualization import report as viz_report

# (module path for the failure message, the dict itself)
_LOOKUPS: list[tuple[str, dict]] = [
    ("comparison/candidates.py TOOL_DISPLAY_NAMES", candidates.TOOL_DISPLAY_NAMES),
    ("comparison/hits.py TOOL_CODE_SLUGS", hits.TOOL_CODE_SLUGS),
    ("comparison/tool_classification.py TOOL_CLASSIFICATION", tool_classification.TOOL_CLASSIFICATION),
    ("visualization/plots.py TOOL_COLOURS", plots.TOOL_COLOURS),
    ("visualization/plots.py _TOOL_DISPLAY", plots._TOOL_DISPLAY),
    ("visualization/plots.py _ENGINE_BAR_LABEL", plots._ENGINE_BAR_LABEL),
    ("visualization/report.py _TOOL_COLOURS_NGL", viz_report._TOOL_COLOURS_NGL),
    ("visualization/top30_slim.py _TOOLCOL", top30_slim._TOOLCOL),
    ("cli/report.py _TOOL_COLOURS_PYMOL", cli_report._TOOL_COLOURS_PYMOL),
    ("cli/report.py _TOOL_DISPLAY_PYMOL", cli_report._TOOL_DISPLAY_PYMOL),
]


@pytest.mark.parametrize(("where", "lookup"), _LOOKUPS, ids=[w for w, _ in _LOOKUPS])
def test_every_canonical_tool_is_registered(where, lookup):
    missing = [t for t in candidates.CANONICAL_TOOL_ORDER if t not in lookup]
    assert not missing, f"{where} is missing: {missing}"


def test_every_canonical_tool_has_a_css_rule():
    """The class is emitted from the tool key, so a missing rule renders unstyled."""
    styled = set(re.findall(r"\.tool-([a-z0-9_]+)\s*\{\{", viz_report._HTML_TEMPLATE))
    missing = [t for t in candidates.CANONICAL_TOOL_ORDER if t not in styled]
    assert not missing, f"no .tool-<key> CSS rule for: {missing}"


def test_tool_colours_are_distinct():
    """Two tools sharing a colour makes the table that separates them useless."""
    used: dict[str, str] = {}
    for tool in candidates.CANONICAL_TOOL_ORDER:
        colour = plots.TOOL_COLOURS.get(tool)
        if colour is None:
            continue
        assert colour not in used, f"{tool} and {used[colour]} share the colour {colour}"
        used[colour] = tool


def test_tool_links_cover_every_tool():
    missing = [t for t in candidates.CANONICAL_TOOL_ORDER if t not in viz_report._TOOL_LINKS]
    assert not missing, f"visualization/report.py _TOOL_LINKS is missing: {missing}"


def test_bindcraft2_is_not_linked_to_bindcraft_1():
    """It is a different tool, not a version of BindCraft — the first attempt
    linked it to martinpacesa/BindCraft, which is BindCraft 1's repository."""
    link = viz_report._TOOL_LINKS.get("bindcraft2")
    assert link is None or "martinpacesa/BindCraft" not in link


def test_bindcraft2_classification_names_its_real_ranking_metric():
    """It ranks on i_pDAE, not i_pTM and not a composite — verified against all
    100 rows of the two delivered pools and against its own campaign output."""
    note = tool_classification.TOOL_CLASSIFICATION["bindcraft2"].native_metric_interpretation
    assert "i_pDAE" in note
    # The original text claimed the export was ordered by a "composite Rank".
    # The corrected text may say "not a composite", so match the claim, not the word.
    assert "composite rank" not in note.lower()
