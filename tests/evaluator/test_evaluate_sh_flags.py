"""Regression tests for the Evaluator shell entry points (F10).

``Evaluator/run.sh`` is the interactive wizard that the installers wire up as the
``evaluate`` shortcut. It shells out to ``Evaluator/evaluate.sh``, whose argument
parser rejects anything it does not know::

    *) echo "Unknown argument: $1"; exit 1 ;;

So any flag ``run.sh`` passes that ``evaluate.sh`` has no ``case`` arm for kills the
documented human entry point on the spot. That is exactly what happened with
``--target-pdb``. These tests parse both scripts and assert the two stay in sync, so
future drift in either file is caught rather than shipped.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SH = REPO_ROOT / "Evaluator" / "run.sh"
EVALUATE_SH = REPO_ROOT / "Evaluator" / "evaluate.sh"

# A case-arm line, e.g. `--output|-o)      OUTPUT="$2"; shift 2 ;;`
_CASE_ARM_RE = re.compile(r"^\s*([^\s)(]+(?:\|[^\s)(]+)*)\)")
# A long/short option token appearing in a command invocation.
_FLAG_RE = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")


def _accepted_flags(script: str) -> set[str]:
    """Flags evaluate.sh's argument-parsing `while` loop has a `case` arm for."""
    lines = script.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("while [[ $# -gt 0 ]]"))
    end = next(i for i, ln in enumerate(lines[start:], start) if ln.strip() == "done")

    flags: set[str] = set()
    for line in lines[start + 1 : end]:
        if line.lstrip().startswith("#"):
            continue
        m = _CASE_ARM_RE.match(line)
        if not m:
            continue
        # Patterns are `|`-separated; keep only real option tokens (drops `*` and
        # the arms of the nested `case "$PRIMARY_ENGINE"` value check).
        flags.update(tok for tok in m.group(1).split("|") if tok.startswith("-"))
    return flags


def _flags_passed_to_evaluate_sh(script: str) -> set[str]:
    """Flags run.sh hands to evaluate.sh, including backslash-continued lines."""
    lines = script.splitlines()
    flags: set[str] = set()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") or "evaluate.sh" not in line:
            continue
        if not re.search(r"\b(?:exec\s+)?bash\b", line):
            continue  # a mention, not an invocation
        block = [line]
        while block[-1].rstrip().endswith("\\") and i + len(block) < len(lines):
            block.append(lines[i + len(block)])
        for part in block:
            if part.lstrip().startswith("#"):
                continue
            flags.update(_FLAG_RE.findall(part))
    return flags


def test_parsers_find_the_expected_shape() -> None:
    """Guard the regexes themselves so the real assertions can't pass vacuously."""
    accepted = _accepted_flags(EVALUATE_SH.read_text())
    passed = _flags_passed_to_evaluate_sh(RUN_SH.read_text())

    assert {"--sequences", "--target-seq", "--output", "--help"} <= accepted
    assert "*" not in accepted
    assert {"--sequences", "--target-seq", "--output"} <= passed


def test_run_sh_passes_only_flags_evaluate_sh_accepts() -> None:
    """F10: run.sh passed --target-pdb, which evaluate.sh rejects with exit 1."""
    accepted = _accepted_flags(EVALUATE_SH.read_text())
    unknown = sorted(_flags_passed_to_evaluate_sh(RUN_SH.read_text()) - accepted)

    assert not unknown, (
        f"Evaluator/run.sh passes {unknown} to Evaluator/evaluate.sh, which has no "
        f"case arm for them — evaluate.sh will die with 'Unknown argument' before "
        f"doing any work. Add a case arm in evaluate.sh or stop passing the flag."
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_evaluate_sh_parser_accepts_the_run_sh_invocation(tmp_path: Path) -> None:
    """Behavioural check: drive evaluate.sh's real parser with run.sh's flag set.

    Everything evaluate.sh shells out to is stubbed, so this exercises argument
    parsing only — no conda env, no GPU, no refolding.
    """
    passed = _flags_passed_to_evaluate_sh(RUN_SH.read_text())

    sandbox = tmp_path / "Evaluator"
    (sandbox / "envs").mkdir(parents=True)
    shutil.copy(EVALUATE_SH, sandbox / "evaluate.sh")

    venv = tmp_path / "fakevenv"
    (venv / "bin").mkdir(parents=True)
    stub = venv / "bin" / "binder-compare"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    (sandbox / "envs" / "mosaic_venv_path").write_text(f"{venv}\n")

    # Stub conda so no real environment is ever touched.
    stub_bin = tmp_path / "stubbin"
    stub_bin.mkdir()
    conda = stub_bin / "conda"
    conda.write_text("#!/bin/sh\nexit 0\n")
    conda.chmod(0o755)

    sequences = tmp_path / "seqs.fasta"
    sequences.write_text(">b1\nMKTAYIAKQRQ\n")

    # Build the argv run.sh would produce, driven by what it actually passes.
    values = {
        "--sequences": str(sequences),
        "--target-seq": "MKTAYIAKQRQ",
        "--target-pdb": str(tmp_path / "target.pdb"),
        "--output": str(tmp_path / "out"),
    }
    argv: list[str] = []
    for flag in sorted(passed):
        argv.append(flag)
        argv.append(values.get(flag, "dummy"))

    env = {**os.environ, "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}"}
    proc = subprocess.run(
        ["bash", str(sandbox / "evaluate.sh"), *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    combined = proc.stdout + proc.stderr
    assert "Unknown argument" not in combined, f"evaluate.sh rejected run.sh's own invocation: {combined.strip()}"


# --- Cross-engine gate vs. the engines that actually run ----------------------


def _run_evaluate_sh(tmp_path: Path, envs: list[str], argv: list[str]):
    """Drive evaluate.sh's real parser with a stub conda reporting *envs*.

    Everything past argument parsing shells out through the stub, so this exercises
    engine auto-detection and the gate warning only — no conda env, no GPU.
    """
    sandbox = tmp_path / "Evaluator"
    (sandbox / "envs").mkdir(parents=True, exist_ok=True)
    shutil.copy(EVALUATE_SH, sandbox / "evaluate.sh")

    stub_bin = tmp_path / "stubbin"
    stub_bin.mkdir(exist_ok=True)
    listing = "\n".join(f"echo '{name} /x'" for name in envs)
    conda = stub_bin / "conda"
    conda.write_text(f'#!/bin/sh\nif [ "$1" = "env" ]; then\n{listing}\nexit 0\nfi\nexit 7\n')
    conda.chmod(0o755)

    sequences = tmp_path / "seqs.fasta"
    sequences.write_text(">b1\nMKTAYIAKQRQ\n")

    env = {**os.environ, "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}"}
    proc = subprocess.run(
        [
            "bash",
            str(sandbox / "evaluate.sh"),
            "--skip-boltz2",  # Boltz-2 needs the Mosaic venv; not what we are testing
            "--sequences",
            str(sequences),
            "--target-seq",
            "MKTAYIAKQRQ",
            "--output",
            str(tmp_path / "out"),
            *argv,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    return proc.stdout + proc.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
class TestMinEnginesGate:
    """The ranking gates on how many independent engines refolded each design (default
    3). AF3 needs >100 GB of GPU memory, so most hosts run only two — and every design
    then fails the gate, leaving a report whose whole shortlist is ineligible. There was
    no way to say otherwise: evaluate.sh had no --min-engines passthrough at all.
    """

    _TWO: ClassVar = ["binder-eval", "binder-eval-af3", "binder-eval-esmfold2"]

    def test_flag_is_accepted(self):
        assert "--min-engines" in _accepted_flags(EVALUATE_SH.read_text())

    def test_warns_when_fewer_engines_run_than_the_default_gate(self, tmp_path):
        out = _run_evaluate_sh(tmp_path, self._TWO, [])
        assert "2 refold engine(s) will run" in out
        assert "--min-engines 2" in out, "the warning must name the flag that fixes it"

    def test_no_warning_once_the_gate_matches_the_engines(self, tmp_path):
        out = _run_evaluate_sh(tmp_path, self._TWO, ["--min-engines", "2"])
        assert "cross-engine gate defaults to 3" not in out

    def test_warns_when_the_requested_gate_exceeds_the_engines(self, tmp_path):
        out = _run_evaluate_sh(tmp_path, self._TWO, ["--min-engines", "3"])
        assert "only 2 engine(s) will run" in out

    def test_single_engine_is_told_a_consensus_is_impossible(self, tmp_path):
        out = _run_evaluate_sh(tmp_path, ["binder-eval", "binder-eval-esmfold2"], [])
        assert "needs at least 2 engines" in out

    def test_gate_is_never_lowered_automatically(self):
        """Deriving the gate from the local install would make two operators with the
        same designs produce different rankings — the contradiction Part J's revert
        removed for Protenix. MIN_ENGINES must come only from the operator's flag.

        Asserted against the source rather than a run: the stub cannot reach the report
        call, so a behavioural check here would pass vacuously.
        """
        assignments = re.findall(r"^\s*MIN_ENGINES=.*$", EVALUATE_SH.read_text(), re.M)
        assert assignments, "MIN_ENGINES vanished — this guard needs rewriting"
        for line in assignments:
            assert "_N_ENGINES" not in line, f"gate derived from the local install: {line.strip()}"

    def test_the_gate_reaches_the_report_only_when_asked_for(self):
        """The passthrough is conditional: no flag means binder-compare applies its own
        default, so the shell script never silently pins a gate of its own."""
        source = EVALUATE_SH.read_text()
        block = source[source.index("REPORT_ARGS+=(--primary-engine") :]
        block = block[: block.index("conda run")]
        assert 'if [[ -n "$MIN_ENGINES" ]]; then' in block
        assert 'REPORT_ARGS+=(--min-engines "$MIN_ENGINES")' in block

    @pytest.mark.parametrize("bad", ["1", "abc", ""])
    def test_rejects_a_gate_below_the_floor_or_non_numeric(self, tmp_path, bad):
        out = _run_evaluate_sh(tmp_path, self._TWO, ["--min-engines", bad])
        assert "Error: --min-engines" in out
