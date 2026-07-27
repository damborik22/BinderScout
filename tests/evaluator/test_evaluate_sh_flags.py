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
