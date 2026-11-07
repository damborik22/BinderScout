"""`binder-compare report` with a second-slot engine: AF3 (default) or Protenix.

End to end through the real report CLI on the deterministic synthetic pool. The Protenix pool
is the AF3 pool re-slotted: same ipTM values, same PAE content, but written the way the shared
second-engine driver writes them (``[binder|target]``, not AF3's target-first token order), so
a report that read the Protenix PAE with the wrong ordering produces different numbers and the
equality tests below fail.

Column names, panel strings and sentences are pinned as literals on purpose: a test that
derived them from the registry would pass whatever the registry said.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

pytest.importorskip("pandas")
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "Evaluator"))
sys.path.insert(0, str(_ROOT / "tests" / "integration"))

import synthetic_pool  # noqa: E402
from binder_comparison.cli import report as report_cli  # noqa: E402

# The columns metrics.csv carried for the AF3 default before the panel was recorded.
_AF3_METRICS_COLUMNS = [
    "run_id", "sequence", "target_sequence", "binder_length", "boltz_iptm", "ipsae_min_aux",
    "boltz_plddt_binder_mean", "boltz_pae_max", "boltz_pae_file", "af3_iptm", "af3_ipsae_min",
    "af3_plddt_binder_mean", "af3_pae_max", "af3_pae_file", "esmfold2_iptm", "esmfold2_ipsae_min",
    "esmfold2_plddt_binder_mean", "esmfold2_pae_max", "esmfold2_pae_file", "binder_id", "source_tool",
    "native_length", "native_mw", "native_pi", "native_extinction_280", "native_gravy",
    "native_aromatic_fraction", "comp_ala_frac", "comp_pro_gly_frac", "comp_glu_arg_frac",
    "comp_hydrophobic_frac", "comp_entropy", "comp_has_gggg", "would_exclude_composition", "composition_reason",
    "confidence_n_engines", "passes_confidence_gate", "confidence_fail_reasons", "confidence_missing",
    "would_exclude_confidence", "self_consistency_rmsd", "passes_self_consistency",
    "would_exclude_self_consistency", "seq_family_id", "seq_family_size", "seq_family_is_redundant",
    "seq_family_tools", "struct_family_id", "struct_family_size", "struct_family_is_redundant", "iptm", "ipae",
    "pae_bt", "pae_tb", "pae_bb", "plddt_binder_mean", "plddt_binder_min", "plddt_target_mean",
    "boltz_pae_bt_ipsae", "boltz_pae_tb_ipsae", "boltz_pae_ipsae_min", "boltz_pae_ipsae_max", "boltz_pae_iptm",
    "boltz_pae_iptm_pinned", "af3_bt_ipsae", "af3_tb_ipsae", "af3_ipsae_max", "af3_pae_iptm",
    "af3_pae_iptm_pinned", "esmfold2_bt_ipsae", "esmfold2_tb_ipsae", "esmfold2_ipsae_max", "esmfold2_pae_iptm",
    "esmfold2_pae_iptm_pinned", "consensus_iptm_mean_pinned", "ipsae_min", "iptm_z", "ipae_z", "pae_bt_z",
    "pae_tb_z", "pae_bb_z", "plddt_binder_mean_z", "plddt_binder_min_z", "plddt_target_mean_z", "ipsae_min_aux_z",
    "boltz_pae_bt_ipsae_z", "boltz_pae_tb_ipsae_z", "boltz_pae_ipsae_min_z", "af3_iptm_z",
    "af3_plddt_binder_mean_z", "af3_bt_ipsae_z", "af3_tb_ipsae_z", "af3_ipsae_min_z", "af3_pae_iptm_z",
    "esmfold2_iptm_z", "esmfold2_plddt_binder_mean_z", "esmfold2_bt_ipsae_z", "esmfold2_tb_ipsae_z",
    "esmfold2_ipsae_min_z", "esmfold2_pae_iptm_z", "boltz_pae_iptm_z", "passes_boltz_filter", "passes_af3_filter",
    "passes_esmfold2_filter", "passes_ipsae_filter", "passes_ipsae_strict", "quality_tier", "agreement_count",
    "agreement_denom", "consensus_iptm", "consensus_iptm_mean", "consensus_iptm_min", "consensus_iptm_n",
    "consensus_iptm_spread", "consensus_ipsae_min_mean", "consensus_ipsae_min_n", "consensus_ipsae_min_spread",
    "passes_engine_gate", "rank", "wetlab_recommended", "wetlab_reason", "design_group", "is_representative",
    "family_id", "family_size", "family_rank",
]  # fmt: skip


def _reslot_to_protenix(pool: dict[str, Path], root: Path) -> Path:
    """The AF3 CSV + PAE files of *pool*, rewritten as a Protenix refold (binder-first PAE)."""
    pdir = root / "protenix"
    (pdir / "pae").mkdir(parents=True)
    rows = list(csv.DictReader(pool["af3"].open()))
    for row in rows:
        af3_pae = np.load(row["pae_file"])  # target-first
        nb, nt = int(row["binder_length"]), len(synthetic_pool.TARGET)
        binder_first = np.block([[af3_pae[nt:, nt:], af3_pae[nt:, :nt]], [af3_pae[:nt, nt:], af3_pae[:nt, :nt]]])
        assert binder_first.shape == (nb + nt, nb + nt)
        out = pdir / "pae" / Path(row["pae_file"]).name
        np.save(out, binder_first)
        row["pae_file"] = str(out)
    path = pdir / "protenix_results.csv"
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


def _run(out: Path, argv: list[str]) -> pd.DataFrame:
    parser = argparse.ArgumentParser()
    report_cli.add_parser(parser.add_subparsers(dest="command"))
    report_cli.run(parser.parse_args(["report", *argv, "--output", str(out)]))
    return pd.read_csv(out / "metrics.csv")


def _base(pool: dict[str, Path]) -> list[str]:
    return ["--boltz2-results", str(pool["boltz2"]), "--esmfold2-results", str(pool["esmfold2"]),
            "--sequences", str(pool["sequences"])]  # fmt: skip


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("second_engine")
    pool = synthetic_pool.build(root / "pool")
    prot_csv = _reslot_to_protenix(pool, root)
    af3_df = _run(root / "rep_af3", [*_base(pool), "--af3-results", str(pool["af3"])])
    prot_df = _run(root / "rep_prot", [*_base(pool), "--second-engine", "protenix", "--second-results", str(prot_csv)])
    return {"root": root, "pool": pool, "prot_csv": prot_csv, "af3": af3_df, "prot": prot_df}


def _html(runs, which: str) -> str:
    return (runs["root"] / f"rep_{which}" / "report.html").read_text()


class TestProtenixSlot:
    def test_metrics_carry_protenix_columns_and_no_af3_ones(self, runs):
        cols = list(runs["prot"].columns)
        assert "protenix_pae_iptm" in cols
        assert "protenix_ipsae_min" in cols
        assert "passes_protenix_filter" in cols
        assert not [c for c in cols if c.startswith("af3_") or "_af3_" in c], "an af3 column leaked into the report"
        assert "passes_af3_filter" not in cols

    def test_panel_and_second_engine_are_recorded_on_every_row(self, runs):
        df = runs["prot"]
        assert set(df["panel"]) == {"boltz+protenix+esmfold2"}
        assert set(df["second_engine"]) == {"protenix"}

    def test_binder_first_pae_is_read_in_binder_first_order(self, runs):
        """Same complex, same numbers: the Protenix PAE is [binder|target]; reading it as AF3's
        target-first layout would change every value below."""
        af3, prot = runs["af3"].set_index("binder_id"), runs["prot"].set_index("binder_id")
        got = prot.loc[af3.index, "protenix_pae_iptm"].astype(float).to_numpy()
        want = af3["af3_pae_iptm"].astype(float).to_numpy()
        assert np.isfinite(got).sum() == 9  # d07 has no second-engine row
        np.testing.assert_allclose(got, want, rtol=0, atol=1e-6, equal_nan=True)
        got = prot.loc[af3.index, "protenix_ipsae_min"].astype(float).to_numpy()
        want = af3["af3_ipsae_min"].astype(float).to_numpy()
        np.testing.assert_allclose(got, want, rtol=0, atol=1e-6, equal_nan=True)

    def test_rank_order_equals_the_af3_run(self, runs):
        af3, prot = runs["af3"], runs["prot"]
        assert list(af3.sort_values("rank")["binder_id"]) == list(prot.sort_values("rank")["binder_id"])
        np.testing.assert_allclose(af3["consensus_iptm_mean"], prot["consensus_iptm_mean"], atol=1e-6)
        assert list(af3["consensus_iptm_n"]) == list(prot["consensus_iptm_n"])

    def test_html_states_the_panel_and_that_af3_was_not_used(self, runs):
        html = _html(runs, "prot")
        assert "Boltz-2 + Protenix + ESMFold2; AF3 not used" in html
        assert "not on one scale" in html

    def test_html_names_no_af3_outside_the_panel_line(self, runs):
        html = _html(runs, "prot").replace("Boltz-2 + Protenix + ESMFold2; AF3 not used", "")
        # base64 images and the viewer scripts are not prose; look at the visible text only.
        import re

        text = re.sub(r"data:image/png;base64,[A-Za-z0-9+/=]+", "", html)
        text = re.sub(r"<script.*?</script>", "", text, flags=re.S)
        leftovers = [m.group(0) for m in re.finditer(r".{30}(?:AF3|AlphaFold).{30}", text, flags=re.S)]
        assert not leftovers, leftovers

    def test_primary_engine_may_be_the_slot_engine(self, runs, tmp_path, capsys):
        df = _run(
            tmp_path / "rep",
            [*_base(runs["pool"]), "--second-engine", "protenix", "--second-results", str(runs["prot_csv"]),
             "--primary-engine", "protenix"],
        )  # fmt: skip
        assert "Using protenix_ipsae_min as primary ipsae_min" in capsys.readouterr().out
        assert set(df["panel"]) == {"boltz+protenix+esmfold2"}

    def test_threshold_protenix_changes_the_pass_flag(self, runs, tmp_path):
        loose = _run(
            tmp_path / "loose",
            [*_base(runs["pool"]), "--second-engine", "protenix", "--second-results", str(runs["prot_csv"]),
             "--threshold-protenix", "0.0"],
        )  # fmt: skip
        assert loose["passes_protenix_filter"].sum() == 9
        assert runs["prot"]["passes_protenix_filter"].sum() < 9


class TestAf3DefaultIsUnchanged:
    def test_metrics_columns_are_the_old_ones_plus_the_two_new_last(self, runs):
        assert list(runs["af3"].columns) == [*_AF3_METRICS_COLUMNS, "panel", "second_engine"]

    def test_panel_columns_for_af3(self, runs):
        assert set(runs["af3"]["panel"]) == {"boltz+af3+esmfold2"}
        assert set(runs["af3"]["second_engine"]) == {"af3"}

    def test_html_prints_the_panel_without_the_not_used_clause(self, runs):
        html = _html(runs, "af3")
        assert "Boltz-2 + AF3 + ESMFold2" in html
        assert "AF3 not used" not in html
        assert "not on one scale" in html

    def test_second_results_with_the_default_engine_fills_the_af3_slot(self, runs, tmp_path):
        df = _run(tmp_path / "rep", [*_base(runs["pool"]), "--second-results", str(runs["pool"]["af3"])])
        assert list(df.columns) == list(runs["af3"].columns)
        assert list(df.sort_values("rank")["binder_id"]) == list(runs["af3"].sort_values("rank")["binder_id"])


class TestThresholdOfTheOtherEngine:
    def test_threshold_protenix_with_the_af3_slot_is_noticed_and_ignored(self, runs, tmp_path, capsys):
        df = _run(
            tmp_path / "rep",
            [*_base(runs["pool"]), "--af3-results", str(runs["pool"]["af3"]), "--threshold-protenix", "0.5"],
        )  # fmt: skip
        err = capsys.readouterr().err
        assert "--threshold-protenix" in err and "--second-engine is af3" in err and "ignored" in err
        assert list(df["rank"]) == list(runs["af3"]["rank"])

    def test_the_default_af3_run_prints_no_such_notice(self, runs, tmp_path, capsys):
        _run(tmp_path / "rep", [*_base(runs["pool"]), "--af3-results", str(runs["pool"]["af3"])])
        assert "--threshold-protenix" not in capsys.readouterr().err


class TestWrongSlotRefusals:
    def test_af3_results_with_the_protenix_slot_is_noticed_and_ignored(self, runs, tmp_path, capsys):
        df = _run(
            tmp_path / "rep",
            [*_base(runs["pool"]), "--af3-results", str(runs["pool"]["af3"]), "--second-engine", "protenix",
             "--second-results", str(runs["prot_csv"])],
        )  # fmt: skip
        err = capsys.readouterr().err
        assert "--af3-results" in err and "protenix" in err and "ignored" in err
        assert not [c for c in df.columns if c.startswith("af3_")]
        assert set(df["panel"]) == {"boltz+protenix+esmfold2"}

    def test_af3_results_alone_with_the_protenix_slot_leaves_a_two_engine_panel(self, runs, tmp_path, capsys):
        df = _run(
            tmp_path / "rep",
            [*_base(runs["pool"]), "--af3-results", str(runs["pool"]["af3"]), "--second-engine", "protenix"],
        )  # fmt: skip
        assert "--af3-results" in capsys.readouterr().err
        assert not [c for c in df.columns if c.startswith("af3_")]
        assert not [c for c in df.columns if c.startswith("protenix_")]
        assert set(df["consensus_iptm_n"]) <= {1, 2}

    def test_primary_engine_af3_is_refused_when_the_slot_is_protenix(self, runs, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(
                tmp_path / "rep",
                [*_base(runs["pool"]), "--second-engine", "protenix", "--second-results", str(runs["prot_csv"]),
                 "--primary-engine", "af3"],
            )  # fmt: skip
        assert exc.value.code not in (0, None)
        err = capsys.readouterr().err
        assert "af3" in err and "protenix" in err and "primary" in err

    def test_primary_engine_protenix_is_refused_when_the_slot_is_af3(self, runs, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(
                tmp_path / "rep",
                [*_base(runs["pool"]), "--af3-results", str(runs["pool"]["af3"]), "--primary-engine", "protenix"],
            )  # fmt: skip
        assert exc.value.code not in (0, None)
        assert "protenix" in capsys.readouterr().err

    def test_af3_results_together_with_second_results_names_both(self, runs, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(
                tmp_path / "rep",
                [*_base(runs["pool"]), "--af3-results", str(runs["pool"]["af3"]),
                 "--second-results", str(runs["pool"]["af3"])],
            )  # fmt: skip
        assert exc.value.code not in (0, None)
        err = capsys.readouterr().err
        assert "--af3-results" in err and "--second-results" in err

    def test_unknown_second_engine_is_an_argparse_error(self, runs, tmp_path):
        with pytest.raises(SystemExit):
            _run(tmp_path / "rep", [*_base(runs["pool"]), "--second-engine", "chai1"])


class TestSlotColumnsOfTheOtherEngineAreIgnored:
    """A frame carrying both engines' columns must not feed the other one into plots or tables."""

    def test_bar_chart_uses_only_the_panel(self, runs):
        from binder_comparison.core.engines import resolve_panel
        from binder_comparison.visualization.plots import plot_per_tool_engine_iptm

        df = runs["prot"].copy()
        df["af3_pae_iptm"] = 0.5  # a stray AF3 column
        fig = plot_per_tool_engine_iptm(df, panel=resolve_panel("protenix"))
        labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
        assert labels == ["Boltz-2", "Protenix", "ESMFold2"]

    def test_radar_panels_are_the_panels_engines(self, runs):
        from binder_comparison.core.engines import resolve_panel
        from binder_comparison.visualization.plots import plot_radar_per_engine

        df = runs["prot"].copy()
        df["af3_ipsae_min"] = 0.9
        df["af3_iptm"] = 0.9
        fig = plot_radar_per_engine(df, top_n=10, panel=resolve_panel("protenix"))
        titles = [ax.get_title() for ax in fig.axes]
        assert not any("AF3" in t for t in titles), titles

    def test_slim_table_engine_count_follows_the_panel(self, runs):
        from binder_comparison.core.engines import resolve_panel
        from binder_comparison.visualization.top30_slim import _n_engines

        df = runs["prot"].copy()
        df["af3_ipsae_min"] = 0.9
        assert _n_engines(df, resolve_panel("protenix")) == 3
        assert _n_engines(df.drop(columns=["protenix_ipsae_min"]), resolve_panel("protenix")) == 2


class TestHitsWorkbookNamesThePanel:
    """The workbook leaves the pipeline: its engines line must come from the recorded panel."""

    def _workbook_text(self, cand: Path, tmp_path, **extra) -> str:
        openpyxl = pytest.importorskip("openpyxl")
        from binder_comparison.cli import hits

        ns = argparse.Namespace(
            candidates=[f"T={cand}"], per_tool=2, refolded=2, extra=None, meta=None, version="1.0", date="",
            csv=False, output=str(tmp_path / "hits.xlsx"), **{"second_engine": None, **extra},
        )  # fmt: skip
        hits.run(ns)
        wb = openpyxl.load_workbook(tmp_path / "hits.xlsx")
        return "\n".join(str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None)

    def test_a_protenix_pool_is_named_without_passing_the_flag(self, runs, tmp_path):
        text = self._workbook_text(runs["root"] / "rep_prot" / "candidates.csv", tmp_path)
        assert "Boltz-2, Protenix, ESMFold2 (AF3 not used)" in text
        assert "AlphaFold3" not in text

    def test_the_explicit_flag_overrides_the_recorded_panel(self, runs, tmp_path):
        text = self._workbook_text(runs["root"] / "rep_prot" / "candidates.csv", tmp_path, second_engine="af3")
        assert "Re-folding: Boltz-2, AlphaFold3, ESMFold2" in text
        assert "Protenix" not in text

    def test_a_disagreeing_explicit_flag_warns_and_wins(self, runs, tmp_path, capsys):
        self._workbook_text(runs["root"] / "rep_prot" / "candidates.csv", tmp_path, second_engine="af3")
        err = capsys.readouterr().err
        assert "--second-engine af3" in err and "second_engine=protenix" in err and "explicit flag wins" in err

    def test_an_agreeing_explicit_flag_is_silent(self, runs, tmp_path, capsys):
        self._workbook_text(runs["root"] / "rep_prot" / "candidates.csv", tmp_path, second_engine="protenix")
        assert "disagrees" not in capsys.readouterr().err

    def test_an_af3_pool_is_named_from_its_recorded_panel(self, runs, tmp_path):
        text = self._workbook_text(runs["root"] / "rep_af3" / "candidates.csv", tmp_path)
        assert "Re-folding: Boltz-2, AlphaFold3, ESMFold2" in text
        assert "Protenix" not in text

    def test_a_pool_with_no_metrics_csv_is_unchanged(self, runs, tmp_path):
        lone = tmp_path / "lone"
        lone.mkdir()
        (lone / "candidates.csv").write_bytes((runs["root"] / "rep_prot" / "candidates.csv").read_bytes())
        text = self._workbook_text(lone / "candidates.csv", tmp_path)
        assert "Re-folding: Boltz-2, AlphaFold3, ESMFold2" in text
        assert "Protenix" not in text

    def test_a_metrics_csv_from_before_the_panel_was_recorded_is_unchanged(self, runs, tmp_path):
        old = tmp_path / "old"
        old.mkdir()
        (old / "candidates.csv").write_bytes((runs["root"] / "rep_prot" / "candidates.csv").read_bytes())
        pd.read_csv(runs["root"] / "rep_prot" / "metrics.csv").drop(columns=["panel", "second_engine"]).to_csv(
            old / "metrics.csv", index=False
        )
        text = self._workbook_text(old / "candidates.csv", tmp_path)
        assert "Re-folding: Boltz-2, AlphaFold3, ESMFold2" in text

    def test_candidates_csv_itself_is_not_changed_by_the_panel(self, runs):
        header = (runs["root"] / "rep_af3" / "candidates.csv").read_text().splitlines()[0]
        assert "panel" not in header and "second_engine" not in header


class TestAf3RankOrderIsPinnedToTheCodeBeforeThePanel:
    """The literal order the AF3 run produced, taken from the pre-change code.

    Obtained by extracting commit 44816b6 (the tree before `binder-compare report` read a panel)
    with ``git archive`` into an empty directory, running this same synthetic pool through that
    tree's ``report`` and reading ``rank`` off its metrics.csv. Not derived from this tree.
    """

    PRE_CHANGE_ORDER: ClassVar[list[tuple[str, int]]] = [
        ("d01_mpnn1|bindcraft", 1),
        ("d05|rfd3", 2),
        ("d02|mosaic", 3),
        ("d08|rfd3", 4),
        ("d04_c1|protein_hunter", 5),
        ("d01_mpnn2|bindcraft", 6),
        ("d03|boltzgen", 7),
        ("d04_c2|protein_hunter", 8),
        ("d07|mosaic", 9),
        ("d06|pxdesign", 10),
    ]

    def test_af3_run_ranks_exactly_as_before(self, runs):
        df = runs["af3"].sort_values("rank")
        assert list(zip(df["binder_id"], df["rank"].astype(int), strict=True)) == self.PRE_CHANGE_ORDER

    def test_the_protenix_reslot_ranks_the_same(self, runs):
        df = runs["prot"].sort_values("rank")
        assert list(zip(df["binder_id"], df["rank"].astype(int), strict=True)) == self.PRE_CHANGE_ORDER


class TestPrimaryEngineStructureColumns:
    def test_esmfold2_keeps_its_old_fallback_to_the_boltz_structure(self):
        from binder_comparison.visualization.report import _pri_cols

        assert _pri_cols("esmfold2") == ["boltz_pdb", "pdb"]
        assert _pri_cols("af3") == ["af3_pdb", "af3_cif", "boltz_pdb", "pdb"]
        assert _pri_cols("protenix") == ["protenix_pdb", "protenix_cif", "boltz_pdb", "pdb"]
