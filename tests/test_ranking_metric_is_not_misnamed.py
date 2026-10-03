"""Nothing user- or agent-facing may name a metric other than the real one as the rank.

This is the drift that made the fix necessary, and it is worth pinning because it is
invisible: the ranking itself was correct the whole time, so no run failed, no test went
red, and nothing in the output looked wrong. Only the labels were lying.

Measured 2026-10-03, four surfaces disagreed with ``rank_designs()`` at once:

* ``report.html``'s own glossary told the operator ``ipsae_min`` was "the primary ranking
  metric", in the same page that ranks by ``consensus_iptm_mean``.
* ``Evaluator/docs/pipeline_reference.md`` -- the file CLAUDE.md cites as THE metrics
  reference -- said the same in its metrics table.
* The orchestrator skill's ``references/evaluation.md`` instructed an agent to sort on
  ``agreement_count`` descending as the primary key.
* ``SKILL.md`` §6.3 said ``ipsae_min`` agreement "is what unifies them at the campaign's
  final ranking".

An agent following the third would have produced a differently-ordered shortlist from the
report's own and had no way to notice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The only correct answer. Kept as a literal rather than imported so that renaming the
# column in code cannot quietly satisfy this test.
RANK_METRIC = "consensus_iptm_mean"

# Surfaces that tell a human or an agent how designs are ranked.
SURFACES = [
    "Evaluator/binder_comparison/visualization/report.py",
    "Evaluator/docs/pipeline_reference.md",
    ".claude/skills/binderscout-orchestrator/references/evaluation.md",
    ".claude/skills/binderscout-orchestrator/SKILL.md",
]

# "<other metric> is the ranking metric" in the shapes these files actually used.
# Each pattern must NOT match any surface. `ipsae_min` and `agreement_count` are the two
# that really drifted; both are diagnostics.
WRONG_CLAIMS = [
    # "This is the primary ranking metric." in the ipsae_min glossary entry.
    re.compile(r"(?<!NOT )the primary ranking metric", re.I),
    # "Primary ranking metric. min(bt_ipSAE..." in a metrics table row.
    re.compile(r"\|\s*`ipsae_min`\s*\|[^|]*\|\s*Primary ranking metric", re.I),
    # "Primary sort: `agreement_count` descending"
    re.compile(r"Primary sort:\s*`?agreement_count`?", re.I),
    # "`ipsae_min` agreement is what unifies them at the ... final ranking"
    re.compile(r"`ipsae_min`\s+agreement is what unifies", re.I),
]


@pytest.mark.parametrize("rel", SURFACES)
def test_surface_does_not_misname_the_ranking_metric(rel: str) -> None:
    path = REPO / rel
    assert path.exists(), f"{rel} moved or was deleted — update SURFACES"
    text = path.read_text(encoding="utf-8")
    for pattern in WRONG_CLAIMS:
        m = pattern.search(text)
        assert m is None, (
            f"{rel} names something other than {RANK_METRIC} as the ranking metric: "
            f"{m.group(0)!r} at offset {m.start()}. There is ONE ranking (Part U): a "
            f"cross-engine gate, then {RANK_METRIC}. ipsae_min and agreement_count are "
            "diagnostics."
        )


@pytest.mark.parametrize("rel", SURFACES)
def test_surface_actually_names_the_real_one(rel: str) -> None:
    """The negative test alone is satisfiable by saying nothing at all.

    Deleting every mention of ranking from these files would pass the test above while
    leaving an operator with no idea what the order means, so each surface must also
    name the real metric.
    """
    text = (REPO / rel).read_text(encoding="utf-8")
    assert RANK_METRIC in text, (
        f"{rel} no longer mentions {RANK_METRIC}. Saying nothing is not a fix — these are "
        "the surfaces that explain the ordering to an operator or an agent."
    )


def test_report_glossary_says_ipsae_min_is_not_the_rank() -> None:
    """The positive form, on the string that actually ships in report.html.

    ``_METRIC_DESCRIPTION`` only renders for metrics present in the ``summary`` dict, and
    ``summary`` is built before the consensus columns exist — so the shipped per-tool table
    shows ``ipsae_min`` and does NOT show ``consensus_iptm_mean``. That asymmetry is why
    this entry in particular has to carry the correction.
    """
    from binder_comparison.visualization.report import _METRIC_DESCRIPTION

    desc = _METRIC_DESCRIPTION["ipsae_min"]
    assert "NOT the ranking metric" in desc
    assert RANK_METRIC in desc


def test_wetlab_criteria_string_matches_the_code() -> None:
    """The glossary listed SoluProt and agreement_count as criteria for the badge.

    Both are note-only now (SoluProt 2026-09-28, agreement_count 2026-10-03), so the
    string promised the operator a gate that no longer exists in
    ``annotate_wetlab_recommended``.
    """
    src = (REPO / "Evaluator/binder_comparison/visualization/report.py").read_text(encoding="utf-8")
    assert "SoluProt pass + agreement_count" not in src, (
        "report.html still describes wetlab_recommended as requiring SoluProt and "
        "agreement_count; both became note-only and cannot withhold the recommendation."
    )
