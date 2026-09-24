"""Tests for the Part N affinity ranking: pure |dG/dSASA| density, gated by ipsae_min.

ipsae_min is a binder GATE, not a ranking multiplier — it carries no affinity signal among
binders on the Adaptyv benchmark, so multiplying it in only adds variance.
"""

import math

import pytest
from binder_comparison.comparison.affinity import interface_energy_density

pd = pytest.importorskip("pandas")
from binder_comparison.comparison.affinity import DEFAULT_AFFINITY_GATE, add_affinity_ranking  # noqa: E402


def test_density_value():
    # |−30 / 1000| = 0.03 — NO ipsae_min factor.
    assert interface_energy_density(-30.0, 1000.0) == pytest.approx(0.03)


def test_more_favorable_dg_scores_higher():
    strong = interface_energy_density(-50.0, 1000.0)
    weak = interface_energy_density(-10.0, 1000.0)
    assert strong > weak


def test_density_independent_of_ipsae():
    """The score must not depend on ipsae_min — that's the whole point of the change."""
    df = pd.DataFrame(
        {
            "ipsae_min": [0.9, 0.3],  # very different confidence
            "interface_dG": [-30.0, -30.0],
            "interface_dSASA": [1000.0, 1000.0],
        }
    )
    out = add_affinity_ranking(df)
    assert out["affinity_energy_density"].tolist() == pytest.approx([0.03, 0.03])


def test_zero_dsasa_is_nan():
    assert math.isnan(interface_energy_density(-30.0, 0.0))


def test_missing_input_is_nan():
    assert math.isnan(interface_energy_density(None, 1000.0))
    assert math.isnan(interface_energy_density(-30.0, None))


def test_gate_flags_binders_above_threshold():
    df = pd.DataFrame(
        {
            "ipsae_min": [0.80, 0.61, 0.40, float("nan")],
            "interface_dG": [-30.0, -30.0, -30.0, -30.0],
            "interface_dSASA": [1000.0, 1000.0, 1000.0, 1000.0],
        }
    )
    out = add_affinity_ranking(df, gate_threshold=DEFAULT_AFFINITY_GATE)
    # >= 0.61 passes; 0.40 fails; NaN fails (can't confirm a binder).
    assert out["passes_affinity_gate"].tolist() == [True, True, False, False]


def test_gate_then_density_ordering():
    """A weak-but-gated-in binder outranks a strong-density design that fails the gate."""
    df = pd.DataFrame(
        {
            "id": ["gated_weak", "ungated_strong"],
            "ipsae_min": [0.70, 0.30],
            "interface_dG": [-10.0, -90.0],  # ungated has the stronger density
            "interface_dSASA": [1000.0, 1000.0],
        }
    )
    out = add_affinity_ranking(df)
    out = out.sort_values(["passes_affinity_gate", "affinity_energy_density"], ascending=[False, False])
    assert out["id"].tolist() == ["gated_weak", "ungated_strong"]


def test_cli_module_imports_with_renamed_symbols():
    """The affinity CLI must import cleanly after the gate-then-density rename."""
    from binder_comparison.cli import affinity as cli_affinity

    assert callable(cli_affinity.run)
    assert callable(cli_affinity.add_parser)


def test_df_helper_coerces_strings():
    df = pd.DataFrame(
        {
            "ipsae_min": ["0.8", "0.5"],
            "interface_dG": ["-30.0", "-10.0"],
            "interface_dSASA": ["1000.0", "500.0"],
        }
    )
    out = add_affinity_ranking(df)
    assert out["affinity_energy_density"].tolist() == pytest.approx([0.03, 0.02])


def test_df_helper_noop_density_without_energy_columns():
    df = pd.DataFrame({"ipsae_min": [0.8]})  # no energy columns
    out = add_affinity_ranking(df)
    assert "affinity_energy_density" not in out.columns
    # but the gate is still computed from ipsae_min
    assert out["passes_affinity_gate"].tolist() == [True]


def test_df_helper_gate_all_true_without_ipsae():
    df = pd.DataFrame({"interface_dG": [-30.0], "interface_dSASA": [1000.0]})
    out = add_affinity_ranking(df)
    assert out["passes_affinity_gate"].tolist() == [True]  # can't gate → don't drop


def test_df_helper_nan_on_zero_dsasa():
    df = pd.DataFrame({"ipsae_min": [0.8], "interface_dG": [-30.0], "interface_dSASA": [0.0]})
    out = add_affinity_ranking(df)
    assert math.isnan(out["affinity_energy_density"].iloc[0])


class TestEnergyJoinActuallyMatches:
    """Same silent keying bug as qc-annotate (see test_qc_annotate.py).

    ``interface_energy.py`` keys its rows by the structure filename stem, and the
    structures the pipeline points at are the report's export,
    ``rank{NN}_{binder_id}.pdb``. ``affinity.py`` left-joined that against
    ``binder_id``, so every design got NaN energy and the whole Part N ranking
    quietly degraded to the ipsae gate alone.
    """

    def _energy(self, design_ids):
        return pd.DataFrame([{"design_id": d, "interface_dG": -30.0, "interface_dSASA": 1000.0} for d in design_ids])

    def _metrics(self, binder_ids):
        return pd.DataFrame([{"binder_id": b, "ipsae_min": 0.8} for b in binder_ids])

    def _run(self, tmp_path, metrics, energy, tag):
        import argparse

        from binder_comparison.cli import affinity as cli_affinity

        m, e = tmp_path / f"m{tag}.csv", tmp_path / f"e{tag}.csv"
        out = tmp_path / f"o{tag}.csv"
        metrics.to_csv(m, index=False)
        energy.to_csv(e, index=False)
        cli_affinity.run(
            argparse.Namespace(
                metrics=str(m),
                energy=str(e),
                structures_dir=None,
                run_rosetta=False,
                output=str(out),
                ipsae_col="ipsae_min",
                gate_threshold=DEFAULT_AFFINITY_GATE,
                interface="B_A",
                bindcraft_env="BindCraft",
            )
        )
        return pd.read_csv(out)

    def test_rank_prefixed_energy_ids_join(self, tmp_path):
        ids = ["bindcraft2_CALCA_b_l99_4796f2fbca3e328c_seq3", "rfd3_helix_binder_2_model_0"]
        out = self._run(
            tmp_path,
            self._metrics(ids),
            self._energy([f"rank{i + 1:02d}_{b}" for i, b in enumerate(ids)]),
            "_rank",
        )
        assert out["interface_dG"].notna().all(), (
            "rank-prefixed energy ids did not join — affinity silently falls back to the gate alone"
        )
        assert out["affinity_energy_density"].notna().all()

    def test_energy_matching_nothing_is_an_error(self, tmp_path):
        with pytest.raises(SystemExit):
            self._run(
                tmp_path,
                self._metrics(["design_alpha"]),
                self._energy(["af3_0007"]),
                "_none",
            )
