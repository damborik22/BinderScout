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
    """Panel covered nothing at all -> --drop-failures must not empty the shortlist.

    The panel here JOINS to both designs but produced no metric values — the
    Rosetta panel ran and could not score them. That is the real
    absence-of-evidence case, and it must be kept.

    It used to be written with a panel keyed ``zzz``, i.e. matching neither
    design. That shape now errors, because a panel that matches NOTHING is a
    keying bug rather than a measurement outcome — which is exactly how the
    metrics/panel id mismatch stayed invisible. The distinction is the point:
    joined-but-NaN is uncovered; never-joined is broken.
    """
    metrics = pd.DataFrame({"binder_id": ["a", "b"], "consensus_iptm_mean": [0.9, 0.8]})
    panel = pd.DataFrame([{"design_id": d, **{k: None for k in _GOOD}} for d in ("a", "b")])
    df = _run(tmp_path, metrics, panel, drop_failures=True, tag="_none")
    assert df.index.tolist() == ["a", "b"]
    assert df["qc_pass"].isna().all()
    assert not df["qc_covered"].astype(bool).any()


def test_qc_pass_true_semantics_unchanged(tmp_path):
    """Backward compat: qc_pass=True still means 'all five measured and cleared' —
    exactly what visualization/report.py::_qc_rules_html tells the report's reader."""
    df = _mixed(tmp_path, drop_failures=False)
    assert [i for i in df.index if _state(df.loc[i, "qc_pass"]) is True] == ["good"]


class TestPanelJoinActuallyMatches:
    """The panel and the metrics table were keyed in different namespaces, so the
    join silently matched nothing.

    ``interface_qc.py:71`` writes ``design_id = pdb.stem``. The structures it is
    pointed at in the real pipeline are the report's export, named
    ``rank{NN}_{binder_id}.pdb`` (``report.py:533``, fed in by
    ``evaluate.sh:700``). So design_id is binder_id with a ``rank01_`` prefix, and
    the left join produced NaN for every row.

    Worse, the NaN was indistinguishable from the legitimate case this command
    exists to model -- a structure the panel genuinely could not score -- so a
    100% join failure reported itself as "N NOT covered by the panel" and exited
    0. The Rosetta panel has therefore never attached a single row.
    """

    def _panel(self, design_ids):
        return pd.DataFrame(
            [
                {
                    "design_id": d,
                    "interface_dG": -12.0,
                    "interface_sc": 0.70,
                    "interface_interface_hbonds": 5,
                    "interface_delta_unsat_hbonds": 2,
                    "interface_nres": 12,
                }
                for d in design_ids
            ]
        )

    def _metrics(self, binder_ids):
        return pd.DataFrame([{"binder_id": b, "rank": i + 1} for i, b in enumerate(binder_ids)])

    def test_rank_prefixed_panel_ids_join(self, tmp_path):
        """The real pipeline's shape: panel keyed rank01_<binder_id>."""
        ids = ["bindcraft2_CALCA_b_l99_4796f2fbca3e328c_seq3", "rfd3_helix_binder_2_model_0"]
        out = _run(
            tmp_path,
            self._metrics(ids),
            self._panel([f"rank{i + 1:02d}_{b}" for i, b in enumerate(ids)]),
            drop_failures=False,
            tag="_rankpfx",
        )
        assert out["qc_covered"].all(), (
            "the rank-prefixed panel did not join -- every row is NA, which is exactly the silent failure this pins"
        )
        assert (out["qc_pass"] == True).all()  # noqa: E712

    def test_exact_ids_still_join(self, tmp_path):
        """A panel already keyed by binder_id must keep working."""
        ids = ["design_alpha", "design_beta"]
        out = _run(tmp_path, self._metrics(ids), self._panel(ids), drop_failures=False, tag="_exact")
        assert out["qc_covered"].all()

    def test_a_panel_matching_nothing_is_an_error_not_absence_of_evidence(self, tmp_path):
        """A non-empty panel that joins to ZERO rows is a keying bug, not a
        measurement outcome, and must not exit 0 pretending otherwise."""
        with pytest.raises(SystemExit):
            _run(
                tmp_path,
                self._metrics(["design_alpha", "design_beta"]),
                self._panel(["af3_0007", "af3_0011"]),  # refold filenames — a different namespace
                drop_failures=False,
                tag="_nomatch",
            )
