"""`parse-seqs` must be idempotent on an `extract` FASTA, and step 0 must never rewrite its own input.

The generated `run_evaluate.sh` hands evaluate.sh `--sequences <out>/sequences.fasta`, and step 0 of
evaluate.sh then normalised that to `$OUTPUT/sequences.fasta` -- the SAME file. `parse-seqs` passed the
whole header line (`id  source=x  length=N`) to `write_fasta`, whose "no spaces inside an id" guard is
right for an id and wrong for `id + tags`: it welded the tags into the id
(`>protein_hunter_0_c1_source=protein_hunter_length=26`). The report then recorded
`source_tool = unknown` and a bloated `binder_id`, while the sidecar kept the right ones.

Both halves are pinned: the parser keeps tags as tags, and step 0 writes through a temporary file.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
from binder_comparison.cli import parse_seqs as parse_seqs_cli
from binder_comparison.cli import report as report_cli
from binder_comparison.io.read import read_fasta

REPO = Path(__file__).resolve().parents[1]
EVALUATE_SH = REPO / "Evaluator" / "evaluate.sh"
GOLDEN = REPO / "tests" / "integration" / "golden_pool"

TAGGED = (
    ">protein_hunter_0_c1  source=protein_hunter  length=26\n"
    "MKTAYIAKQRQISFVKSHFSRQLEER\n"
    ">mosaic_7  source=mosaic  length=12  rank=3\n"
    "ACDEFGHIKLMN\n"
)


def _parse(src: Path, dst: Path) -> None:
    parse_seqs_cli.run(argparse.Namespace(input=str(src), output=str(dst)))


class TestParseSeqsKeepsTags:
    def test_tags_stay_tags_and_the_id_stays_an_id(self, tmp_path):
        src, dst = tmp_path / "x.fasta", tmp_path / "y.fasta"
        src.write_text(TAGGED)
        _parse(src, dst)
        assert dst.read_text() == TAGGED

    def test_idempotent_when_input_and_output_are_the_same_path(self, tmp_path):
        """The shape the generated run script produced: read and write one file, twice over."""
        f = tmp_path / "sequences.fasta"
        f.write_text(TAGGED)
        _parse(f, f)
        _parse(f, f)
        assert f.read_text() == TAGGED
        assert "source=protein_hunter_length" not in f.read_text()

    def test_an_id_with_a_description_still_collapses_to_one_token(self, tmp_path):
        """The reason the guard exists: a space in an id ends it early for every reader."""
        src, dst = tmp_path / "x.fasta", tmp_path / "y.fasta"
        src.write_text(">sp|P1 some description  source=x\nACDEFGHIKL\n")
        _parse(src, dst)
        ((header, _),) = read_fasta(dst)
        assert header.split()[0] == "sp|P1_some_description"
        assert "source=x" in header.split()[1:]

    def test_a_plain_fasta_without_tags_is_unchanged(self, tmp_path):
        src, dst = tmp_path / "x.fasta", tmp_path / "y.fasta"
        src.write_text(">a\nACDEFGHIKL\n>b\nMKTAYIAKQR\n")
        _parse(src, dst)
        assert dst.read_text() == ">a\nACDEFGHIKL\n>b\nMKTAYIAKQR\n"

    def test_control_write_fasta_welds_a_whole_header_line_into_the_id(self, tmp_path):
        """Control: handing write_fasta the full 'id  tags' line is what produced the bug."""
        from binder_comparison.io.write import write_fasta

        out = tmp_path / "y.fasta"
        write_fasta(["MKTAYIAKQR"], out, headers=["protein_hunter_0_c1  source=protein_hunter  length=26"])
        assert out.read_text().startswith(">protein_hunter_0_c1_source=protein_hunter_length=26")


# ---------------------------------------------------------------------------
# evaluate.sh step 0, run for real (conda stubbed to this interpreter), then the report
# ---------------------------------------------------------------------------


def _fn(name: str) -> str:
    lines = EVALUATE_SH.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"^{re.escape(name)} \(\) \{{", line))
    for end in range(start + 1, len(lines)):
        if lines[end] == "}":
            return "\n".join(lines[start : end + 1])
    raise AssertionError(f"unterminated {name}")


def _step0(sequences: Path, fasta: Path, cwd: Path) -> subprocess.CompletedProcess:
    """Run evaluate.sh's real step-0 function, with the conda launcher stubbed to this interpreter."""
    program = "\n".join(
        [
            "set -euo pipefail",
            f'conda () {{ shift 4; "{sys.executable}" -m binder_comparison "$@"; }}',
            _fn("normalise_sequences"),
            f'normalise_sequences "{sequences}" "{fasta}"',
        ]
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO), str(REPO / "Evaluator")]))
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, env=env, cwd=str(cwd), timeout=120)


def _report(pool: Path, out: Path) -> pd.DataFrame:
    parser = argparse.ArgumentParser()
    report_cli.add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        [
            "report",
            "--boltz2-results",
            str(pool / "boltz2_results.csv"),
            "--af3-results",
            str(pool / "af3_results.csv"),
            "--esmfold2-results",
            str(pool / "esmfold2_results.csv"),
            "--sequences",
            str(pool / "sequences.fasta"),
            "--output",
            str(out),
        ]
    )
    report_cli.run(args)
    return pd.read_csv(out / "metrics.csv")


def test_step0_on_its_own_output_keeps_source_tool_in_the_report(tmp_path):
    """The generated run script: --sequences IS $OUTPUT/sequences.fasta. Report must still know each source."""
    pool = tmp_path / "pool"
    shutil.copytree(GOLDEN, pool)
    before = _report(pool, tmp_path / "rep_before")
    assert set(before["source_tool"]) == {"bindcraft2"}, "control: the golden pool carries real source tags"

    fasta = pool / "sequences.fasta"
    original = fasta.read_text()
    r = _step0(fasta, fasta, tmp_path)  # same path in and out, as in the generated run_evaluate.sh
    assert r.returncode == 0, r.stdout + r.stderr
    assert fasta.read_text() == original, "step 0 must leave an extract-format FASTA exactly as it was"

    after = _report(pool, tmp_path / "rep_after")
    assert set(after["source_tool"]) == {"bindcraft2"}
    assert sorted(after["binder_id"]) == sorted(before["binder_id"])
    assert not any("source=" in b for b in after["binder_id"])
    assert not list(pool.glob("*.parse.*")), "the temporary file must not be left behind"


def test_step0_converts_a_non_fasta_input_into_the_output_path(tmp_path):
    src = tmp_path / "seqs.txt"
    src.write_text("MKTAYIAKQRQISFVKSHFSRQLEER\nACDEFGHIKLMNPQRSTV\n")
    out = tmp_path / "out" / "sequences.fasta"
    out.parent.mkdir()
    r = _step0(src, out, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert [h for h, _ in read_fasta(out)] == ["seq_0001", "seq_0002"]


def test_step0_failure_aborts_and_leaves_the_existing_fasta_alone(tmp_path):
    fasta = tmp_path / "sequences.fasta"
    fasta.write_text("")  # parse-seqs refuses a file with no sequences
    fasta_bak = fasta.read_text()
    r = _step0(fasta, fasta, tmp_path)
    assert r.returncode != 0
    assert fasta.read_text() == fasta_bak
    assert not list(tmp_path.glob("*.parse.*"))


def test_evaluate_sh_calls_step0_through_the_function_with_distinct_temp_output():
    src = EVALUATE_SH.read_text()
    assert 'normalise_sequences "$SEQUENCES" "$FASTA"' in src
    body = _fn("normalise_sequences")
    assert '--output "$tmp"' in body and 'mv -f "$tmp" "$2"' in body
    assert src.index("[step 0] Parsing sequences") < src.index('normalise_sequences "$SEQUENCES" "$FASTA"')
