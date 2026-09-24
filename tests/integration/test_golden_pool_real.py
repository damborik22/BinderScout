"""The ranking, pinned against a REAL archived campaign.

`test_ranking_is_pinned.py` proves the ranking *moves when it should*, using a
synthetic pool so the mutation tests need no committed data. This file is the
other half: it proves the ranking *does not move when it should not*, against
six designs from a real CALCA / BindCraft 2 campaign — real refold CSVs from all
three engines, with their real PAE matrices.

Why both, and the split is not decorative:

* Synthetic data cannot catch a **schema drift** — the real CSVs carry 36, 19
  and 20 columns against the synthetic pool's 9, and the real binder_ids carry
  the ``_seqN`` grammar the grouping code reads.
* This fixture cannot exercise the **cross-engine gate**. All six designs were
  refolded by all three engines, so lowering ``MIN_ENGINES_DEFAULT`` from 3 to 2
  changes nothing here — verified, that mutation leaves these tests green. The
  synthetic pool carries a deliberate 2-engine and 1-engine design for exactly
  that reason, and is where gate demotion is pinned.

So neither fixture is redundant, and neither is sufficient. A real pool that
also happened to contain a 1-engine design would collapse the two, but this one
does not and manufacturing one would make the "golden" order no longer the
order the campaign actually produced.

The fixture was built by ``make_golden_pool.py``, which relativises every
recorded path (they are absolute and carry a username from the machine that
produced them) and quantises PAE to float16 at 0.25 Å.
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import pandas as pd
import pytest
from binder_comparison.cli import report as report_cli
from binder_comparison.comparison import scoring

POOL = Path(__file__).resolve().parent / "golden_pool"

# The ranking this pool produces. Any change here is either a real regression or
# a deliberate decision that must be argued for in the commit that makes it.
EXPECTED_ORDER = [
    "bindcraft2_CALCA_b_l99_4796f2fbca3e328c_seq3",
    "bindcraft2_CALCA_b_l105_fed84892013ae24e_seq2",
    "bindcraft2_CALCA_b_l106_16b88894c8774162_seq6",
    "bindcraft2_CALCA_b_l101_c793daeb143ffd01_seq6",
    "bindcraft2_CALCA_b_l107_e24d9703a87e09eb_seq3",
    "bindcraft2_CALCA_b_l103_038cd6f0f8b3268c_seq7",
]


def _report(tmp_path):
    out = tmp_path / "rep"
    parser = argparse.ArgumentParser()
    report_cli.add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        [
            "report",
            "--boltz2-results",
            str(POOL / "boltz2_results.csv"),
            "--af3-results",
            str(POOL / "af3_results.csv"),
            "--esmfold2-results",
            str(POOL / "esmfold2_results.csv"),
            "--sequences",
            str(POOL / "sequences.fasta"),
            "--output",
            str(out),
        ]
    )
    report_cli.run(args)
    return pd.read_csv(out / "metrics.csv")


@pytest.fixture(scope="module")
def ranked(tmp_path_factory):
    return _report(tmp_path_factory.mktemp("golden_real"))


def test_the_fixture_is_present_and_portable():
    """It must carry no absolute path: those break on any other machine and
    would put a username from the producing host into a public repo."""
    assert POOL.is_dir(), "golden_pool fixture missing"
    for csv_path in POOL.glob("*_results.csv"):
        text = csv_path.read_text()
        assert "/home/" not in text, f"{csv_path.name} still holds an absolute path"


def test_rank_matches_the_golden_order(ranked):
    assert ranked.sort_values("rank")["binder_id"].tolist() == EXPECTED_ORDER


def test_every_design_is_three_engine(ranked):
    """If PAE resolution regresses, consensus_iptm_n collapses and the gate
    fails everything — which is what a transplanted pool used to do."""
    assert (ranked["consensus_iptm_n"] == 3).all()
    assert ranked["passes_engine_gate"].all()


def test_pae_derived_columns_are_populated(ranked):
    """The columns the cross-engine gate actually counts."""
    for col in ("boltz_pae_iptm", "af3_pae_iptm", "esmfold2_pae_iptm"):
        assert col in ranked.columns, f"{col} missing — PAE was not read"
        assert ranked[col].notna().all(), f"{col} has nulls — some PAE did not resolve"


def test_real_pae_files_resolve_without_warning(tmp_path):
    """A transplanted pool warns about unresolved PAE. The fixture must not."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _report(tmp_path)
    unresolved = [w for w in caught if "pae" in str(w.message).lower() and "not found" in str(w.message).lower()]
    assert not unresolved, [str(w.message) for w in unresolved]


def test_advisory_columns_do_not_move_the_real_ranking(ranked):
    """The 2.0 rule, checked against real data rather than synthetic."""
    df = ranked.copy()
    df["would_exclude_somefilter"] = [i % 2 == 0 for i in range(len(df))]
    df["native_some_screen"] = 0.5
    reranked = scoring.rank_designs(df.drop(columns=["rank"]))
    assert reranked.sort_values("rank")["binder_id"].tolist() == EXPECTED_ORDER


def test_the_real_schema_is_wider_than_the_synthetic_one(ranked):
    """Guards the reason this fixture exists: synthetic data cannot catch a
    schema drift, because it never had the columns to drift."""
    assert len(ranked.columns) > 100, f"only {len(ranked.columns)} columns — is the real pool still wired up?"
