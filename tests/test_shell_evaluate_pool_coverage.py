"""evaluate.sh's per-engine guard must check POOL COVERAGE, not a row delta.

An engine can write rows and exit 0 without having refolded the pool: a refold that resumes
off a stale CSV shared with earlier pools gains hundreds of rows (0 -> 1003) and the guard
read it as "ok -- 1003 new row(s)", while none of the pool's own designs had been folded.
Every design then lacked that engine and failed the cross-engine gate.

`pool_coverage` counts the pool's FASTA sequences the engine CSV actually carries. The
functions are extracted from evaluate.sh and run in a subshell, so the awk is exercised
rather than asserted to exist. A row only counts when it carries a score (non-empty
`iptm`): this line's `csv_rows` already refuses to call a blank row a refold.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

EVALUATE_SH = Path(__file__).resolve().parents[1] / "Evaluator" / "evaluate.sh"


def _fn(name: str) -> str:
    """The text of a top-level `name () { ... }` function of evaluate.sh."""
    lines = EVALUATE_SH.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"^{re.escape(name)} \(\) \{{", line))
    if lines[start].rstrip().endswith("}"):  # one-line function
        return lines[start]
    for end in range(start + 1, len(lines)):
        if lines[end] == "}":
            return "\n".join(lines[start : end + 1])
    raise AssertionError(f"unterminated {name}")


def _bash(program: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=60, cwd=str(cwd))


def _csv(path: Path, seqs: list[str], *, header: str = "idx,sequence,iptm", iptm: str = "0.9") -> Path:
    rows = [header]
    for i, s in enumerate(seqs, 1):
        cell = {"idx": str(i), "sequence": s, "iptm": iptm}
        rows.append(",".join(cell.get(c, "") for c in header.split(",")))
    path.write_text("\n".join(rows) + "\n")
    return path


def _fasta(path: Path, seqs: list[str], *, wrap: int = 0) -> Path:
    out = []
    for i, s in enumerate(seqs, 1):
        out.append(f">b{i} source=mosaic length={len(s)}")
        out.extend([s[j : j + wrap] for j in range(0, len(s), wrap)] if wrap else [s])
    path.write_text("\n".join(out) + "\n")
    return path


def _coverage(csv: Path | str, fa: Path, cwd: Path) -> str:
    program = f'{_fn("pool_coverage")}\npool_coverage "{csv}" "{fa}"'
    r = _bash(program, cwd)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class TestPoolCoverage:
    def test_full_coverage(self, tmp_path):
        csv = _csv(tmp_path / "e.csv", ["AAAA", "CCCC"])
        fa = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC"])
        assert _coverage(csv, fa, tmp_path) == "2"

    def test_a_csv_of_other_pools_covers_nothing(self, tmp_path):
        csv = _csv(tmp_path / "e.csv", [f"STALE{i:04d}" for i in range(1003)])
        fa = _fasta(tmp_path / "s.fasta", [f"POOL{i:04d}" for i in range(65)])
        assert _coverage(csv, fa, tmp_path) == "0"

    def test_partial_coverage_is_counted_exactly(self, tmp_path):
        csv = _csv(tmp_path / "e.csv", ["AAAA", "OFFPOOL"])
        fa = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC", "GGGG"])
        assert _coverage(csv, fa, tmp_path) == "1"

    def test_a_wrapped_fasta_record_is_one_sequence(self, tmp_path):
        seq = "AAAACCCCGGGGTTTT"
        csv = _csv(tmp_path / "e.csv", [seq])
        fa = _fasta(tmp_path / "s.fasta", [seq], wrap=5)
        assert _coverage(csv, fa, tmp_path) == "1"

    def test_crlf_line_endings_do_not_hide_a_design(self, tmp_path):
        csv = _csv(tmp_path / "e.csv", ["AAAA"])
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        fa.write_bytes(fa.read_bytes().replace(b"\n", b"\r\n"))
        assert _coverage(csv, fa, tmp_path) == "1"

    def test_the_sequence_column_is_found_by_name_not_position(self, tmp_path):
        csv = _csv(tmp_path / "e.csv", ["AAAA"], header="run_id,idx,sequence,iptm")
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        assert _coverage(csv, fa, tmp_path) == "1"

    def test_a_csv_without_a_sequence_column_covers_nothing(self, tmp_path):
        csv = _csv(tmp_path / "e.csv", ["AAAA"], header="idx,iptm")
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        assert _coverage(csv, fa, tmp_path) == "0"

    def test_a_header_only_csv_covers_nothing(self, tmp_path):
        csv = _csv(tmp_path / "e.csv", [])
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        assert _coverage(csv, fa, tmp_path) == "0"

    def test_a_missing_csv_covers_nothing_rather_than_erroring(self, tmp_path):
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        assert _coverage(tmp_path / "nope.csv", fa, tmp_path) == "0"

    def test_a_blank_score_is_not_coverage(self, tmp_path):
        """A full-length row with every score blank (an OOM) is not a refold of that design."""
        csv = _csv(tmp_path / "e.csv", ["AAAA", "CCCC"], iptm="")
        fa = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC"])
        assert _coverage(csv, fa, tmp_path) == "0"

    def test_fasta_count_counts_records(self, tmp_path):
        fa = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC", "GGGG"], wrap=2)
        r = _bash(f'{_fn("fasta_count")}\nfasta_count "{fa}"', tmp_path)
        assert r.stdout.strip() == "3"


def _check(tmp_path: Path, csv_seqs: list[str], pool: list[str], *, before: int = 0, rc: int = 0, iptm: str = "0.9"):
    """Run the real check_engine_rows against a CSV and a pool FASTA."""
    csv = _csv(tmp_path / "e.csv", csv_seqs, iptm=iptm)
    fa = _fasta(tmp_path / "s.fasta", pool)
    program = "\n".join(
        [_fn("csv_rows"), _fn("pool_coverage"), _fn("fasta_count"), _fn("check_engine_rows")]
        + [f'SEQUENCES="{fa}"', f'check_engine_rows "Boltz-2" "{csv}" {before} {rc}', "echo rc=$?"]
    )
    return _bash(program, tmp_path)


class TestCheckEngineRows:
    def test_the_stale_csv_case_aborts(self, tmp_path):
        """The measured failure: 1003 rows gained, none of them in the 65-design pool."""
        r = _check(tmp_path, [f"STALE{i:04d}" for i in range(1003)], [f"POOL{i:04d}" for i in range(65)])
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "NONE of them is a" in r.stderr, r.stderr
        assert "ok --" not in r.stdout, r.stdout

    def test_a_covered_pool_passes_and_reports_coverage(self, tmp_path):
        r = _check(tmp_path, ["AAAA", "CCCC"], ["AAAA", "CCCC"])
        assert "rc=0" in r.stdout, r.stdout + r.stderr
        assert "ok -- 2/2 pool design(s), 2 new row(s)" in r.stdout, r.stdout

    def test_a_partial_pool_passes_but_says_what_is_missing(self, tmp_path):
        r = _check(tmp_path, ["AAAA", "OFF"], ["AAAA", "CCCC", "GGGG"])
        assert "rc=0" in r.stdout, r.stdout + r.stderr
        assert "covers 1/3 pool design(s)" in r.stderr, r.stderr

    def test_the_scored_row_check_still_runs_first(self, tmp_path):
        """This line's non-empty-iptm counting must survive: blank rows are zero new rows."""
        r = _check(tmp_path, ["AAAA", "CCCC"], ["AAAA", "CCCC"], iptm="")
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "no new SCORED rows" in r.stderr, r.stderr

    def test_a_failed_engine_still_fails_before_coverage_is_read(self, tmp_path):
        r = _check(tmp_path, ["AAAA"], ["AAAA"], rc=3)
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "refolding failed (rc=3)" in r.stderr, r.stderr


def test_both_the_sequential_and_the_concurrent_path_reach_the_guard():
    """Control: the guard is only worth anything if every refold path calls it."""
    assert "check_engine_rows" in _fn("run_engine_checked")
    assert 'if ! check_engine_rows "${E_NAMES[$i]}"' in EVALUATE_SH.read_text()


def test_boltz2_is_given_a_per_run_output_dir():
    """refold-boltz2 defaults --output-dir to a CWD-relative dir shared by every run."""
    assert '--output-dir "$OUTPUT/refold_boltz2"' in _fn("engine_boltz2")


@pytest.mark.parametrize("fn", ["engine_boltz2", "engine_af3", "engine_esmfold2"])
def test_every_engine_writes_under_the_run_output(fn):
    assert '"$OUTPUT/refold_' in _fn(fn)
