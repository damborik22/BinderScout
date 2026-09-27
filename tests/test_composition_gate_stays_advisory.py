"""The composition gate must stay shadow-mode, and the reason is measurable.

The gate is a pre-GPU sequence filter. Turning it on would be attractive — it
costs nothing and would cut refold time — which is exactly why the bar for
promoting it is that it removes **zero confirmed binders** on a calibration pool.

Measured 2026-09-27 on ``tests/integration/golden_pool`` (six real BindCraft 2
designs against CALCA, all three engines, the rank-1 design at
``consensus_iptm_mean`` 0.918): the gate flags **6 of 6**. Two thresholds carried
over from ``tools/rfd3_gate.py`` are responsible — the hydrophobic floor sits
above the pool's mean and the Glu+Arg ceiling sits at it — because RFD3's failure
mode is a Pro/Gly coil while BindCraft 2 makes charged helices.

This test pins that measurement so the finding cannot quietly decay into
"someone once worried about this". It asserts the two thresholds that transfer
still transfer, and that the two that do not are still only advisory.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.sequence_panel import (  # noqa: E402
    _HYDROPHOBIC,
    COMPOSITION_THRESHOLDS,
    annotate_composition,
)

POOL = Path(__file__).resolve().parents[1] / "tests" / "integration" / "golden_pool" / "boltz2_results.csv"


def _pool_sequences() -> list[str]:
    with POOL.open(newline="") as fh:
        seqs = [r["sequence"].strip().upper() for r in csv.DictReader(fh) if r.get("sequence")]
    assert len(seqs) >= 6, f"golden pool shrank to {len(seqs)} sequences — re-measure before editing this test"
    return seqs


def test_the_gate_excludes_nothing():
    """Shadow mode: it may annotate, never drop."""
    df = pd.DataFrame({"sequence": _pool_sequences()})
    out = annotate_composition(df)
    assert len(out) == len(df), "annotate_composition dropped rows — it is advisory, it must not filter"
    assert "would_exclude_composition" in out.columns
    assert "composition_reason" in out.columns, "the verdict needs its reason, or a flag is unactionable"


def test_current_thresholds_would_reject_the_whole_validated_pool():
    """The measurement that forbids promotion. If a future calibration fixes the
    two offending thresholds this test SHOULD fail — update it with the new
    numbers rather than deleting it."""
    out = annotate_composition(pd.DataFrame({"sequence": _pool_sequences()}))
    flagged = int(out["would_exclude_composition"].sum())
    assert flagged == len(out), (
        f"{flagged}/{len(out)} real designs flagged — this pool measured 6/6 on 2026-09-27. "
        "If the thresholds were recalibrated, re-measure and update this test and the "
        "sequence_panel docstring together."
    )
    reasons = ",".join(out["composition_reason"].dropna())
    assert "hydrophobic" in reasons, "the hydrophobic floor was the dominant cause (5/6)"
    assert "glu_arg" in reasons, "the Glu+Arg ceiling was the second cause (4/6)"


@pytest.mark.parametrize(
    ("key", "extract", "comparison"),
    [
        ("max_ala_frac", lambda s: s.count("A") / len(s), "le"),
        ("max_pro_gly_frac", lambda s: (s.count("P") + s.count("G")) / len(s), "le"),
    ],
)
def test_the_thresholds_that_transfer_still_transfer(key, extract, comparison):
    """Ala and Pro+Gly were calibrated on RFD3 and hold on BindCraft 2 designs too.
    If one of these starts failing, the gate has stopped describing real designs at
    all and the whole panel needs recalibration, not a nudged constant."""
    limit = COMPOSITION_THRESHOLDS[key]
    worst = max(extract(s) for s in _pool_sequences())
    assert worst <= limit, f"{key}: real designs now reach {worst:.3f} against a limit of {limit}"


def test_hydrophobic_floor_is_still_above_the_real_pool_mean():
    """The specific, quantified reason the gate cannot be switched on."""
    seqs = _pool_sequences()
    mean_hydro = sum(sum(c in _HYDROPHOBIC for c in s) / len(s) for s in seqs) / len(seqs)
    floor = COMPOSITION_THRESHOLDS["min_hydrophobic_frac"]
    assert mean_hydro < floor, (
        f"hydrophobic floor {floor} is no longer above the real-pool mean {mean_hydro:.3f} — "
        "re-measure the 6/6 finding, it may no longer hold"
    )
