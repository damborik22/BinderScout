"""The TmProt wrapper must not lose a design, and must hand `report` something it can join.

TmProt is an external CLI with two habits that quietly shorten a result set, and the
wrapper exists mostly to absorb them:

* It **sorts its output by Tm, descending**, and identifies rows by FASTA ID alone. A
  wrapper that zipped its rows back onto the input order would mislabel every design.
* It **silently skips** sequences it will not score — under 20 aa, over 2000, or carrying
  a non-standard residue. It warns on stderr and omits the row, so a naive reader gets a
  short CSV with no indication which designs are missing.

Either one produces a plausible, wrong column of melting temperatures rather than an
error, which is the failure mode this project keeps finding.

The real `tmprot` binary needs ESM-2 650M (~2.5 GB) and is far too heavy for a unit test,
so these drive a stub that reproduces upstream's exact output contract: the header
`Rank, ID, Predicted Tm [°C], Thermostable`, rows ordered by Tm descending, and the file
written to `<outdir>/<input stem>.csv`. The stub is a real executable invoked through the
real subprocess call, so the argument construction is exercised too.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest
from binder_comparison.refolding.tmprot_runner import run_tmprot_filter

# Long enough to clear TmProt's own 20 aa floor.
SEQ_A = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"
SEQ_B = "GSHMVDWLKAFYDKVAEKLKEAFPDTEIVFSHG"
SEQ_C = "ELTKAIDWLVRNGHEVNAIDQYGNTPLHLAAKY"

STUB = r"""#!/usr/bin/env python3
"""

STUB_BODY = r"""
import csv, sys
from pathlib import Path

args = sys.argv[1:]
def opt(flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default

inp = Path(opt("-i"))
outdir = Path(opt("-o"))
delim = opt("-d", "\t")

ids = []
for line in inp.read_text().splitlines():
    if line.startswith(">"):
        ids.append(line[1:].strip())

# Deterministic, distinct, and NOT in input order once sorted: TmProt sorts by Tm desc.
tms = {sid: 50.0 + 7.5 * (len(ids) - n) for n, sid in enumerate(ids)}
rows = sorted(tms.items(), key=lambda kv: kv[1], reverse=True)

outdir.mkdir(parents=True, exist_ok=True)
with (outdir / (inp.stem + ".csv")).open("w", newline="") as fh:
    w = csv.writer(fh, delimiter=delim)
    w.writerow(["Rank", "ID", "Predicted Tm [°C]", "Thermostable"])
    for rank, (sid, tm) in enumerate(rows, 1):
        w.writerow([rank, sid, tm, "Yes" if tm > 60.0 else "No"])
print(f"Saved to: {outdir / (inp.stem + '.csv')}")
"""


@pytest.fixture
def tmprot_stub(tmp_path, monkeypatch):
    """Put a fake `tmprot` on PATH that reproduces upstream's output contract."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "tmprot"
    stub.write_text(f"#!{sys.executable}\n{STUB_BODY}")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return stub


def _read(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestEveryInputSequenceComesBack:
    def test_rows_are_in_input_order_not_tmprot_rank_order(self, tmp_path, tmprot_stub):
        """The stub returns Tm descending, which is the reverse of the input order here."""
        out = tmp_path / "tm.csv"
        run_tmprot_filter([SEQ_A, SEQ_B, SEQ_C], out)
        rows = _read(out)
        assert [r["sequence"] for r in rows] == [SEQ_A, SEQ_B, SEQ_C], "rows were reordered by Tm"
        # Highest Tm went to the FIRST input sequence, so a zip-by-position bug inverts this.
        tms = [float(r["native_tmprot_tm"]) for r in rows]
        assert tms == sorted(tms, reverse=True)
        assert tms[0] > tms[-1]

    def test_a_sequence_tmprot_refuses_keeps_its_row_with_an_empty_tm(self, tmp_path, tmprot_stub):
        """Under 20 aa: upstream skips it. It must stay in the CSV, not vanish."""
        short = "MKTAYIAKQ"  # 9 aa
        out = tmp_path / "tm.csv"
        run_tmprot_filter([SEQ_A, short, SEQ_B], out)
        rows = _read(out)
        assert [r["sequence"] for r in rows] == [SEQ_A, short, SEQ_B]
        assert rows[1]["native_tmprot_tm"] == "", "a skipped sequence must have no Tm, not someone else's"
        assert rows[0]["native_tmprot_tm"] and rows[2]["native_tmprot_tm"]

    def test_binder_ids_are_carried_through_when_given(self, tmp_path, tmprot_stub):
        out = tmp_path / "tm.csv"
        run_tmprot_filter([SEQ_A, SEQ_B], out, binder_ids=["mosaic_d1", "rfd3_d2"])
        rows = _read(out)
        assert [r["binder_id"] for r in rows] == ["mosaic_d1", "rfd3_d2"]

    def test_a_design_header_with_spaces_does_not_break_the_join(self, tmp_path, tmprot_stub):
        """Biopython keeps only the first token of a FASTA ID, so headers cannot be the key."""
        out = tmp_path / "tm.csv"
        run_tmprot_filter([SEQ_A, SEQ_B], out, binder_ids=["d1 len=33 tool=mosaic", "d1 len=33 tool=rfd3"])
        rows = _read(out)
        assert all(r["native_tmprot_tm"] for r in rows), "ambiguous headers lost a Tm"
        assert float(rows[0]["native_tmprot_tm"]) != float(rows[1]["native_tmprot_tm"])


class TestItFailsLoudly:
    def test_a_missing_cli_is_an_error_naming_the_env(self, tmp_path):
        with pytest.raises(RuntimeError, match="binder-eval-tmprot"):
            run_tmprot_filter([SEQ_A], tmp_path / "tm.csv", tmprot_bin="tmprot-does-not-exist")

    def test_a_failing_tmprot_is_an_error_not_an_empty_screen(self, tmp_path, monkeypatch):
        """Silently writing nothing would read as "no design is thermostable"."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        bad = bindir / "tmprot"
        bad.write_text("#!/bin/sh\necho 'CUDA error' >&2\nexit 1\n")
        bad.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        with pytest.raises(RuntimeError, match="exit 1"):
            run_tmprot_filter([SEQ_A], tmp_path / "tm.csv")

    def test_no_sequences_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            run_tmprot_filter([], tmp_path / "tm.csv")


def test_the_csv_is_what_report_tmprot_results_ingests(tmp_path, tmprot_stub):
    """End to end against the real ingest: the column must be named and typed right.

    `_attach_tmprot_results` left-joins on `sequence` and renames the Tm column to
    `native_tmprot_tm`. If the wrapper's header drifts, the join silently attaches
    nothing and every design reports no Tm.
    """
    import pandas as pd
    from binder_comparison.cli.report import _attach_tmprot_results

    out = tmp_path / "tm.csv"
    run_tmprot_filter([SEQ_A, SEQ_B], out)

    df = pd.DataFrame({"sequence": [SEQ_A, SEQ_B], "rank": [1, 2]})
    merged = _attach_tmprot_results(df, str(out))

    assert "native_tmprot_tm" in merged.columns
    assert merged["native_tmprot_tm"].notna().all(), "report ingested the CSV but attached no Tm"
    assert pd.api.types.is_numeric_dtype(merged["native_tmprot_tm"])


def test_the_subcommand_is_registered_and_parses():
    """`filter-tmprot` has to be reachable from the real CLI, not just importable."""
    import argparse

    from binder_comparison.cli import filter_tmprot

    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command")
    filter_tmprot.add_parser(subs)
    args = parser.parse_args(["filter-tmprot", "-s", "in.fasta", "-o", "out.csv", "-t", "65"])
    assert args.threshold == 65.0
    assert args.func is filter_tmprot.run


def test_main_registers_it_alongside_filter_soluprot():
    """The sister screen is registered in main.py; this one must be too, or it is unreachable."""
    main_py = Path(__file__).resolve().parents[2] / "Evaluator" / "binder_comparison" / "main.py"
    text = main_py.read_text(encoding="utf-8")
    assert "filter_tmprot.add_parser(subparsers)" in text
    assert "filter-tmprot" in text, "the subcommand is missing from the CLI help listing"


def test_the_tm_column_is_found_under_upstream_exact_header():
    """The header carries a degree sign and brackets, so it is matched leniently.

    Upstream writes `Predicted Tm [°C]` verbatim (TmProt cli.py). Matching that exactly
    would break on a stray space or a case change; matching too loosely would grab
    `Thermostable`. Both failure modes end the same way — the Tm column is not found,
    the runner raises, and the screen produces nothing.
    """
    from binder_comparison.refolding.tmprot_runner import _tm_column

    assert _tm_column(["Rank", "ID", "Predicted Tm [°C]", "Thermostable"]) == "Predicted Tm [°C]"
    assert _tm_column(["Rank", "ID", "predicted tm [c]", "Thermostable"]) == "predicted tm [c]"
    assert _tm_column(["Rank", "ID", "Thermostable"]) is None, "must not mistake the Yes/No label for a Tm"
    assert _tm_column([]) is None
