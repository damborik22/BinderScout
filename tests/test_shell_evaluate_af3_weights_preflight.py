"""evaluate.sh resolves AF3's weights up front, not after hours of other engines.

The AF3 env alone does not mean AF3 can run: its weights are gated, so the installer can
neither bundle nor fetch them -- it only prints where to put them. Detecting the env but not
the weights meant a pool refolded through Boltz-2 and ESMFold2 for hours and only then died
in the AF3 step on FileNotFoundError.

The preflight uses refold_af3.py's own search order -- $AF3_MODEL_DIR (taken as-is when it is
a directory), then ~/.alphafold3/models, ~/af3_models, /opt/alphafold3/models (taken only when
non-empty) -- and degrades the run NOW, naming the engine in the `[skipped]` summary, exactly as
a missing env does.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.test_shell_evaluate_says_why_engines_are_skipped import EVALUATE_SH, _evaluate

ENVS = ["binder-eval", "binder-eval-af3", "binder-eval-esmfold2"]
NO_WEIGHTS = "[skipped] AF3: no AF3 weights found"
FOUND = "AF3 weights found: "

pytestmark = pytest.mark.skipif(
    Path("/opt/alphafold3/models").is_dir(), reason="a system-wide AF3 model directory would be found"
)


def _models(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "af3.bin").write_bytes(b"x")
    return path


def _run(tmp_path, extra=None, extra_env=None, envs=ENVS):
    r = _evaluate(tmp_path, envs, extra, extra_env)
    return r, r.stdout + r.stderr


def test_missing_weights_skip_af3_up_front_and_name_why(tmp_path):
    _, out = _run(tmp_path)
    assert NO_WEIGHTS in out, out
    assert "Searched: $AF3_MODEL_DIR, ~/.alphafold3/models, ~/af3_models, /opt/alphafold3/models" in out, out
    assert "gated" in out, out
    assert FOUND not in out, out
    # and AF3 really is out of the run: only ESMFold2 is left to reach the report (Boltz-2 is skipped
    # in the sandbox), and the existing gate warning says so before any engine starts.
    assert "1 refold engine(s) will reach the report" in out, out


def test_the_skip_is_listed_in_the_summary_with_the_other_skipped_engines(tmp_path):
    _, out = _run(tmp_path)
    assert "[skipped] AF3: no AF3 weights found" in out, out
    # ESMFold2's env is installed, so only AF3 is listed.
    assert "[skipped] ESMFold2" not in out, out


def test_weights_in_AF3_MODEL_DIR_are_found(tmp_path):
    models = _models(tmp_path / "m")
    _, out = _run(tmp_path, extra_env={"AF3_MODEL_DIR": str(models)})
    assert f"{FOUND}{models}" in out, out
    assert NO_WEIGHTS not in out, out
    # control: with weights, AF3 stays in the run (AF3 + ESMFold2)
    assert "2 refold engine(s) will reach the report" in out, out


def _function() -> str:
    lines = EVALUATE_SH.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r"^_af3_weights_dir \(\) \{", line))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _resolve(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    exports = "\n".join(f'export {k}="{v}"' for k, v in env.items())
    prog = f'HOME="{home}"; unset AF3_MODEL_DIR\n{exports}\n{_function()}\n_af3_weights_dir'
    return subprocess.run(["bash", "-c", prog], capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("sub", [".alphafold3/models", "af3_models"])
def test_weights_in_a_default_directory_are_found(tmp_path, sub):
    default = _models(tmp_path / "h" / sub)
    r = _resolve(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(default)


def test_no_weights_anywhere_is_a_failure(tmp_path):
    assert _resolve(tmp_path).returncode != 0


def test_an_empty_default_directory_is_not_weights(tmp_path):
    (tmp_path / "h" / "af3_models").mkdir(parents=True)
    assert _resolve(tmp_path).returncode != 0


def test_AF3_MODEL_DIR_wins_over_a_default_directory(tmp_path):
    _models(tmp_path / "h" / "af3_models")
    chosen = _models(tmp_path / "chosen")
    r = _resolve(tmp_path, AF3_MODEL_DIR=str(chosen))
    assert r.stdout.strip() == str(chosen), r.stderr


def test_an_empty_AF3_MODEL_DIR_is_not_silently_replaced_by_a_default(tmp_path):
    """refold_af3.py takes $AF3_MODEL_DIR as-is when it is a directory, empty or not.

    Falling through to a populated default here would pass the preflight and then fail in the AF3
    step, which is the very failure this check exists to move earlier.
    """
    _models(tmp_path / "h" / "af3_models")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _resolve(tmp_path, AF3_MODEL_DIR=str(empty)).returncode != 0


def test_AF3_MODEL_DIR_that_is_not_a_directory_falls_through_to_the_defaults(tmp_path):
    """refold_af3.py ignores a $AF3_MODEL_DIR that is not a directory."""
    default = _models(tmp_path / "h" / "af3_models")
    r = _resolve(tmp_path, AF3_MODEL_DIR=str(tmp_path / "nope"))
    assert r.stdout.strip() == str(default), r.stderr


def test_an_empty_AF3_MODEL_DIR_is_named_in_the_note(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _, out = _run(tmp_path, extra_env={"AF3_MODEL_DIR": str(empty)})
    assert NO_WEIGHTS in out, out
    assert f"AF3_MODEL_DIR is set to {empty} but that directory is empty" in out, out


def test_nothing_is_checked_when_af3_is_skipped_by_the_user(tmp_path):
    _, out = _run(tmp_path, extra=["--skip-af3"])
    assert "AF3" not in out.replace("--skip-af3", ""), out


def test_a_missing_env_is_reported_as_the_env_not_as_missing_weights(tmp_path):
    _, out = _run(tmp_path, envs=["binder-eval", "binder-eval-esmfold2"])
    assert "[skipped] AF3: conda env 'binder-eval-af3' not found" in out, out
    assert "weights" not in out, out


def test_the_preflight_runs_before_any_engine_or_the_first_conda_step(tmp_path):
    """Ordering is the whole point: it must be decided before any refold starts."""
    src = EVALUATE_SH.read_text()
    call = '_af3_models="$(_af3_weights_dir)"'
    assert src.count(call) == 1
    assert src.index(call) < src.index("[step 0] Parsing sequences")
    assert src.index(call) < src.index('run_engine_checked "Boltz-2"')
