"""The table a human picks designs from must show whether the gate was cleared.

`top30_slim.csv` is what someone opens in Excel to choose what to order, and
`top30_slim.html` is the matching on-page table. Both showed a design's
`consensus_iptm_mean` with no indication that the mean might come from ONE
engine — and that the design was therefore ranked last for a reason that has
nothing to do with its quality.

`agreement_count` is present but is NOT that signal: Part U retired it as a
ranking input (macro-AUC 0.532, 87.2% of designs tied at zero).

The synthetic pool is used deliberately: it contains a 1-engine and a 2-engine
design, so the column can be shown to carry signal rather than merely exist.
The real golden pool is all-3-engine and would pass a weaker version of this
test without proving anything.
"""

from __future__ import annotations

import argparse

import pandas as pd
import pytest
import synthetic_pool
from binder_comparison.cli import report as report_cli


@pytest.fixture(scope="module")
def slim(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("slim")
    pool = synthetic_pool.build(tmp / "pool")
    out = tmp / "rep"
    parser = argparse.ArgumentParser()
    report_cli.add_parser(parser.add_subparsers(dest="command"))
    report_cli.run(
        parser.parse_args(
            [
                "report",
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
        )
    )
    return pd.read_csv(out / "top30_slim.csv")


def test_the_pick_table_has_a_gate_column(slim):
    assert "Gate" in slim.columns, (
        "top30_slim.csv has no gate signal — a picker cannot tell a 3-engine mean "
        f"from a 1-engine one. Columns: {list(slim.columns)}"
    )


def test_the_gate_column_actually_discriminates(slim):
    """Present but constant would be worse than absent: it would look informative."""
    vals = set(slim["Gate"].astype(str))
    assert len(vals) > 1, f"Gate is constant ({vals}) — the fixture no longer exercises the gate"


def test_a_gate_failure_can_outscore_a_passer_on_the_visible_metric(slim):
    """The exact trap the column exists to close: a design with a HIGHER mean
    ipTM sitting below one with a lower mean, because it had one engine."""
    failed = slim[slim["Gate"].astype(str).str.lower().isin(("false", "0"))]
    passed = slim[slim["Gate"].astype(str).str.lower().isin(("true", "1"))]
    assert not failed.empty and not passed.empty
    assert failed["Mean ipTM"].max() > passed["Mean ipTM"].min(), (
        "fixture no longer demonstrates the trap; the column's rationale is unproven"
    )
