"""Part AA's zero-dependency core: the ProtParam panel and the composition gate.

Both are computed from the `sequence` column that is already in the frame, so
neither needs a join — which is what keeps them clear of the row-multiplication
class of defect that corrupted `rank` (see test_report_attach_joins.py).

The composition gate ships in SHADOW MODE: it emits `would_exclude_composition`
and excludes nothing. Per the 2.0 plan, a pre-GPU filter may only start
excluding once it has been shown to remove zero confirmed binders on a
calibration pool, and no such pool exists yet.
"""

import pandas as pd
import pytest
from binder_comparison.comparison.sequence_panel import (
    COMPOSITION_THRESHOLDS,
    annotate_composition,
    annotate_sequence_panel,
    composition_features,
)

# A well-behaved designed helix, and a Pro/Gly coil of the kind RFD3 produces
# when infer_ori_strategy is missing (CLAUDE.md records that failure mode).
GOOD = "MKWVTFISLLLLFSSAYSRGVFRRDAHKSEVAHRFKDLGEENFKALVLIAFAQYLQQCPFEDHVKLVNE"
COIL = "GPGPGPGGGGPGPGPGGPGPGPGGGGPGPGPGGPGPGPGGGGPGPGPGGPGPGPGGGGPGPGPGGPGP"


def _frame(seqs):
    return pd.DataFrame({"binder_id": [f"d{i}" for i in range(len(seqs))], "sequence": list(seqs)})


# ---------------------------------------------------------------- ProtParam


def test_panel_adds_biophysical_columns():
    out = annotate_sequence_panel(_frame([GOOD, COIL]))
    for col in (
        "native_length",
        "native_mw",
        "native_pi",
        "native_extinction_280",
        "native_gravy",
        "native_aromatic_fraction",
    ):
        assert col in out.columns, f"{col} missing from the panel"
    assert out["native_length"].tolist() == [len(GOOD), len(COIL)]
    assert out["native_mw"].iloc[0] > 0


def test_panel_never_changes_the_row_count():
    """It is computed from the frame, not joined onto it."""
    df = _frame([GOOD, GOOD, COIL])  # a duplicated sequence must be harmless
    assert len(annotate_sequence_panel(df)) == 3


def test_panel_tolerates_a_missing_or_empty_sequence():
    df = pd.DataFrame({"binder_id": ["a", "b"], "sequence": [GOOD, ""]})
    out = annotate_sequence_panel(df)
    assert len(out) == 2
    assert out["native_length"].tolist() == [len(GOOD), 0]


def test_panel_avoids_the_names_that_auto_create_composites():
    """compute_composite_scores fires on the PRESENCE of native_dG +
    native_dSASA, and apply_screening_thresholds on
    native_shape_complementarity. A panel column must never be named into
    those, or an advisory column silently becomes a ranking input."""
    out = annotate_sequence_panel(_frame([GOOD]))
    for forbidden in ("native_dG", "native_dSASA", "native_shape_complementarity"):
        assert forbidden not in out.columns


# -------------------------------------------------------------- composition


def test_composition_features_separate_a_helix_from_a_pro_gly_coil():
    good = composition_features(GOOD)
    coil = composition_features(COIL)
    assert coil["comp_pro_gly_frac"] > good["comp_pro_gly_frac"]
    assert coil["comp_hydrophobic_frac"] < good["comp_hydrophobic_frac"]
    assert coil["comp_has_gggg"] is True
    assert good["comp_has_gggg"] is False


def test_composition_entropy_alone_does_not_catch_the_coil():
    """Recorded in CLAUDE.md: a Pro/Gly coil passes both the alanine and the
    Shannon-entropy checks, which is why the gate reads Pro+Gly and hydrophobic
    fraction instead. This test exists so that reasoning cannot be quietly lost."""
    coil = composition_features(COIL)
    assert coil["comp_ala_frac"] <= COMPOSITION_THRESHOLDS["max_ala_frac"]
    assert coil["comp_pro_gly_frac"] > COMPOSITION_THRESHOLDS["max_pro_gly_frac"]


def test_composition_is_shadow_mode_and_excludes_nothing():
    out = annotate_composition(_frame([GOOD, COIL]))
    assert "would_exclude_composition" in out.columns
    assert len(out) == 2, "shadow mode must not drop a single row"
    assert out.loc[out.sequence == COIL, "would_exclude_composition"].item() is True
    assert out.loc[out.sequence == GOOD, "would_exclude_composition"].item() is False


def test_composition_records_why():
    """A bare boolean is not actionable when someone asks why a design was flagged."""
    out = annotate_composition(_frame([COIL]))
    reason = out["composition_reason"].item()
    assert reason, "no reason recorded for a flagged design"
    assert "pro_gly" in reason


@pytest.mark.parametrize("seq", ["", "XXXX", "M"])
def test_composition_survives_degenerate_sequences(seq):
    out = annotate_composition(_frame([seq]))
    assert len(out) == 1
