"""Tests for `binder-compare qc-annotate` — three-state QC verdicts (F36).

The bug these pin: a design the Rosetta interface panel never covered used to be
annotated ``qc_pass=False`` with ``qc_fail_reasons="interface_dG=NA;interface_sc=NA;…"``,
i.e. failed for *absence of evidence* rather than bad evidence — indistinguishable
from a design that genuinely blew a threshold, and hard-deleted by ``--drop-failures``.

After the fix ``qc_pass`` is three-state (True / False / NA), coverage is its own
``qc_covered`` column, and ``--drop-failures`` removes only measured failures.
"""

import argparse

import pytest

pd = pytest.importorskip("pandas")
from binder_comparison.cli.qc_annotate import DEFAULT_QC, _evaluate, _verdict, run  # noqa: E402

# A design that clears every BindCraft default (dG≤0, sc≥0.55, hbonds≥3, unsat≤4, nres≥7).
_GOOD = {
    "interface_dG": -28.0,
    "interface_sc": 0.71,
    "interface_interface_hbonds": 6,
    "interface_delta_unsat_hbonds": 2,
    "interface_nres": 18,
}
# Same, but the panel measured a positive ΔG and a poor shape complementarity.
_BAD = {**_GOOD, "interface_dG": 4.5, "interface_sc": 0.31}

_TH = {
    "dg_max": DEFAULT_QC["dg_max"],
    "sc_min": DEFAULT_QC["sc_min"],
    "hbonds_min": DEFAULT_QC["hbonds_min"],
    "unsat_max": DEFAULT_QC["unsat_max"],
    "nres_min": DEFAULT_QC["nres_min"],
}


def _state(v):
    """Normalise a CSV-round-tripped qc_pass cell to True / False / None."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    return v == "True" if isinstance(v, str) else bool(v)


# --------------------------------------------------------------------------
# _evaluate / _verdict: the three states
# --------------------------------------------------------------------------


def test_all_metrics_present_and_passing():
    failures, missing = _evaluate(_GOOD, _TH)
    assert failures == []
    assert missing == []
    assert _verdict(failures, missing) is True


def test_real_threshold_failure_is_false():
    failures, missing = _evaluate(_BAD, _TH)
    assert missing == []
    assert failures == ["dG>0.0", "sc<0.55"]
    assert _verdict(failures, missing) is False


def test_uncovered_design_is_na_not_false():
    """No panel row at all -> every metric NaN. Absence of evidence, not a failure."""
    row = dict.fromkeys(_GOOD, float("nan"))
    failures, missing = _evaluate(row, _TH)
    assert failures == []  # nothing was measured, so nothing can have failed
    assert missing == list(_GOOD)
    # THE bug: this verdict used to be False, identical to a genuine threshold failure.
    assert _verdict(failures, missing) is None


@pytest.mark.parametrize("blank", [None, float("nan"), ""])
def test_every_missing_representation_counts_as_uncovered(blank):
    failures, missing = _evaluate({**_GOOD, "interface_sc": blank}, _TH)
    assert failures == []
    assert missing == ["interface_sc"]
    assert _verdict(failures, missing) is None


def test_partial_coverage_with_a_measured_failure_is_a_failure():
    """A measured violation is real evidence even if other metrics are missing."""
    failures, missing = _evaluate({**_BAD, "interface_nres": None}, _TH)
    assert failures == ["dG>0.0", "sc<0.55"]
    assert missing == ["interface_nres"]
    assert _verdict(failures, missing) is False


# --------------------------------------------------------------------------
# run(): column contract + --drop-failures
# --------------------------------------------------------------------------


def _run(tmp_path, metrics, panel, drop_failures, tag=""):
    m_csv, p_csv = tmp_path / f"metrics{tag}.csv", tmp_path / f"panel{tag}.csv"
    out = tmp_path / f"annotated{tag}_{drop_failures}.csv"
    metrics.to_csv(m_csv, index=False)
    panel.to_csv(p_csv, index=False)
    run(
        argparse.Namespace(
            metrics=str(m_csv),
            panel=str(p_csv),
            structures_dir=None,
            run_rosetta=False,
            output=str(out),
            drop_failures=drop_failures,
            **_TH,
        )
    )
    return pd.read_csv(out).set_index("binder_id")


def _mixed(tmp_path, drop_failures):
    """good / bad / uncovered — 'uncovered' has no panel row at all (LEFT-join NaN)."""
    metrics = pd.DataFrame({"binder_id": ["good", "bad", "uncovered"], "consensus_iptm_mean": [0.9, 0.8, 0.7]})
    panel = pd.DataFrame([{"design_id": "good", **_GOOD}, {"design_id": "bad", **_BAD}])
    return _run(tmp_path, metrics, panel, drop_failures)


def test_run_annotates_three_distinct_states(tmp_path):
    df = _mixed(tmp_path, drop_failures=False)
    assert list(df.index) == ["good", "bad", "uncovered"]  # advisory: nothing dropped/reordered

    assert _state(df.loc["good", "qc_pass"]) is True
    assert bool(df.loc["good", "qc_covered"]) is True
    assert pd.isna(df.loc["good", "qc_fail_reasons"])

    assert _state(df.loc["bad", "qc_pass"]) is False
    assert bool(df.loc["bad", "qc_covered"]) is True
    assert df.loc["bad", "qc_fail_reasons"] == "dG>0.0;sc<0.55"

    # The uncovered design must be distinguishable from the genuine failure.
    assert _state(df.loc["uncovered", "qc_pass"]) is None
    assert bool(df.loc["uncovered", "qc_covered"]) is False
    # ...and its missing metrics are named, not smuggled into qc_fail_reasons.
    assert pd.isna(df.loc["uncovered", "qc_fail_reasons"])
    assert set(str(df.loc["uncovered", "qc_missing_metrics"]).split(";")) == set(_GOOD)


def test_drop_failures_drops_only_measured_failures(tmp_path):
    df = _mixed(tmp_path, drop_failures=True)
    # The measured failure goes; the uncovered design is NEVER silently deleted.
    assert list(df.index) == ["good", "uncovered"]
    assert _state(df.loc["uncovered", "qc_pass"]) is None


def test_drop_failures_keeps_a_wholly_uncovered_frame(tmp_path):
    """Panel covered nothing at all -> --drop-failures must not empty the shortlist."""
    metrics = pd.DataFrame({"binder_id": ["a", "b"], "consensus_iptm_mean": [0.9, 0.8]})
    panel = pd.DataFrame([{"design_id": "zzz", **_GOOD}])
    df = _run(tmp_path, metrics, panel, drop_failures=True, tag="_none")
    assert df.index.tolist() == ["a", "b"]
    assert df["qc_pass"].isna().all()
    assert not df["qc_covered"].astype(bool).any()


def test_qc_pass_true_semantics_unchanged(tmp_path):
    """Backward compat: qc_pass=True still means 'all five measured and cleared' —
    exactly what visualization/report.py::_qc_rules_html tells the report's reader."""
    df = _mixed(tmp_path, drop_failures=False)
    assert [i for i in df.index if _state(df.loc[i, "qc_pass"]) is True] == ["good"]
