"""The PXDesign collector must read the ranked CSV that actually exists.

The collector's "preferred" Strategy 1 globs ``filtered_summary.csv``, but
PXDesign's own ``cleanup_outputs()`` unlinks that file during the run, before
our collector ever executes. So Strategy 1 has never once matched: every
BinderScout PXDesign run silently falls through to ``sample_level_output.csv``,
which carries no ``rank`` column, and ships ``pxdesign_rank`` empty.

``summary.csv`` holds the same rows and survives, because it is written two
levels below the directory ``cleanup_outputs`` empties. Two things make reading
it more than a filename swap:

* ``trim_summary_df`` RENAMES the AF2 metrics on the way in (``i_pTM`` ->
  ``af2_iptm``, ``pLDDT`` -> ``af2_plddt``, ``unscaled_i_pAE`` -> ``af2_ipAE``).
  Swapping only the glob would recover ``rank`` and blank three metrics --
  the same silent-emptiness bug, moved.
* It has no per-design ``name``, so the existing fallback would give every row
  the id ``pxdesign_summary``.

These tests run the GENERATED snippet through bash, so the heredoc's quoting and
brace-doubling are exercised rather than assumed.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))

from configurator import _pxdesign_sequence_collector

SEQ_A = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"
SEQ_B = "GGSGGSWELVKQRQISFVKSHFSRQLEERLGLI"

# summary.csv as trim_summary_df leaves it: rank first, task_name, sequence,
# and the RENAMED AF2 columns. No 'name', no 'bucket'.
SUMMARY_COLUMNS = ["rank", "task_name", "sequence", "af2_iptm", "af2_plddt", "af2_ipAE", "ptx_iptm"]

# sample_level_output.csv keeps the ORIGINAL spellings, and has no rank.
SAMPLE_COLUMNS = ["name", "seq_idx", "sequence", "i_pTM", "pLDDT", "unscaled_i_pAE"]


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def _run_collector(run_dir: Path) -> list[dict]:
    """Execute the generated shell snippet and return the sequences.csv rows."""
    snippet = _pxdesign_sequence_collector(str(run_dir))
    proc = subprocess.run(["bash", "-c", snippet], capture_output=True, text=True)
    out_csv = run_dir / "pxdesign" / "sequences.csv"
    if not out_csv.exists():
        raise AssertionError(f"collector wrote no sequences.csv\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    with out_csv.open() as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A PXDesign tree as it looks AFTER cleanup_outputs has run: summary.csv
    present, filtered_summary.csv already deleted, sample CSV alongside."""
    task = tmp_path / "pxdesign" / "outputs_len80" / "design_outputs" / "input_len80"
    _write_csv(
        task / "summary.csv",
        SUMMARY_COLUMNS,
        [
            {
                "rank": "1",
                "task_name": "input_len80",
                "sequence": SEQ_A,
                "af2_iptm": "[0.88]",
                "af2_plddt": "[0.91]",
                "af2_ipAE": "[6.2]",
                "ptx_iptm": "0.83",
            },
            {
                "rank": "2",
                "task_name": "input_len80",
                "sequence": SEQ_B,
                "af2_iptm": "[0.71]",
                "af2_plddt": "[0.85]",
                "af2_ipAE": "[8.4]",
                "ptx_iptm": "0.66",
            },
        ],
    )
    # The decoy the collector takes today.
    _write_csv(
        task / "seed_0" / "sample_level_output.csv",
        SAMPLE_COLUMNS,
        [{"name": "s_0", "seq_idx": "0", "sequence": SEQ_A, "i_pTM": "0.88", "pLDDT": "0.91", "unscaled_i_pAE": "6.2"}],
    )
    return tmp_path


def test_reads_summary_csv_and_recovers_rank(run_dir: Path) -> None:
    rows = _run_collector(run_dir)

    assert len(rows) == 2, f"expected both summary.csv designs, got {len(rows)}"
    assert [r["pxdesign_rank"] for r in rows] == ["1", "2"], (
        "pxdesign_rank is empty -- the collector still ignores summary.csv"
    )
    # Row order IS the reported native rank downstream, so it must be rank order.
    assert [r["sequence"] for r in rows] == [SEQ_A, SEQ_B]


def test_maps_the_renamed_af2_columns(run_dir: Path) -> None:
    """The trap in the obvious fix: trim_summary_df renamed these, so reading
    the old spellings would recover rank and blank three metrics instead."""
    rows = _run_collector(run_dir)

    assert rows[0]["af2_iptm"] == "0.88", "af2_iptm blank -- reading 'i_pTM' instead of 'af2_iptm'"
    assert rows[0]["af2_plddt"] == "0.91", "af2_plddt blank -- reading 'pLDDT' instead of 'af2_plddt'"
    assert rows[0]["af2_ipae"] == "6.2", "af2_ipae blank -- reading 'unscaled_i_pAE' instead of 'af2_ipAE'"
    assert rows[0]["ptx_iptm"] == "0.83", "ptx_iptm is NOT renamed and must still work"


def test_design_ids_are_unique(run_dir: Path) -> None:
    """summary.csv has no 'name', so the old fallback would give every row the
    id 'pxdesign_summary' and collide the whole pool into one design."""
    rows = _run_collector(run_dir)
    ids = [r["design_id"] for r in rows]

    assert len(set(ids)) == len(ids), f"design_id collision: {ids}"
    # Same shape PXDesignExtractor._make_id builds from task_name + rank, so the
    # collector path and a direct read of summary.csv agree on identity.
    assert ids == ["pxdesign_input_len80_1", "pxdesign_input_len80_2"], ids


def test_falls_back_when_no_summary_csv(tmp_path: Path) -> None:
    """Strategy 2 must still work for a tree that has no summary.csv at all."""
    task = tmp_path / "pxdesign" / "outputs_len80" / "design_outputs" / "input_len80"
    _write_csv(
        task / "seed_0" / "sample_level_output.csv",
        SAMPLE_COLUMNS,
        [{"name": "s_0", "seq_idx": "0", "sequence": SEQ_A, "i_pTM": "0.88", "pLDDT": "0.91", "unscaled_i_pAE": "6.2"}],
    )

    rows = _run_collector(tmp_path)
    assert len(rows) == 1
    assert rows[0]["sequence"] == SEQ_A
    assert rows[0]["af2_iptm"] == "0.88", "the ORIGINAL spellings must still resolve on this path"


def test_warns_when_summary_is_a_small_selection(tmp_path: Path) -> None:
    """summary.csv is PXDesign's pre-filter SELECTION, capped at
    --max_success_return. Today the CLI sets that cap to --N_sample so the whole
    pool comes through, but if that ever stops holding the pool would shrink
    silently -- which is the exact failure class this fix removes. Warn.
    """
    task = tmp_path / "pxdesign" / "outputs_len80" / "design_outputs" / "input_len80"
    _write_csv(
        task / "summary.csv",
        SUMMARY_COLUMNS,
        [{"rank": "1", "task_name": "input_len80", "sequence": SEQ_A, "af2_iptm": "0.88"}],
    )
    # A much larger sample-level pool sitting right next to it.
    _write_csv(
        task / "seed_0" / "sample_level_output.csv",
        SAMPLE_COLUMNS,
        [{"name": f"s_{i}", "seq_idx": "0", "sequence": SEQ_A if i % 2 else SEQ_B, "i_pTM": "0.5"} for i in range(50)],
    )

    snippet = _pxdesign_sequence_collector(str(tmp_path))
    proc = subprocess.run(["bash", "-c", snippet], capture_output=True, text=True)
    combined = proc.stdout + proc.stderr

    assert "WARNING" in combined.upper(), (
        f"a 1-row summary.csv against a 50-row sample pool must warn, not pass silently.\n{combined}"
    )
