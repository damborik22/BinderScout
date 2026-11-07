"""The engine registry: one place that names the three refold engines of a panel."""

from __future__ import annotations

import dataclasses

import pytest
from binder_comparison.core.engines import SECOND_ENGINES, Engine, Panel, engine, resolve_panel


def test_default_panel_reproduces_todays_engine_iptm_columns():
    assert resolve_panel().iptm_cols == ["boltz_pae_iptm", "af3_pae_iptm", "esmfold2_pae_iptm"]
    assert resolve_panel("af3").iptm_cols == resolve_panel().iptm_cols


def test_default_panel_reproduces_todays_ipsae_columns_and_thresholds():
    panel = resolve_panel()
    assert panel.ipsae_cols == ["boltz_pae_ipsae_min", "af3_ipsae_min", "esmfold2_ipsae_min"]
    assert [e.default_threshold for e in panel.engines] == [0.61, 0.61, 0.61]


def test_protenix_panel_swaps_only_the_second_slot():
    panel = resolve_panel("protenix")
    assert panel.iptm_cols == ["boltz_pae_iptm", "protenix_pae_iptm", "esmfold2_pae_iptm"]
    assert panel.ipsae_cols == ["boltz_pae_ipsae_min", "protenix_ipsae_min", "esmfold2_ipsae_min"]
    assert panel.label == "Boltz-2 + Protenix + ESMFold2"
    assert panel.slug == "boltz+protenix+esmfold2"


def test_default_panel_label_and_slug():
    panel = resolve_panel()
    assert panel.label == "Boltz-2 + AF3 + ESMFold2"
    assert panel.slug == "boltz+af3+esmfold2"


def test_af3_row_reproduces_todays_literals():
    af3 = engine("af3")
    assert (af3.prefix, af3.refold_dir, af3.results_csv) == ("af3", "refold_af3", "af3_results.csv")
    assert (af3.iptm_col, af3.ipsae_col) == ("af3_pae_iptm", "af3_ipsae_min")
    assert af3.pdb_cols == ("af3_pdb", "af3_cif")
    assert (af3.binder_chain, af3.default_threshold) == ("B", 0.61)


def test_boltz_and_esmfold2_rows_reproduce_todays_literals():
    boltz, esm = engine("boltz"), engine("esmfold2")
    assert boltz.prefix == "boltz"
    assert esm.prefix == "esmfold2"
    assert (boltz.refold_dir, boltz.results_csv) == ("refold_boltz2", "boltz2_results.csv")
    assert boltz.ipsae_col == "boltz_pae_ipsae_min"  # not the af3-style "<prefix>_ipsae_min"
    assert boltz.pdb_cols == ("boltz_pdb", "boltz_cif")
    assert boltz.binder_chain == "A"
    assert (esm.refold_dir, esm.results_csv) == ("refold_esmfold2", "esmfold2_results.csv")
    assert (esm.iptm_col, esm.ipsae_col) == ("esmfold2_pae_iptm", "esmfold2_ipsae_min")
    assert esm.pdb_cols == ("esmfold2_pdb", "esmfold2_cif")
    assert esm.binder_chain == "B"


def test_protenix_row():
    p = engine("protenix")
    assert (p.name, p.display, p.prefix) == ("protenix", "Protenix", "protenix")
    assert (p.refold_dir, p.results_csv) == ("refold_protenix", "protenix_results.csv")
    assert (p.iptm_col, p.ipsae_col) == ("protenix_pae_iptm", "protenix_ipsae_min")
    assert p.pdb_cols == ("protenix_pdb", "protenix_cif")
    assert (p.binder_chain, p.default_threshold) == ("B", 0.61)


def test_second_engines_are_af3_and_protenix():
    assert SECOND_ENGINES == ("af3", "protenix")


@pytest.mark.parametrize("bad", ["boltz", "esmfold2", "", "openfold3", "AF3"])
def test_unknown_second_engine_names_the_valid_values(bad):
    with pytest.raises(ValueError) as exc:
        resolve_panel(bad)
    msg = str(exc.value)
    assert "af3" in msg and "protenix" in msg
    assert repr(bad) in msg


def test_unknown_engine_lookup_raises():
    with pytest.raises(ValueError):
        engine("nope")


@pytest.mark.parametrize("second", SECOND_ENGINES)
def test_a_panel_is_exactly_three_distinct_engines(second):
    panel = resolve_panel(second)
    assert len(panel.engines) == 3
    assert len({e.prefix for e in panel.engines}) == 3
    assert len({e.name for e in panel.engines}) == 3
    assert [e.name for e in panel.engines] == ["boltz", second, "esmfold2"]
    assert len(panel.iptm_cols) == len(panel.ipsae_cols) == 3


def test_engine_and_panel_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        engine("af3").prefix = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolve_panel().second = engine("protenix")  # type: ignore[misc]


def test_panel_has_no_fourth_slot():
    assert [f.name for f in dataclasses.fields(Panel)] == ["boltz", "second", "esmfold2"]
    assert isinstance(resolve_panel().second, Engine)


def test_default_panel_agrees_with_the_scoring_module_literals():
    from binder_comparison.comparison import scoring

    panel = resolve_panel()
    assert panel.iptm_cols == scoring._ENGINE_IPTM_COLS
    assert dict(zip(("boltz", "af3", "esmfold2"), panel.ipsae_cols, strict=True)) == scoring._ENGINE_IPSAE_COLS
    assert tuple(e.refold_dir for e in panel.engines) == scoring._ENGINE_OUTPUT_DIRS
    assert all(e.default_threshold == scoring.IPSAE_PASS_THRESHOLD for e in panel.engines)


def test_default_panel_structure_columns_are_covered_by_the_scoring_and_report_tables():
    from binder_comparison.comparison import scoring

    for e in resolve_panel().engines:
        assert set(e.pdb_cols) <= set(scoring._STRUCTURE_PATH_COLUMNS), e.name
    assert scoring._STRUCTURE_PATH_COLUMNS[-1] == "pdb"

    # cli/report imports the whole report stack; if that does not import here, only this half is skipped.
    report = pytest.importorskip("binder_comparison.cli.report")
    for e in resolve_panel().engines:
        cols, chain = report._ENGINE_STRUCT_COLS[e.name]
        assert tuple(cols) == e.pdb_cols, e.name
        assert chain == e.binder_chain, e.name
