"""TmProt screen: parse the tool's real output and map it back to sequences.

TmProt (Loschmidt Lab, github.com/loschmidt/TmProt) is a LoRA-adapted ESM-2
melting-temperature predictor — the sister tool to SoluProt from the same group.
It writes ``Rank, ID, Predicted Tm [°C], Thermostable``, keyed by the FASTA
header, while ``report.py::_attach_tmprot_results`` joins on ``sequence``. The
remapping in between is the part that can silently go wrong, so it is what
these tests pin.

It is a SCREEN, not a filter: it never drops a design. Item D1 of the 2.0
assessment is explicit — "proceed as a screen, never a ranking term", because Tm
predictors are out of domain on hyperstable de novo miniproteins.
"""

import csv

import pytest
from binder_comparison.refolding.tmprot_runner import (
    DEFAULT_THRESHOLD,
    _parse_tmprot_output,
    _write_csv,
    make_fasta_ids,
)

SEQS = ["MKWVTFISLLLL", "AEQKLISEEDLN", "GSHMSDKIIHLT"]


def _tmprot_csv(tmp_path, rows):
    """A CSV in TmProt's own output format."""
    p = tmp_path / "predictions.csv"
    with p.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Rank", "ID", "Predicted Tm [°C]", "Thermostable"])
        w.writerows(rows)
    return p


def test_fasta_ids_are_positional_and_unique():
    """We control the FASTA IDs, so the mapping back is positional and cannot
    be confused by duplicate or exotic binder names."""
    ids = make_fasta_ids(SEQS)
    assert len(set(ids)) == len(SEQS)
    assert ids == make_fasta_ids(SEQS), "ID generation must be deterministic"


def test_parses_tm_and_maps_back_by_id(tmp_path):
    ids = make_fasta_ids(SEQS)
    # TmProt sorts by rank, NOT by input order — that is the trap.
    csv_path = _tmprot_csv(
        tmp_path,
        [
            [1, ids[2], 78.5, "Yes"],
            [2, ids[0], 61.0, "Yes"],
            [3, ids[1], 44.25, "No"],
        ],
    )
    tms = _parse_tmprot_output(csv_path, ids)
    assert tms == [61.0, 44.25, 78.5], "results were not mapped back to input order"


def test_missing_prediction_becomes_none_not_zero(tmp_path):
    """A dropped sequence must not read as a 0 °C melting temperature."""
    ids = make_fasta_ids(SEQS)
    csv_path = _tmprot_csv(tmp_path, [[1, ids[0], 61.0, "Yes"], [2, ids[2], 70.0, "Yes"]])
    tms = _parse_tmprot_output(csv_path, ids)
    assert tms == [61.0, None, 70.0]


def test_unparseable_tm_becomes_none(tmp_path):
    ids = make_fasta_ids(SEQS)
    csv_path = _tmprot_csv(tmp_path, [[1, ids[0], "n/a", "No"], [2, ids[1], 55.0, "No"], [3, ids[2], "", "No"]])
    assert _parse_tmprot_output(csv_path, ids) == [None, 55.0, None]


def test_output_csv_matches_what_report_expects(tmp_path):
    """report.py finds the Tm column by name and joins on `sequence`."""
    out = tmp_path / "tmprot_results.csv"
    _write_csv(out, sequences=SEQS, tms=[61.0, None, 78.5], threshold=60.0, binder_ids=None)
    rows = list(csv.DictReader(out.open()))

    assert list(rows[0].keys()) == ["sequence", "tmprot_tm", "tmprot_thermostable", "tmprot_threshold"]
    # 'tmprot_tm' is one of the spellings report.py::_attach_tmprot_results accepts.
    assert len(rows) == len(SEQS), "a screen must emit a row for every sequence"
    assert rows[0]["tmprot_tm"] == "61.000000"
    assert rows[1]["tmprot_tm"] == "", "missing Tm must be blank, never 0"
    assert rows[0]["tmprot_thermostable"] == "1"
    assert rows[1]["tmprot_thermostable"] == ""


def test_binder_ids_ride_through_when_given(tmp_path):
    out = tmp_path / "t.csv"
    _write_csv(out, sequences=SEQS, tms=[61.0, 50.0, 78.5], threshold=60.0, binder_ids=["a", "b", "c"])
    rows = list(csv.DictReader(out.open()))
    assert next(iter(rows[0].keys())) == "binder_id"
    assert [r["binder_id"] for r in rows] == ["a", "b", "c"]


@pytest.mark.parametrize(("tm", "expected"), [(60.0, "1"), (59.999, "0"), (None, "")])
def test_thermostable_flag_uses_the_threshold(tmp_path, tm, expected):
    out = tmp_path / "t.csv"
    _write_csv(out, sequences=["AAAA"], tms=[tm], threshold=DEFAULT_THRESHOLD, binder_ids=None)
    assert next(iter(csv.DictReader(out.open())))["tmprot_thermostable"] == expected


def test_default_threshold_is_the_papers_thermostable_cutoff():
    """TmProt's reported AUC 0.75-0.77 is for identifying Tm >= 60 C."""
    assert DEFAULT_THRESHOLD == 60.0


def test_missing_tmprot_binary_explains_itself(tmp_path):
    """Running from the wrong env is the common case; a bare FileNotFoundError
    traceback tells a human nothing about which binary or how to get it."""
    from binder_comparison.refolding.tmprot_runner import run_tmprot_screen

    with pytest.raises(RuntimeError) as exc:
        run_tmprot_screen(SEQS, tmp_path / "o.csv", tmprot_bin="definitely-not-a-real-binary")
    msg = str(exc.value)
    assert "not found" in msg
    assert "--tool tmprot" in msg, "the error must say how to install it"
    assert "binder-eval-tmprot" in msg, "the error must name the env"
