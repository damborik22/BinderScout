"""The report must print the thresholds it actually applied.

`--threshold-boltz` / `--threshold-af3` / `--threshold-esmfold2` change what
`apply_screening_thresholds` and `compute_agreement` compute, but every label in
the HTML retyped "0.61" — so a report run with `--threshold-af3 0.75` computed
against 0.75 and told the reader 0.61, with no way to notice. The tier bands
(0.80 / 0.61 / 0.40) were likewise retyped in 18 places, so editing a scoring
constant relabelled nothing.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.comparison.scoring import (
    _ENGINE_IPSAE_COLS,
    IPSAE_HIGH_THRESHOLD,
    IPSAE_MIN_THRESHOLD,
    IPSAE_PASS_THRESHOLD,
)
from binder_comparison.visualization.report import (
    _active_engines,
    _agreement_phrase,
    _engine_threshold_legend_html,
    _resolve_thresholds,
    _screening_summary_intro_html,
    _slim_legend_html,
    _tier_summary_to_html,
    _top_table_legend_html,
)


def _df(engines=("boltz", "af3", "esmfold2"), n=3):
    """A frame carrying exactly the given engines' ipSAE columns."""
    data = {
        "binder_id": [f"d{i}" for i in range(n)],
        "source_tool": ["mosaic"] * n,
        "ipsae_min": [0.9, 0.7, 0.3][:n],
        "quality_tier": ["high", "medium", "reject"][:n],
        "agreement_count": [3, 2, 0][:n],
    }
    for engine in engines:
        data[_ENGINE_IPSAE_COLS[engine]] = [0.9, 0.7, 0.3][:n]
    return pd.DataFrame(data)


class TestPerEngineCutoffsAreTheAppliedOnes:
    """The legend is the one place a reader can check what --threshold-* was set to."""

    def test_defaults_render_the_default_cutoff(self):
        html = _engine_threshold_legend_html(_df())
        for name in ("Boltz-2", "AF3", "ESMFold2"):
            assert f"{name} ≥ {IPSAE_PASS_THRESHOLD:.2f}" in html

    def test_an_override_is_shown_not_swallowed(self):
        html = _engine_threshold_legend_html(_df(), {"af3": 0.75})
        assert "AF3 ≥ 0.75" in html
        # ...and the engines that were NOT overridden keep the default.
        assert f"Boltz-2 ≥ {IPSAE_PASS_THRESHOLD:.2f}" in html

    def test_every_engine_can_be_overridden_independently(self):
        html = _engine_threshold_legend_html(_df(), {"boltz": 0.5, "af3": 0.75, "esmfold2": 0.9})
        assert "Boltz-2 ≥ 0.50" in html
        assert "AF3 ≥ 0.75" in html
        assert "ESMFold2 ≥ 0.90" in html

    def test_only_engines_that_ran_are_listed(self):
        html = _engine_threshold_legend_html(_df(engines=("boltz",)))
        assert "Boltz-2" in html
        assert "AF3" not in html
        assert "ESMFold2" not in html

    def test_no_engines_renders_nothing_rather_than_an_empty_legend(self):
        assert _engine_threshold_legend_html(_df(engines=())) == ""

    def test_resolve_merges_overrides_over_defaults(self):
        assert _resolve_thresholds({"af3": 0.75})["af3"] == 0.75
        assert _resolve_thresholds({"af3": 0.75})["boltz"] == IPSAE_PASS_THRESHOLD
        assert _resolve_thresholds(None)["esmfold2"] == IPSAE_PASS_THRESHOLD


class TestAgreementDescribesTheEnginesThatRan:
    """`agreement_count` has a smaller ceiling when an engine is skipped, so
    "0–3" made a perfectly good 2-of-2 design look like it failed one of three."""

    def test_three_engines(self):
        phrase = _agreement_phrase(_df(), _resolve_thresholds(None))
        assert "3 engines" in phrase
        assert "0–3" in phrase
        assert f"&gt; {IPSAE_PASS_THRESHOLD:.2f}" in phrase

    def test_two_engines_says_two_not_three(self):
        phrase = _agreement_phrase(_df(engines=("boltz", "af3")), _resolve_thresholds(None))
        assert "2 engines" in phrase
        assert "0–2" in phrase
        assert "0–3" not in phrase
        assert "ESMFold2" not in phrase

    def test_mixed_cutoffs_are_spelled_out_per_engine(self):
        phrase = _agreement_phrase(_df(), _resolve_thresholds({"af3": 0.75}))
        assert "AF3 0.75" in phrase
        assert f"Boltz-2 {IPSAE_PASS_THRESHOLD:.2f}" in phrase

    def test_uniform_cutoffs_stay_terse(self):
        phrase = _agreement_phrase(_df(), _resolve_thresholds(None))
        assert "own cutoff" not in phrase

    def test_active_engines_is_driven_by_the_columns_present(self):
        assert _active_engines(_df()) == ["boltz", "af3", "esmfold2"]
        assert _active_engines(_df(engines=("esmfold2",))) == ["esmfold2"]

    @pytest.mark.parametrize("legend", [_slim_legend_html, None])
    def test_legends_do_not_claim_three_engines_when_two_ran(self, legend):
        df = _df(engines=("boltz", "af3"))
        html = _slim_legend_html(df) if legend else _top_table_legend_html("two_stage", df)
        assert "0–3" not in html
        assert "of the 3 engines" not in html


_RENDERERS = [
    lambda df: _tier_summary_to_html(df),
    lambda df: _screening_summary_intro_html("two_stage"),
    lambda df: _slim_legend_html(df),
    lambda df: _top_table_legend_html("two_stage", df),
    lambda df: _top_table_legend_html("adaptyv", df),
]


class TestTierBandsComeFromTheConstants:
    """A band retyped as a literal cannot follow the constant it claims to show."""

    @pytest.mark.parametrize("render", _RENDERERS)
    def test_rendered_bands_match_the_scoring_constants(self, render):
        html = render(_df())
        assert f"{IPSAE_HIGH_THRESHOLD:.2f}" in html or f"{IPSAE_PASS_THRESHOLD:.2f}" in html

    def test_tier_table_labels_all_three_bands_from_constants(self):
        html = _tier_summary_to_html(_df())
        assert f"High (&gt;{IPSAE_HIGH_THRESHOLD:.2f})" in html
        assert f"Medium (&gt;{IPSAE_PASS_THRESHOLD:.2f})" in html
        assert f"Low (&gt;{IPSAE_MIN_THRESHOLD:.2f})" in html
        assert f"Reject (≤{IPSAE_MIN_THRESHOLD:.2f})" in html

    def test_no_renderer_hardcodes_a_band_that_disagrees_with_the_constants(self):
        """Guards the specific drift: someone edits IPSAE_HIGH_THRESHOLD and the
        report keeps printing the old number next to newly-computed tiers."""
        src = (Path(__file__).resolve().parents[2] / "Evaluator/binder_comparison/visualization/report.py").read_text()
        body = "\n".join(
            line
            for line in src.splitlines()
            # Skip the comments that quote the old literals to explain the fix.
            if not line.lstrip().startswith("#") and "retyped" not in line and "hardcoded" not in line
        )
        for literal in ("&gt;0.80", "&gt;0.61", "&gt;0.40", "&gt; 0.80", "&gt; 0.61", "&gt; 0.40"):
            assert literal not in body, f"threshold literal {literal!r} retyped in report.py"


class TestSlimTableTiersMatchTheFullReport:
    """`top30_slim._tier` was a second, independent copy of the tier cutoffs, so the
    slim table could colour a row differently from the tier the full report assigned."""

    def test_tier_boundaries_follow_the_constants(self):
        from binder_comparison.visualization.top30_slim import _tier

        assert _tier(IPSAE_HIGH_THRESHOLD + 0.01) == "high"
        assert _tier(IPSAE_HIGH_THRESHOLD) == "med"  # strict >, as scoring does
        assert _tier(IPSAE_PASS_THRESHOLD + 0.01) == "med"
        assert _tier(IPSAE_PASS_THRESHOLD) == "low"
        assert _tier(IPSAE_MIN_THRESHOLD + 0.01) == "low"
        assert _tier(IPSAE_MIN_THRESHOLD) == "rej"

    def test_nan_is_its_own_band(self):
        from binder_comparison.visualization.top30_slim import _tier

        assert _tier(float("nan")) == "na"

    def test_slim_agrees_with_the_reports_quality_tier(self):
        """Same value, same band — the two implementations must not diverge."""
        from binder_comparison.comparison.scoring import apply_screening_thresholds
        from binder_comparison.visualization.top30_slim import _tier

        vals = [0.95, 0.81, 0.80, 0.70, 0.61, 0.50, 0.40, 0.10]
        df = pd.DataFrame({"boltz_pae_ipsae_min": vals, "ipsae_min": vals})
        tiers = apply_screening_thresholds(df, primary_engine="boltz")["quality_tier"].tolist()
        short = {"high": "high", "medium": "med", "low": "low", "reject": "rej"}
        assert [_tier(v) for v in vals] == [short[t] for t in tiers]
