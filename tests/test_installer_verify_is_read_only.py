"""`--verify` installs nothing: not even a conda.

`main` called `detect_conda || exit 1` before it looked at --verify, and detect_conda's last
resort is to download an ~80 MB Miniforge and install it into the checkout. So on a box with
no conda, the documented read-only audit fetched and installed a package manager first (and
failed after the download if the path was unsuitable). It also appended to install.log.

"conda not found" is a verification RESULT. These run the real installers against a sandbox
checkout whose PATH holds a `curl` that records every call, and assert nothing was fetched,
nothing was created, and the exit status is nonzero.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, fake_base, run_bash, system_conda_present

pytestmark = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be found")


def _sandbox(tmp_path: Path, platform: str) -> tuple[Path, Path, dict[str, str], Path]:
    """A copy of the installer in an otherwise empty checkout, and an environment with no conda."""
    repo = tmp_path / "checkout"
    (repo / "install").mkdir(parents=True)
    script = repo / "install" / INSTALLERS[platform].name
    shutil.copy(INSTALLERS[platform], script)

    calls = tmp_path / "network-calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("curl", "wget"):
        fake = bin_dir / name
        # Records the call, and "downloads" an installer that fails at once (no retry sleeps).
        fake.write_text(
            f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n'
            'while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n'
            '[ -n "$out" ] && printf "#!/bin/sh\\nexit 1\\n" > "$out"\nexit 0\n'
        )
        fake.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "LC_ALL": "C"}
    return repo, script, env, calls


def _snapshot(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
@pytest.mark.parametrize("args", [["--verify", "--tool", "all", "--yes"], ["--verify", "--tool", "evaluator", "--yes"]])
def test_verify_without_conda_reports_it_and_fetches_nothing(platform, args, tmp_path):
    repo, script, env, calls = _sandbox(tmp_path, platform)
    before = _snapshot(tmp_path)

    r = run_bash(f'bash "{script}" ' + " ".join(args) + " </dev/null", env, repo)
    out = r.stdout + r.stderr

    assert r.returncode != 0, out
    assert "conda not found" in out, out
    assert not calls.exists(), f"--verify tried to download something: {calls.read_text()}"
    assert not (repo / "conda").exists(), "--verify created a standalone conda directory"
    assert _snapshot(tmp_path) == before, f"--verify wrote files: {sorted(_snapshot(tmp_path) - before)}"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_uninstall_without_conda_does_not_provision_one_either(platform, tmp_path):
    repo, script, env, calls = _sandbox(tmp_path, platform)

    r = run_bash(f'bash "{script}" --uninstall --tool bindcraft --yes </dev/null', env, repo)
    out = r.stdout + r.stderr

    assert r.returncode != 0, out
    assert "conda not found" in out, out
    assert not calls.exists(), f"--uninstall tried to download something: {calls.read_text()}"
    assert not (repo / "conda").exists()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_real_install_still_provisions_conda_when_there_is_none(platform, tmp_path):
    """The guard is for the read-only modes only: a plain install must still bootstrap."""
    repo, script, env, calls = _sandbox(tmp_path, platform)

    run_bash(f'bash "{script}" --tool evaluator --yes --skip-preflight </dev/null', env, repo)

    assert calls.exists() and "Miniforge3" in calls.read_text(), "an install no longer tries to fetch Miniforge"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_verify_with_a_conda_present_creates_nothing_either(platform, tmp_path):
    """No envs/ directory (the writability probe mkdir's one) and no install.log."""
    repo, script, env, calls = _sandbox(tmp_path, platform)
    base = fake_base(tmp_path / "conda-base")
    env["BINDERSCOUT_CONDA"] = str(base)
    before = _snapshot(tmp_path)

    r = run_bash(f'bash "{script}" --verify --tool evaluator --yes </dev/null', env, repo)

    assert "conda not found" not in r.stdout + r.stderr
    assert not calls.exists()
    assert _snapshot(tmp_path) == before, f"--verify wrote files: {sorted(_snapshot(tmp_path) - before)}"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_verify_that_finds_a_working_tool_still_writes_nothing(platform, tmp_path):
    """A passing probe must not leave a marker behind (.install_state/) or any other file.

    The empty-checkout cases above never get a tool to verify as usable, so a marker write on the
    success path would go unseen.
    """
    repo, script, env, _calls = _sandbox(tmp_path, platform)
    env["BINDERSCOUT_CONDA"] = str(fake_base(tmp_path / "conda-base"))
    bin_dir = repo / "Mosaic" / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text("#!/bin/sh\nexit 0\n")  # every import "succeeds"
    python.chmod(0o755)
    before = _snapshot(tmp_path)

    r = run_bash(f'bash "{script}" --verify --tool mosaic --yes </dev/null', env, repo)

    assert r.returncode == 0, r.stdout + r.stderr  # it really did verify as usable
    assert "usable" in r.stdout
    assert not (repo / ".install_state").exists()
    assert _snapshot(tmp_path) == before, f"--verify wrote files: {sorted(_snapshot(tmp_path) - before)}"
