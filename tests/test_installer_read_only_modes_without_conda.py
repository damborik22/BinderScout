"""--verify and --uninstall without conda still handle the tools that need no conda.

With no conda the read-only modes used to refuse outright, so `--verify --tool mosaic` said
"nothing can be verified" about a uv venv that needs no conda to inspect, and `--uninstall
--tool mosaic` left a venv that needs no conda to delete. Mosaic, BindCraft 2, RFD4-Proteina
and Proteina-Complexa are uv venvs; every other tool is a conda env. Without conda the
conda-backed tools are reported per tool (and fail the run), the rest are processed normally.

The old message also said "--verify and --uninstall never download or write anything", which is
false for --uninstall: it never installs conda, which is all it should claim.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, run_bash, system_conda_present
from tests.test_installer_verify_is_read_only import _sandbox, _snapshot

pytestmark = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be found")


def _working_mosaic(repo: Path) -> None:
    bin_dir = repo / "Mosaic" / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text("#!/bin/sh\nexit 0\n")  # every import "succeeds"
    python.chmod(0o755)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_verify_checks_a_conda_free_tool_without_conda(platform, tmp_path):
    repo, script, env, calls = _sandbox(tmp_path, platform)
    _working_mosaic(repo)
    before = _snapshot(tmp_path)

    r = run_bash(f'bash "{script}" --verify --tool mosaic --yes </dev/null', env, repo)
    out = r.stdout + r.stderr

    assert r.returncode == 0, out
    assert "usable" in r.stdout, out
    assert "nothing can be verified" not in out, out
    assert not calls.exists()
    assert _snapshot(tmp_path) == before, f"--verify wrote files: {sorted(_snapshot(tmp_path) - before)}"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_verify_without_conda_fails_only_the_conda_backed_tools(platform, tmp_path):
    repo, script, env, _calls = _sandbox(tmp_path, platform)
    _working_mosaic(repo)

    r = run_bash(f'bash "{script}" --verify --tool mosaic --tool evaluator --yes </dev/null', env, repo)
    out = r.stdout + r.stderr

    assert r.returncode != 0, out
    status, verified = r.stdout.split("Verifying installed tools")
    # the "Installed Tools" table must not call a tool it could not look at "not installed"
    evaluator_status = next(line for line in status.splitlines() if "Evaluator" in line)
    assert "not installed" not in evaluator_status and "not checked" in evaluator_status, evaluator_status
    mosaic = next(line for line in verified.splitlines() if "Mosaic" in line and "usable" in line)
    assert "✓" in mosaic, mosaic
    evaluator = next(line for line in verified.splitlines() if "✗" in line and "Evaluator" in line)
    assert "conda not found" in evaluator, evaluator
    unusable = next(line for line in r.stdout.splitlines() if "Unusable:" in line)
    assert "Evaluator" in unusable and "Mosaic" not in unusable, unusable


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_the_no_conda_message_does_not_claim_uninstall_writes_nothing(platform, tmp_path):
    repo, script, env, _calls = _sandbox(tmp_path, platform)

    r = run_bash(f'bash "{script}" --verify --tool evaluator --yes </dev/null', env, repo)
    out = r.stdout + r.stderr

    assert "conda not found" in out, out
    assert "never download or write anything" not in out, out
    assert "never install" in out, out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_uninstall_removes_a_conda_free_tool_without_conda(platform, tmp_path):
    repo, script, env, calls = _sandbox(tmp_path, platform)
    _working_mosaic(repo)

    r = run_bash(f'bash "{script}" --uninstall --tool mosaic --yes </dev/null', env, repo)
    out = r.stdout + r.stderr

    assert r.returncode == 0, out
    assert not (repo / "Mosaic").exists(), out
    assert not calls.exists(), "--uninstall tried to download something"
    assert not (repo / "conda").exists()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_uninstall_without_conda_fails_the_conda_backed_tool_and_touches_nothing_of_it(platform, tmp_path):
    repo, script, env, _calls = _sandbox(tmp_path, platform)
    _working_mosaic(repo)
    (repo / "BindCraft").mkdir()
    (repo / "BindCraft" / "keep.txt").write_text("a conda env this run could not remove\n")

    r = run_bash(f'bash "{script}" --uninstall --tool mosaic --tool bindcraft --yes </dev/null', env, repo)
    out = r.stdout + r.stderr

    assert r.returncode != 0, out
    assert not (repo / "Mosaic").exists(), "the conda-free tool was not uninstalled"
    assert (repo / "BindCraft" / "keep.txt").exists(), "a half-removed conda-backed tool: its env could not be removed"
    failed = next(line for line in out.splitlines() if "Failed to uninstall" in line)
    assert "BindCraft" in failed and "Mosaic" not in failed, failed
