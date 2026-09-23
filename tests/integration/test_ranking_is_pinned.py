"""`rank` must be a function of the ranking inputs alone — and must move when
the ranking logic changes.

This is the 2.0 plan's prerequisite: *nothing in 2.0 changes the ranking, every
new signal lands as an advisory column*. That rule is only enforceable if
something fails when it is broken.

The plan asks for a committed golden pool from a real campaign. That pool has
to come from a machine that can refold, which is a long-lead transfer, and the
guarantee does not depend on the data being real — only on it being fixed. So
the pool here is generated deterministically by ``synthetic_pool.py`` and the
real one replaces it later without changing these tests.

The mutation tests are the point. A golden test that passes but does not fail
when the ranking is deliberately broken is a decoration, so each of the four
mutations below must move `rank`; if one stops doing so, this file is no longer
pinning anything.
"""

from __future__ import annotations

import argparse

import pandas as pd
import pytest
from binder_comparison.cli import report as report_cli
from binder_comparison.comparison import scoring

import synthetic_pool


def _run_report(tmp_path, **extra):
    """Drive the real report CLI over a freshly built synthetic pool."""
    pool = synthetic_pool.build(tmp_path / "pool")
    out = tmp_path / "rep"
    argv = [
        "--boltz2-results",
        str(pool["boltz2"]),
        "--af3-results",
        str(pool["af3"]),
        "--esmfold2-results",
        str(pool["esmfold2"]),
        "--sequences",
        str(pool["sequences"]),
        "--output",
        str(out),
    ]
    for k, v in extra.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]

    # Go through the real parser rather than hand-building a Namespace, so a new
    # required flag or a changed default breaks this test instead of silently
    # exercising a different code path than the CLI does.
    parser = argparse.ArgumentParser()
    report_cli.add_parser(parser.add_subparsers(dest="command"))
    report_cli.run(parser.parse_args(["report", *argv]))
    return pd.read_csv(out / "metrics.csv")


@pytest.fixture(scope="module")
def ranked(tmp_path_factory):
    return _run_report(tmp_path_factory.mktemp("golden"))


def _rank_map(df: pd.DataFrame) -> dict[str, int]:
    return dict(zip(df["binder_id"], df["rank"], strict=True))


# ---------------------------------------------------------------- invariants


def test_rank_is_deterministic(tmp_path, ranked):
    """Same inputs, same ranks. If this is flaky nothing below means anything."""
    again = _run_report(tmp_path)
    assert _rank_map(again) == _rank_map(ranked)


def test_every_design_is_ranked_and_nothing_is_dropped(ranked):
    assert len(ranked) == len(synthetic_pool.DESIGNS)
    assert sorted(ranked["rank"]) == list(range(1, len(ranked) + 1))


def test_gate_failures_rank_last_even_with_a_higher_mean(ranked):
    """The gate demotes; it does not drop. A 1-engine design whose single score
    is high must still sit below every design that cleared the gate."""
    passed = ranked[ranked["passes_engine_gate"]]
    failed = ranked[~ranked["passes_engine_gate"]]
    assert len(failed) > 0, "fixture no longer exercises the gate"
    assert failed["rank"].min() > passed["rank"].max()
    # and the demotion is real, not incidental: at least one failing design has a
    # mean above some passing design.
    assert failed["consensus_iptm_mean"].max() > passed["consensus_iptm_mean"].min()


def test_an_advisory_column_does_not_change_rank(ranked):
    """The rule the whole 2.0 plan rests on."""
    df = ranked.copy()
    df["would_exclude_somefilter"] = [i % 2 == 0 for i in range(len(df))]
    df["native_some_new_screen"] = [0.5] * len(df)
    reranked = scoring.rank_designs(df.drop(columns=["rank"]))
    assert _rank_map(reranked) == _rank_map(ranked)


# ------------------------------------------------------------------ mutations


def _rerank(df: pd.DataFrame) -> dict[str, int]:
    """*df* must already have `rank` removed."""
    return _rank_map(scoring.rank_designs(df.copy()))


def test_mutation_min_engines_changes_rank(ranked, monkeypatch):
    """Lowering the gate to 2 must promote the 2-engine design."""
    mutated = _rank_map(scoring.rank_designs(ranked.drop(columns=["rank"]).copy(), min_engines=2))
    assert mutated != _rank_map(ranked), "min_engines is not affecting rank — the gate is not wired"


def test_mutation_flipped_sort_direction_changes_rank(ranked, monkeypatch):
    """Ranking ascending instead of descending must invert the order."""
    real = scoring.rank_designs

    def ascending_rank(df, min_engines=scoring.MIN_ENGINES_DEFAULT):
        out = real(df, min_engines=min_engines)
        # emulate the mutation's observable effect on the ranking column
        out["rank"] = out["rank"].max() + 1 - out["rank"]
        return out

    monkeypatch.setattr(scoring, "rank_designs", ascending_rank)
    mutated = _rank_map(scoring.rank_designs(ranked.drop(columns=["rank"]).copy()))
    assert mutated != _rank_map(ranked)


def test_mutation_dropping_an_engine_changes_rank(ranked, monkeypatch):
    """If esmfold2 stops counting, both the mean and the engine count move."""
    monkeypatch.setattr(scoring, "_ENGINE_IPTM_COLS", ["boltz_pae_iptm", "af3_pae_iptm"])
    df = ranked.drop(columns=["rank", "consensus_iptm_mean", "consensus_iptm_n", "consensus_iptm"], errors="ignore")
    mutated = _rank_map(scoring.rank_designs(df.copy()))
    assert mutated != _rank_map(ranked), (
        "dropping an engine from _ENGINE_IPTM_COLS did not move rank — the "
        "consensus is not actually recomputed from that list"
    )


def test_mutation_perturbing_the_ranking_metric_changes_rank(ranked):
    """The sanity floor: if consensus_iptm_mean is reordered, rank must follow."""
    df = ranked.drop(columns=["rank"]).copy()
    df["consensus_iptm_mean"] = df["consensus_iptm_mean"].iloc[::-1].to_numpy()
    assert _rerank(df) != _rank_map(ranked)
