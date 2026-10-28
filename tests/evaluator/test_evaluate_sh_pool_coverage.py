"""The per-engine guard must check POOL COVERAGE, not a row delta.

2026-10-28, PD-L1. `engine_boltz2` was the one engine evaluate.sh invoked without
`--output-dir`, so `refold-boltz2` used its CWD-relative default `./refold_boltz2`,
shared by every run against every target. That directory held 1003 rows from earlier
pools. Resume skipped the whole 65-design pool, the runner copied the stale CSV into
place, and `check_engine_rows` saw 0 -> 1003 and printed:

    [Boltz-2] ok -- 1003 new row(s)

Boltz-2 had refolded nothing. It was the `--primary-engine`, so `ipsae_min` and the
Top-30 came from designs that were never in the campaign, and 0 of 65 designs had the
3 engines the gate wanted.

`pool_coverage` is extracted from evaluate.sh and exercised directly, so the awk is
really tested rather than assumed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATE_SH = REPO_ROOT / "Evaluator" / "evaluate.sh"


def _extract_function(name: str) -> str:
    """Pull a top-level `name () { ... }` block out of evaluate.sh."""
    src = EVALUATE_SH.read_text()
    # A multi-line body opens with `{` and nothing but an optional comment after it.
    m = re.search(rf"^{re.escape(name)} \(\) \{{[ \t]*(?:#.*)?$", src, re.M)
    if m:  # multi-line body
        lines = src[m.start() :].splitlines()
        body = [lines[0]]
        for line in lines[1:]:
            body.append(line)
            if line == "}":
                return "\n".join(body)
        raise AssertionError(f"unterminated body for {name}")
    m = re.search(rf"^{re.escape(name)} \(\) \{{.*\}}$", src, re.M)
    assert m, f"{name} not found in evaluate.sh"
    return m.group(0)


def _run_helper(call: str, *files: Path) -> str:
    script = textwrap.dedent(f"""\
        set -euo pipefail
        {_extract_function("pool_coverage")}
        {_extract_function("fasta_count")}
        {call}
    """)
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, cwd=str(files[0].parent))
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _csv(path: Path, seqs: list[str], *, header: str = "idx,sequence,iptm") -> Path:
    cols = header.split(",")
    rows = [header]
    for i, s in enumerate(seqs, 1):
        cell = {"idx": str(i), "sequence": s, "iptm": "0.9"}
        rows.append(",".join(cell.get(c, "") for c in cols))
    path.write_text("\n".join(rows) + "\n")
    return path


def _fasta(path: Path, seqs: list[str], *, wrap: int = 0) -> Path:
    out = []
    for i, s in enumerate(seqs, 1):
        out.append(f">b{i} source=mosaic length={len(s)}")
        out.extend([s[j : j + wrap] for j in range(0, len(s), wrap)] if wrap else [s])
    path.write_text("\n".join(out) + "\n")
    return path


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.skipif(shutil.which("awk") is None, reason="awk not available")
class TestPoolCoverage:
    def test_full_coverage(self, tmp_path: Path) -> None:
        csv = _csv(tmp_path / "e.csv", ["AAAA", "CCCC"])
        fa = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC"])
        assert _run_helper(f'pool_coverage "{csv}" "{fa}"', csv, fa) == "2"

    def test_the_pdl1_regression_a_disjoint_csv_covers_nothing(self, tmp_path: Path) -> None:
        csv = _csv(tmp_path / "e.csv", [f"STALE{i:04d}" for i in range(1003)])
        fa = _fasta(tmp_path / "s.fasta", [f"POOL{i:04d}" for i in range(65)])
        assert _run_helper(f'pool_coverage "{csv}" "{fa}"', csv, fa) == "0"

    def test_partial_coverage_is_counted_exactly(self, tmp_path: Path) -> None:
        csv = _csv(tmp_path / "e.csv", ["AAAA", "OFFPOOL"])
        fa = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC", "GGGG"])
        assert _run_helper(f'pool_coverage "{csv}" "{fa}"', csv, fa) == "1"

    def test_a_wrapped_fasta_is_read_as_one_sequence(self, tmp_path: Path) -> None:
        seq = "AAAACCCCGGGGTTTT"
        csv = _csv(tmp_path / "e.csv", [seq])
        fa = _fasta(tmp_path / "s.fasta", [seq], wrap=5)
        assert _run_helper(f'pool_coverage "{csv}" "{fa}"', csv, fa) == "1"

    def test_the_sequence_column_is_found_by_name_not_position(self, tmp_path: Path) -> None:
        """Engine CSVs do not agree on column order; Boltz-2's `sequence` is 3rd."""
        csv = _csv(tmp_path / "e.csv", ["AAAA"], header="run_id,idx,sequence,iptm")
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        assert _run_helper(f'pool_coverage "{csv}" "{fa}"', csv, fa) == "1"

    def test_a_csv_without_a_sequence_column_covers_nothing(self, tmp_path: Path) -> None:
        csv = _csv(tmp_path / "e.csv", ["AAAA"], header="idx,iptm")
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        assert _run_helper(f'pool_coverage "{csv}" "{fa}"', csv, fa) == "0"

    def test_a_header_only_csv_covers_nothing(self, tmp_path: Path) -> None:
        csv = _csv(tmp_path / "e.csv", [])
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        assert _run_helper(f'pool_coverage "{csv}" "{fa}"', csv, fa) == "0"

    def test_a_missing_csv_covers_nothing_rather_than_erroring(self, tmp_path: Path) -> None:
        fa = _fasta(tmp_path / "s.fasta", ["AAAA"])
        assert _run_helper(f'pool_coverage "{tmp_path}/nope.csv" "{fa}"', fa) == "0"

    def test_fasta_count_counts_records(self, tmp_path: Path) -> None:
        fa = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC", "GGGG"], wrap=2)
        assert _run_helper(f'fasta_count "{fa}"', fa) == "3"


class TestGuardWiring:
    """Static assertions: the guard must be reached, and boltz2 must get its own dir."""

    def test_check_engine_rows_consults_pool_coverage(self) -> None:
        body = _extract_function("check_engine_rows")
        assert "pool_coverage" in body, "the row-delta guard is still the only check"
        assert "$SEQUENCES" in body

    def test_zero_coverage_returns_failure(self) -> None:
        body = _extract_function("check_engine_rows")
        m = re.search(r'if \[\[ "\$covered" -eq 0 \]\]; then(.*?)fi', body, re.S)
        assert m, "no zero-coverage branch"
        assert "return 1" in m.group(1), "zero pool coverage must abort, not warn"

    def test_boltz2_is_given_a_per_run_output_dir(self) -> None:
        body = _extract_function("engine_boltz2")
        assert "--output-dir" in body, (
            "refold-boltz2 defaults --output-dir to a CWD-relative ./refold_boltz2 shared "
            "by every run and every target; that is what lost the PD-L1 pool"
        )
        assert '"$OUTPUT/refold_boltz2"' in body

    @pytest.mark.parametrize("fn", ["engine_boltz2", "engine_af3", "engine_esmfold2"])
    def test_every_engine_writes_under_the_run_output(self, fn: str) -> None:
        assert '"$OUTPUT/refold_' in _extract_function(fn)
