"""A retried design must reach the report with the score, not with the blank it replaced.

THE FAILURE
-----------
AF3 and ESMFold2 open their result CSV in APPEND mode and, when one design fails, write
a row with ``sequence`` filled in and every score blank.  ``--resume`` (which the
generated ``run_evaluate.sh`` always passes) keys "completed" on a non-empty ``iptm``, so
the retry correctly re-folds that design and APPENDS a second row for the same sequence.

``_load_engine`` then collapsed the pair with ``drop_duplicates("sequence",
keep="first")`` -- keeping the BLANK row written first and discarding the scored row the
resume existed to produce.  ``consensus_iptm_n`` counts non-NaN engine iptm, so the
design still showed one engine short, failed the ``>=3``-engine gate and was ranked last,
while ``evaluate.sh`` saw the appended row and printed "ok -- 1 new row(s)".  The
documented recovery path silently reproduced the demotion 2.0 set out to eliminate.

Boltz-2 is unaffected -- it omits the row instead of blanking it.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.merger import merge_refold_results  # noqa: E402

_HEADER = "run_id,idx,sequence,target_sequence,binder_length,iptm,ptm\n"
_SEQ = "AAAWWWAAA"
_TARGET = "TTTTTT"


def _boltz2(tmp_path):
    path = tmp_path / "boltz2.csv"
    path.write_text(_HEADER + f"b_0001,1,{_SEQ},{_TARGET},9,0.72,0.70\n")
    return path


def _af3_blank_then_scored(tmp_path):
    """What AF3 leaves on disk after a per-design OOM followed by `--resume`."""
    path = tmp_path / "af3.csv"
    path.write_text(
        _HEADER
        + f"af3_0001,1,{_SEQ},{_TARGET},9,,\n"  # the failure's blank row, written first
        + f"af3_0001,1,{_SEQ},{_TARGET},9,0.88,0.86\n"  # the retry's score, appended after
    )
    return path


def test_the_retried_score_survives_the_merge(tmp_path):
    merged = merge_refold_results(boltz2_csv=_boltz2(tmp_path), af3_csv=_af3_blank_then_scored(tmp_path))
    assert len(merged) == 1, "the blank and the retry are the same design, so they must collapse to one row"
    assert merged.iloc[0]["af3_iptm"] == pytest.approx(0.88), (
        "the merge kept the blank row the failure wrote and dropped the score --resume produced"
    )


def test_a_blank_with_no_retry_is_still_reported_blank(tmp_path):
    """Preferring the scored row must not invent a score where the retry never happened."""
    path = tmp_path / "af3.csv"
    path.write_text(_HEADER + f"af3_0001,1,{_SEQ},{_TARGET},9,,\n")
    merged = merge_refold_results(boltz2_csv=_boltz2(tmp_path), af3_csv=path)
    assert len(merged) == 1
    assert pd.isna(merged.iloc[0]["af3_iptm"])


def test_file_order_is_kept_among_scored_duplicates(tmp_path):
    """Two scored rows for one sequence is the plain append case: keep the first."""
    path = tmp_path / "af3.csv"
    path.write_text(
        _HEADER + f"af3_0001,1,{_SEQ},{_TARGET},9,0.40,0.41\n" + f"af3_0001,1,{_SEQ},{_TARGET},9,0.90,0.91\n"
    )
    with pytest.warns(UserWarning, match="duplicate row"):
        merged = merge_refold_results(boltz2_csv=_boltz2(tmp_path), af3_csv=path)
    assert merged.iloc[0]["af3_iptm"] == pytest.approx(0.40)


def test_an_engine_csv_without_an_iptm_column_still_merges(tmp_path):
    """`read_csv_safe` can hand back a frame with no `iptm` at all; the sort must not KeyError."""
    path = tmp_path / "af3.csv"
    path.write_text("run_id,idx,sequence,target_sequence,binder_length\n" + f"af3_0001,1,{_SEQ},{_TARGET},9\n")
    merged = merge_refold_results(boltz2_csv=_boltz2(tmp_path), af3_csv=path)
    assert len(merged) == 1
