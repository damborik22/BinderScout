"""A mixed-vintage designs.csv must not misalign into the wrong columns.

Mosaic appends to ``designs.csv`` across runs, and ``_read_mosaic_csv`` reads it
POSITIONALLY: it takes the header from line 1 and applies those names to every
row that follows (``names=padded_header, skiprows=1``). Its docstring states the
assumption that makes this safe -- "The named columns ... stay correct since
they're always in the same position."

That assumption holds only while new columns are appended at the END. A column
inserted in the MIDDLE shifts every field after it, and because the file's first
line is whichever header the run that created the file wrote, a single
``designs.csv`` containing both vintages silently reads the newer rows one
position out. ``sequence`` is four positions along, so the corruption lands
squarely on the one field the whole pipeline is built from -- and pandas does
not warn, because every row still parses.

This is not hypothetical: it is the documented "Mosaic CSV column mismatch"
failure mode, and adding ``generation_index`` for the discovery-rank metric
re-introduced it by inserting the column between ``rank`` and ``is_top``.

The guard is a property of the template, not of the reader: ``generation_index``
must be the LAST column, so a mixed file degrades to an unnamed trailing column
(older rows simply get NaN) instead of shifting the named ones.
"""

from __future__ import annotations

import re
from pathlib import Path

from binder_comparison.extractors.mosaic import _read_mosaic_csv

TEMPLATE = Path(__file__).resolve().parents[1] / "binderscout_examples" / "hallucinate_binderscout.py"

# The columns an older Mosaic run wrote, in order, before generation_index existed.
OLD_COLUMNS = ["worker_id", "rank", "is_top", "sequence", "target_sequence", "binder_length", "ranking_loss"]

SEQ_OLD = "MKTAYIAKQRQISFVK"
SEQ_NEW = "GGSGGSWELVKQRQIS"


def _template_columns() -> list[str]:
    """The csv_columns list the template writes, read from the source."""
    text = TEMPLATE.read_text()
    block = re.search(r"csv_columns = \[(.*?)\]", text, re.S)
    assert block, "csv_columns list not found in the Mosaic template"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_generation_index_is_the_last_column() -> None:
    """The structural guard. A middle insertion shifts every later field."""
    cols = _template_columns()
    assert "generation_index" in cols, "template no longer writes generation_index"
    assert cols[-1] == "generation_index", (
        f"generation_index must be the LAST column so appended files degrade safely; "
        f"it is at index {cols.index('generation_index')} of {len(cols)}, followed by "
        f"{cols[cols.index('generation_index') + 1 :]}"
    )


def test_mixed_vintage_file_keeps_sequence_intact(tmp_path: Path) -> None:
    """The consequence, end to end.

    An older run created the file and wrote its header; a newer run appended a
    row carrying the extra column. Reading must still return each row's real
    sequence.
    """
    cols = _template_columns()
    new_row = {c: "" for c in cols}
    new_row.update(
        {
            "worker_id": "1",
            "rank": "1",
            "is_top": "1",
            "sequence": SEQ_NEW,
            "target_sequence": "TARGET",
            "binder_length": "16",
            "ranking_loss": "0.25",
            "generation_index": "7",
        }
    )

    csv_path = tmp_path / "designs.csv"
    with csv_path.open("w") as fh:
        fh.write(",".join(OLD_COLUMNS) + "\n")
        fh.write(",".join(["0", "1", "1", SEQ_OLD, "TARGET", "16", "0.30"]) + "\n")
        fh.write(",".join(new_row[c] for c in cols) + "\n")

    df = _read_mosaic_csv(csv_path)

    assert df.loc[0, "sequence"] == SEQ_OLD
    assert df.loc[1, "sequence"] == SEQ_NEW, (
        f"newer row's sequence read as {df.loc[1, 'sequence']!r} -- the row is shifted, "
        "so a mid-list column was added to the template"
    )
    # is_top drives the default extraction filter; a shifted row silently changes
    # which designs are in the pool at all.
    assert str(df.loc[1, "is_top"]) in ("1", "1.0", "True")
