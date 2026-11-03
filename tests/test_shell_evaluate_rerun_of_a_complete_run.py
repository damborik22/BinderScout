"""Re-running a FINISHED evaluate run must succeed, and say the engine was already complete.

The generated run_evaluate.sh always passes `--resume`. On a complete run every engine skips every
design and exits 0 writing nothing, and `check_engine_rows` read "no new rows" as failure:
`Error: Boltz-2 exited 0 but wrote no new SCORED rows ... (1 -> 1)`, exit 1, report never regenerated.

`pool_coverage` is the right signal: if every pool sequence already carries a scored row, the engine
is complete. The guards that must survive are pinned here too: no rows AND an uncovered pool is still
an error, and a stale CSV that gained rows without covering the pool still aborts.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

EVALUATE_SH = Path(__file__).resolve().parents[1] / "Evaluator" / "evaluate.sh"


def _fn(name: str) -> str:
    lines = EVALUATE_SH.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"^{re.escape(name)} \(\) \{{", line))
    if lines[start].rstrip().endswith("}"):
        return lines[start]
    for end in range(start + 1, len(lines)):
        if lines[end] == "}":
            return "\n".join(lines[start : end + 1])
    raise AssertionError(f"unterminated {name}")


def _bash(program: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=60, cwd=str(cwd))


def _csv(path: Path, seqs: list[str], iptm: str = "0.9") -> Path:
    rows = ["idx,sequence,iptm"] + [f"{i},{s},{iptm}" for i, s in enumerate(seqs, 1)]
    path.write_text("\n".join(rows) + "\n")
    return path


def _fasta(path: Path, seqs: list[str]) -> Path:
    path.write_text("".join(f">b{i} source=x\n{s}\n" for i, s in enumerate(seqs, 1)))
    return path


_FUNCS = ["csv_rows", "pool_coverage", "fasta_count", "check_engine_rows"]


def _check(tmp_path: Path, csv_seqs: list[str], pool: list[str], *, before: int, iptm: str = "0.9"):
    csv = _csv(tmp_path / "e.csv", csv_seqs, iptm=iptm)
    fa = _fasta(tmp_path / "s.fasta", pool)
    program = "\n".join(
        [_fn(n) for n in _FUNCS]
        + [f'SEQUENCES="{fa}"', f'check_engine_rows "Boltz-2" "{csv}" {before} 0', "echo rc=$?"]
    )
    return _bash(program, tmp_path)


class TestCompleteRunIsNotAFailure:
    def test_resume_on_a_complete_run_writes_nothing_and_is_ok(self, tmp_path):
        """The measured failure: (1 -> 1) with the one design already scored."""
        r = _check(tmp_path, ["AAAA"], ["AAAA"], before=1)
        assert "rc=0" in r.stdout, r.stdout + r.stderr
        assert "already complete" in r.stdout, r.stdout
        assert "Error" not in r.stderr, r.stderr

    def test_a_larger_complete_pool_is_ok_too(self, tmp_path):
        seqs = [f"SEQ{i:03d}" for i in range(65)]
        r = _check(tmp_path, seqs, seqs, before=65)
        assert "rc=0" in r.stdout, r.stdout + r.stderr
        assert "already complete: 65/65" in r.stdout, r.stdout

    def test_control_the_new_rows_path_is_still_the_one_that_says_new_rows(self, tmp_path):
        """Control: rows were written -> the ordinary 'ok -- N new row(s)' line, not 'already complete'."""
        r = _check(tmp_path, ["AAAA", "CCCC"], ["AAAA", "CCCC"], before=0)
        assert "rc=0" in r.stdout and "ok -- 2/2 pool design(s), 2 new row(s)" in r.stdout, r.stdout
        assert "already complete" not in r.stdout


class TestTheGuardsThatMustSurvive:
    def test_no_new_rows_and_an_uncovered_pool_is_still_an_error(self, tmp_path):
        """A partly-covered pool that gained nothing is a stalled engine, not a finished one."""
        r = _check(tmp_path, ["AAAA"], ["AAAA", "CCCC"], before=1)
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "no new SCORED rows" in r.stderr, r.stderr
        assert "already complete" not in r.stdout

    def test_no_new_rows_and_a_csv_of_another_pool_is_still_an_error(self, tmp_path):
        r = _check(tmp_path, ["STALE1", "STALE2"], ["AAAA", "CCCC"], before=2)
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "no new SCORED rows" in r.stderr, r.stderr

    def test_a_file_of_blank_rows_is_not_a_complete_run(self, tmp_path):
        """Blank iptm rows cover nothing, so an all-blank CSV cannot be 'already complete'."""
        r = _check(tmp_path, ["AAAA", "CCCC"], ["AAAA", "CCCC"], before=0, iptm="")
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "no new SCORED rows" in r.stderr, r.stderr

    def test_the_stale_shared_csv_that_gained_rows_still_aborts(self, tmp_path):
        r = _check(tmp_path, [f"STALE{i:04d}" for i in range(50)], [f"POOL{i:04d}" for i in range(5)], before=0)
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "NONE of them is a" in r.stderr, r.stderr

    def test_an_empty_pool_is_not_a_complete_run(self, tmp_path):
        """0 >= 0 must not read as 'covered': a pool FASTA with no records proves nothing."""
        r = _check(tmp_path, ["AAAA"], [], before=1)
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "already complete" not in r.stdout

    def test_a_failed_engine_still_fails_even_on_a_covered_pool(self, tmp_path):
        csv = _csv(tmp_path / "e.csv", ["AAAA"])
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        program = "\n".join(
            [_fn(n) for n in _FUNCS] + [f'SEQUENCES="{fa}"', f'check_engine_rows "Boltz-2" "{csv}" 1 7', "echo rc=$?"]
        )
        r = _bash(program, tmp_path)
        assert "rc=1" in r.stdout and "refolding failed (rc=7)" in r.stderr, r.stdout + r.stderr


def test_the_sequential_wrapper_passes_a_stub_engine_that_writes_nothing_on_a_complete_run(tmp_path):
    """Through run_engine_checked with a stub engine, as the generated --resume run reaches it."""
    csv = _csv(tmp_path / "e.csv", ["AAAA", "CCCC"])
    fa = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC"])
    program = "\n".join(
        [_fn(n) for n in [*_FUNCS, "run_engine_checked"]]
        + [
            f'SEQUENCES="{fa}"',
            "stub_engine () { return 0; }  # --resume skipped every design: exits 0, writes nothing",
            f'run_engine_checked "Boltz-2" stub_engine "{csv}"',
            "echo reached-after-engine",
        ]
    )
    r = _bash("set -euo pipefail\n" + program, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "reached-after-engine" in r.stdout
    assert "already complete" in r.stdout


class TestACompleteRunOfAnotherTargetIsNotComplete:
    """`--resume` keys on the binder sequence only: a re-run with a DIFFERENT --target-seq into the same
    output directory finds every design 'completed' and writes nothing. That must not read as success
    (review 2026-11-03: the new already-complete shortcut would have published the old target's scores)."""

    def _run(self, tmp_path, csv_target: str, run_target: str):
        csv = tmp_path / "e.csv"
        csv.write_text(f"idx,sequence,target_sequence,iptm\n1,AAAA,{csv_target},0.9\n")
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        program = "\n".join(
            [_fn(n) for n in _FUNCS]
            + [
                f'SEQUENCES="{fa}"',
                f'TARGET_SEQ="{run_target}"',
                f'check_engine_rows "Boltz-2" "{csv}" 1 0',
                "echo rc=$?",
            ]
        )
        return _bash(program, tmp_path)

    def test_the_same_target_is_complete(self, tmp_path):
        r = self._run(tmp_path, "TTTTTT", "TTTTTT")
        assert "already complete" in r.stdout and "rc=0" in r.stdout, (r.stdout, r.stderr)

    def test_a_different_target_is_refused(self, tmp_path):
        r = self._run(tmp_path, "OLDTARGET", "NEWTARGET")
        assert "rc=1" in r.stdout and "DIFFERENT target" in r.stderr, (r.stdout, r.stderr)

    def test_case_and_whitespace_in_the_target_do_not_matter(self, tmp_path):
        r = self._run(tmp_path, " tttttt ", "TTTTTT")
        assert "already complete" in r.stdout, (r.stdout, r.stderr)
