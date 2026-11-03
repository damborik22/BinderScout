"""A "NOTE: owned by another checkout" result must not mask a BROKEN one.

`_relocation_reason` ran its second check (the Mosaic pointer for the evaluator, the tmprot-1.0
editable for tmprot) only when the first came back empty. The foreign-checkout NOTE is non-empty,
so the second check was skipped and a vanished `mosaic_venv_path` target, or a tmprot-1.0 editable
at a deleted path, was reported usable. A BROKEN result now replaces the NOTE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, run_bash, system_conda_present
from tests.test_installer_moved_checkout import _editable_env, _sandbox, _venv

pytestmark = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be found")


def _stub_env_tools(base: Path, env_name: str) -> None:
    """A python and a binder-compare that succeed, so only the relocation check can object."""
    bin_dir = base / "envs" / env_name / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("python", "binder-compare"):
        f = bin_dir / name
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)


def _verify(script: Path, repo: Path, env: dict[str, str], tool: str):
    r = run_bash(f'bash "{script}" --verify --tool {tool} --yes </dev/null', env, repo)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_stale_mosaic_pointer_is_broken_even_when_the_env_is_owned_by_another_checkout(platform, tmp_path):
    repo, script, env, base = _sandbox(tmp_path, platform)
    other = tmp_path / "other-checkout"
    (other / "Evaluator").mkdir(parents=True)
    _editable_env(base, "binder-eval", f"file://{other}/Evaluator")
    _stub_env_tools(base, "binder-eval")
    _venv(repo / "Mosaic", recorded=repo / "Mosaic")
    (repo / "Evaluator" / "envs").mkdir(parents=True)
    (repo / "Evaluator" / "envs" / "mosaic_venv_path").write_text(str(tmp_path / "vanished" / "Mosaic" / ".venv"))

    rc, out = _verify(script, repo, env, "evaluator")

    assert rc != 0, out
    assert "BROKEN" in out and "mosaic_venv_path" in out, out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_deleted_tmprot_editable_is_broken_even_when_evaluator_is_owned_by_another_checkout(platform, tmp_path):
    repo, script, env, base = _sandbox(tmp_path, platform)
    other = tmp_path / "other-checkout"
    (other / "Evaluator").mkdir(parents=True)
    _editable_env(base, "binder-eval-tmprot", f"file://{other}/Evaluator")
    _editable_env(base, "binder-eval-tmprot", f"file://{tmp_path}/deleted/TmProt/tmprot-1.0", "tmprot-1.0")
    _stub_env_tools(base, "binder-eval-tmprot")

    rc, out = _verify(script, repo, env, "tmprot")

    assert rc != 0, out
    assert "BROKEN" in out and f"{tmp_path}/deleted/TmProt/tmprot-1.0" in out, out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_the_foreign_note_alone_is_still_only_a_note(platform, tmp_path):
    """The fix must not turn a foreign-owned env into a failure when nothing else is wrong."""
    repo, script, env, base = _sandbox(tmp_path, platform)
    other = tmp_path / "other-checkout"
    (other / "Evaluator").mkdir(parents=True)
    _editable_env(base, "binder-eval", f"file://{other}/Evaluator")
    _stub_env_tools(base, "binder-eval")

    _, out = _verify(script, repo, env, "evaluator")

    assert "BROKEN" not in out, out
    assert "another checkout" in out, out
