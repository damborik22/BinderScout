"""An alias of the same directory is not a move, and a second checkout is not a broken one.

`_stale_venv_reason` / `_stale_editable_reason` compared `readlink -f` STRINGS. A bind mount or an
automount alias of one directory resolves to a different string, so a working venv was called BROKEN
and `_discard_relocated_venv` would `rm -rf` it (on a plain install, not only --repair). Bind mounts
cannot be created unprivileged, so a `readlink` that does not resolve aliases stands in for them
here, while the two paths are the same directory on disk (a symlink: `-ef` is true).

The second half: a conda editable install recorded at a checkout that STILL EXISTS is not "a moved
checkout" -- it is a second checkout sharing a system conda. Calling it BROKEN sends --repair (or
--repair --stale) off to re-point the shared env at THIS checkout, which breaks the other one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, extract_functions, run_bash, system_conda_present
from tests.test_installer_moved_checkout import _editable_env, _sandbox, _venv, _verify

pytestmark = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be found")


def _blind_readlink(tmp_path: Path) -> str:
    """A PATH whose `readlink -f` prints its argument unchanged: it cannot see through an alias."""
    bin_dir = tmp_path / "blind-bin"
    bin_dir.mkdir()
    fake = bin_dir / "readlink"
    fake.write_text('#!/bin/sh\nfor a; do last="$a"; done\nprintf "%s\\n" "$last"\n')
    fake.chmod(0o755)
    return f"{bin_dir}:/usr/bin:/bin"


def _alias(tmp_path: Path, target: Path) -> Path:
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    return alias


def _stub_python(base: Path, env_name: str) -> None:
    py = base / "envs" / env_name / "bin" / "python"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o755)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_venv_recorded_through_an_alias_of_its_own_directory_is_not_broken(platform, tmp_path):
    repo, script, env, _ = _sandbox(tmp_path, platform)
    _venv(repo / "BindCraft2", recorded=_alias(tmp_path, repo / "BindCraft2"))
    env["PATH"] = _blind_readlink(tmp_path)

    rc, out = _verify(script, repo, env, "bindcraft2")

    assert "BROKEN" not in out, out
    assert rc == 0, out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_working_venv_reached_through_an_alias_is_not_discarded(platform, tmp_path):
    checkout = tmp_path / "RFD4-Proteina"
    _venv(checkout, recorded=_alias(tmp_path, checkout))
    prog = "\n".join(
        [
            "set -u",
            extract_functions(
                INSTALLERS[platform],
                "_canon_path",
                "_venv_recorded_path",
                "_stale_venv_reason",
                "_discard_relocated_venv",
            ),
            'print_warn() { echo "WARN $*"; }',
            f'_discard_relocated_venv "{checkout}"',
        ]
    )

    out = run_bash(prog, {"PATH": _blind_readlink(tmp_path)}, tmp_path).stdout

    assert (checkout / ".venv" / "bin" / "python").exists(), f"a working venv was deleted: {out}"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_an_editable_install_recorded_through_an_alias_is_not_broken(platform, tmp_path):
    repo, script, env, base = _sandbox(tmp_path, platform)
    (repo / "BoltzGen").mkdir()
    _stub_python(base, "BoltzGen")
    _editable_env(base, "BoltzGen", f"file://{_alias(tmp_path, repo)}/BoltzGen", "boltzgen-0.1")
    env["PATH"] = _blind_readlink(tmp_path)

    rc, out = _verify(script, repo, env, "boltzgen")

    assert "BROKEN" not in out, out
    # the alias is THIS checkout, not another one that happens to exist
    assert "owned by another checkout" not in out, out
    assert rc == 0, out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_an_editable_install_owned_by_another_existing_checkout_is_reported_not_broken(platform, tmp_path):
    repo, script, env, base = _sandbox(tmp_path, platform)
    other = tmp_path / "other-checkout" / "BoltzGen"
    other.mkdir(parents=True)
    _stub_python(base, "BoltzGen")
    _editable_env(base, "BoltzGen", f"file://{other}", "boltzgen-0.1")

    rc, out = _verify(script, repo, env, "boltzgen")

    assert "BROKEN" not in out, out
    assert rc == 0, out
    assert "owned by another checkout" in out and str(other) in out, out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_repair_stale_never_re_points_an_env_another_checkout_owns(platform, tmp_path):
    repo, script, env, base = _sandbox(tmp_path, platform)
    other = tmp_path / "other-checkout" / "BoltzGen"
    other.mkdir(parents=True)
    _stub_python(base, "BoltzGen")
    _editable_env(base, "BoltzGen", f"file://{other}", "boltzgen-0.1")
    # a checkout whose HEAD differs from the commit the marker records: the tool is also STALE
    git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True, env={"PATH": "/usr/bin:/bin", "HOME": env["HOME"]})
    subprocess.run(
        [*git, "commit", "-q", "--allow-empty", "-m", "x"],
        cwd=repo,
        check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": env["HOME"]},
    )
    (repo / ".install_state").mkdir()
    (repo / ".install_state" / "boltzgen").write_text("2026-01-01T00:00:00+00:00\tdeadbee\n")

    r = run_bash(f'bash "{script}" --repair --stale --tool boltzgen --yes --skip-preflight </dev/null', env, repo)
    out = r.stdout + r.stderr

    assert r.returncode == 0, out
    assert "Repairing" not in out, out
    assert "Nothing to repair" in out, out
