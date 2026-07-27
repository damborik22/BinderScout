"""Every column the report can display needs a `METRIC_META` label.

`_df_to_html` renders a column's header from `plots.METRIC_META`, falling back to
the raw column name. The fallback is silent, so a column added to a display set
without a matching label shipped as `af3_ipsae_min` sitting next to
`Boltz ipSAE_min ↑ [0–1]` in the same table — 26 of the 50 displayable columns
were in that state, including both non-Boltz engines' ipSAE and every
interface-QC and epitope column.

This is the guard: it derives the displayable set from `_select_display_cols`
itself, so a new column reaches this test the moment it reaches a table.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.comparison.scoring import _ENGINE_IPSAE_COLS
from binder_comparison.visualization.plots import METRIC_META
from binder_comparison.visualization.report import _ADVISORY_SECONDARY, _select_display_cols

_RANK_METHODS = ("two_stage", "consensus_iptm", "adaptyv")

# The refold engines that can actually populate an ipSAE column. `_ENGINE_IPSAE_COLS`
# also carries an "af2" entry left over from before Part I removed AF2 refolding:
# no runner, merger or schema field writes `af2_ipsae_min` any more (the surviving
# af2 fields are PXDesign's and Proteina-Complexa's own native metrics), so it can
# never reach a table and needs no label. Kept out of this parametrisation rather
# than labelled, so a label is not invented for a column that cannot appear.
_LIVE_ENGINES = ("boltz", "af3", "esmfold2")

# Columns a report can carry. Anything a display set may select must be here so
# the selector actually returns it (it filters on `c in df.columns`).
_CANDIDATE_COLS = [
    "binder_id",
    "source_tool",
    "sequence",
    "binder_length",
    "quality_tier",
    "agreement_count",
    "passes_max_screen",
    "consensus_iptm",
    "consensus_iptm_mean",
    "consensus_iptm_min",
    "consensus_iptm_spread",
    "consensus_iptm_n",
    "consensus_ipsae_min_mean",
    "two_stage_rank",
    "consensus_rank",
    "adaptyv_rank",
    "ipsae_min",
    "plddt_binder_mean",
    "plddt_binder_min",
    "binder_ptm",
    "iptm",
    "native_soluprot_score",
    "af3_iptm",
    "esmfold2_iptm",
    "boltz_pae_iptm",
    "wetlab_recommended",
    "wetlab_reason",
    *_ENGINE_IPSAE_COLS.values(),
    *_ADVISORY_SECONDARY,
]


def _displayable_columns() -> set[str]:
    """Union of every column the three rank methods can put in a table."""
    df = pd.DataFrame({c: [0] for c in dict.fromkeys(_CANDIDATE_COLS)})
    cols: set[str] = set()
    for method in _RANK_METHODS:
        primary, secondary = _select_display_cols(df, rank_method=method)
        cols |= set(primary) | set(secondary)
    return cols


class TestEveryDisplayedColumnHasALabel:
    def test_no_displayable_column_falls_back_to_its_raw_name(self):
        missing = sorted(c for c in _displayable_columns() if c not in METRIC_META)
        assert not missing, (
            "these columns would render as raw names in the report: "
            + ", ".join(missing)
            + " — add them to plots.METRIC_META"
        )

    @pytest.mark.parametrize("engine", sorted(_LIVE_ENGINES))
    def test_every_engine_ipsae_column_is_labelled(self, engine):
        """Regression: only Boltz had one, so AF3/ESMFold2 printed raw."""
        col = _ENGINE_IPSAE_COLS[engine]
        assert col in METRIC_META, f"{col} has no display label"
        label, _unit, direction = METRIC_META[col]
        assert col not in label, f"{col}'s label is just the column name"
        assert direction == "↑", "ipSAE_min is higher-is-better"


class TestLabelsAreWellFormed:
    def test_no_label_is_its_own_column_name(self):
        offenders = [c for c, (label, _u, _d) in METRIC_META.items() if label == c]
        assert not offenders, f"placeholder labels: {offenders}"

    def test_directions_are_valid(self):
        bad = {c: d for c, (_l, _u, d) in METRIC_META.items() if d not in ("↑", "↓", "")}
        assert not bad, f"invalid direction arrows: {bad}"

    def test_labels_are_unique_where_it_matters(self):
        """Two different metrics sharing a header make a table unreadable.

        `two_stage_rank`/`consensus_rank` deliberately share "Rank" — only one
        rank column is ever displayed at a time, so they cannot collide.
        """
        allowed_shared = {"Rank"}
        seen: dict[str, str] = {}
        clashes = []
        for col, (label, _u, _d) in METRIC_META.items():
            if label in allowed_shared:
                continue
            if label in seen:
                clashes.append(f"{seen[label]} and {col} both render as {label!r}")
            seen[label] = col
        assert not clashes, "; ".join(clashes)

    def test_interface_directions_match_the_qc_thresholds(self):
        """The QC gate in cli/qc_annotate.py is the source of truth for these,
        so the arrow a reader sees must agree with the filter that judges them."""
        expected = {
            "interface_dG": "↓",  # dG <= dg_max
            "interface_sc": "↑",  # sc >= sc_min
            "interface_interface_hbonds": "↑",  # hbonds >= hbonds_min
            "interface_delta_unsat_hbonds": "↓",  # unsat <= unsat_max
            "interface_nres": "↑",  # nres >= nres_min
        }
        for col, direction in expected.items():
            assert METRIC_META[col][2] == direction, f"{col} arrow disagrees with its QC threshold"
