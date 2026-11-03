"""evaluate.sh says which engines it skipped and WHY, and does not mistake "no conda" for "no env".

`conda env list | awk | grep -qx ENV` was the whole detection. With conda unreachable (its own
`conda.sh` not in the four places the script knew, nothing on PATH) the pipeline failed, and the
note read "conda env 'binder-eval-af3' not found -- AF3 refolding will be skipped": wrong cause,
and every optional engine silently dropped, which the >=3-engine gate then turned into a ranking
with no shortlist. The run then died at its first `conda run`.

Now each skip carries its reason, a `[skipped]` line per engine names it, and a missing conda is
reported as exactly that, up front.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import REPO, system_conda_present

EVALUATE_SH = REPO / "Evaluator" / "evaluate.sh"
RUN_SH = REPO / "Evaluator" / "run.sh"
INSTALL_SH = REPO / "Evaluator" / "install.sh"

needs_no_system_conda = pytest.mark.skipif(
    bool(system_conda_present()) or bool(shutil.which("conda", path="/usr/bin:/bin")),
    reason="a conda in /opt or /usr/bin would be found",
)


def _evaluate(tmp_path: Path, envs: list[str] | None, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run evaluate.sh in a sandbox. envs=None means there is no conda at all."""
    sandbox = tmp_path / "Evaluator"
    (sandbox / "envs").mkdir(parents=True)
    shutil.copy(EVALUATE_SH, sandbox / "evaluate.sh")
    env = {"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    (tmp_path / "home").mkdir()
    if envs is not None:
        listing = "\n".join(f"echo '{name} /x'" for name in envs)
        conda_sh = tmp_path / "conda" / "etc" / "profile.d" / "conda.sh"
        conda_sh.parent.mkdir(parents=True)
        conda_sh.write_text(f'conda() {{\n  if [ "$1" = "env" ]; then\n{listing}\n    return 0\n  fi\n  return 7\n}}\n')
    seqs = tmp_path / "seqs.fasta"
    seqs.write_text(">b1\nMKTAYIAKQRQ\n")
    return subprocess.run(
        [
            "bash",
            str(sandbox / "evaluate.sh"),
            "--skip-boltz2",
            "--sequences",
            str(seqs),
            "--target-seq",
            "MKTAYIAKQRQ",
            "--output",
            str(tmp_path / "out"),
            *(extra or []),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_each_engine_without_an_env_is_listed_with_the_reason(tmp_path):
    r = _evaluate(tmp_path, ["binder-eval"])
    out = r.stdout + r.stderr
    assert "[skipped] AF3: conda env 'binder-eval-af3' not found" in out, out
    assert "[skipped] ESMFold2: conda env 'binder-eval-esmfold2' not found" in out, out


def test_an_engine_the_user_skipped_is_not_reported_as_missing(tmp_path):
    r = _evaluate(tmp_path, ["binder-eval"], ["--skip-af3"])
    out = r.stdout + r.stderr
    assert "[skipped] AF3" not in out, out
    assert "[skipped] ESMFold2" in out, out


def test_an_installed_engine_is_not_listed(tmp_path):
    r = _evaluate(tmp_path, ["binder-eval", "binder-eval-af3", "binder-eval-esmfold2"])
    out = r.stdout + r.stderr
    assert "[skipped] AF3" not in out and "[skipped] ESMFold2" not in out, out


@needs_no_system_conda
def test_no_conda_is_reported_as_no_conda_not_as_a_missing_env(tmp_path):
    r = _evaluate(tmp_path, None)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "conda not found" in out, out
    # the engines are named, with the real cause, instead of "env ... not found"
    assert "[skipped] AF3: conda not found" in out, out
    assert "[skipped] ESMFold2: conda not found" in out, out
    assert "conda env 'binder-eval-af3' not found" not in out, out
    # and it stops before running anything
    assert not (tmp_path / "out" / "sequences.fasta").exists()


@needs_no_system_conda
@pytest.mark.parametrize("script", [RUN_SH, INSTALL_SH], ids=lambda p: p.name)
def test_the_other_evaluator_scripts_stop_at_once_when_there_is_no_conda(script, tmp_path):
    sandbox = tmp_path / "Evaluator"
    sandbox.mkdir()
    shutil.copy(script, sandbox / script.name)
    (tmp_path / "home").mkdir()
    env = {"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    r = subprocess.run(
        ["bash", str(sandbox / script.name)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "conda not found" in out, out
