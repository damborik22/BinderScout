"""A moved or renamed checkout is BROKEN, not "usable".

BindCraft 2, RFD4-Proteina, Mosaic and Proteina-Complexa are uv venvs inside the checkout, and
binder-compare is an editable install of Evaluator/: all of them record ABSOLUTE paths
(bin/activate, console-script shebangs, direct_url.json). Rename the checkout and every file
still exists and is executable, so `--verify` called the tool usable until its first run died
on a missing interpreter.

--verify now compares the recorded location with the current one and reports BROKEN with the
remedy, and the install steps that used to say "venv already exists -- skipping creation"
discard such a venv so that `--repair` actually repairs it.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, extract_functions, fake_base, run_bash, system_conda_present  # noqa: E402

pytestmark = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be found")


def _sandbox(tmp_path: Path, platform: str):
    """The checkout at its NEW location, and a conda that is found without searching."""
    repo = tmp_path / "new-name"
    (repo / "install").mkdir(parents=True)
    script = repo / "install" / INSTALLERS[platform].name
    shutil.copy(INSTALLERS[platform], script)
    base = fake_base(tmp_path / "conda-base")
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LC_ALL": "C", "BINDERSCOUT_CONDA": str(base)}
    return repo, script, env, base


def _venv(checkout: Path, recorded: Path) -> None:
    """A uv-style venv inside *checkout* whose activate script says it was built at *recorded*."""
    bin_dir = checkout / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("python", "rfd4-generate", "bindcraft"):
        f = bin_dir / name
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)
    (bin_dir / "activate").write_text(f"# uv\nVIRTUAL_ENV='{recorded}/.venv'\nexport VIRTUAL_ENV\n")


def _verify(script: Path, repo: Path, env: dict[str, str], tool: str):
    r = run_bash(f'bash "{script}" --verify --tool {tool} --yes </dev/null', env, repo)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
@pytest.mark.parametrize(
    ("tool", "directory"),
    [
        ("rfd4", "RFD4-Proteina"),
        ("bindcraft2", "BindCraft2"),
        ("mosaic", "Mosaic"),
        ("proteina-complexa", "Proteina-Complexa"),
    ],
)
class TestVenvTools:
    def test_a_moved_checkout_is_broken_with_a_remedy(self, platform, tool, directory, tmp_path):
        repo, script, env, _ = _sandbox(tmp_path, platform)
        _venv(repo / directory, recorded=tmp_path / "old-name" / directory)

        rc, out = _verify(script, repo, env, tool)

        assert rc != 0, out
        assert "BROKEN" in out, out
        assert str(tmp_path / "old-name" / directory) in out, "the report does not say where it was built"
        assert "--repair" in out, "no remedy offered"

    def test_a_venv_at_its_recorded_location_is_not_flagged(self, platform, tool, directory, tmp_path):
        repo, script, env, _ = _sandbox(tmp_path, platform)
        _venv(repo / directory, recorded=repo / directory)

        _, out = _verify(script, repo, env, tool)

        assert "BROKEN" not in out, out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_mosaic_pointer_file_naming_a_vanished_venv_is_broken(platform, tmp_path):
    """evaluate.sh finds Boltz-2 through Evaluator/envs/mosaic_venv_path."""
    repo, script, env, _ = _sandbox(tmp_path, platform)
    _venv(repo / "Mosaic", recorded=repo / "Mosaic")
    (repo / "Evaluator" / "envs").mkdir(parents=True)
    (repo / "Evaluator" / "envs" / "mosaic_venv_path").write_text(str(tmp_path / "old-name" / "Mosaic" / ".venv"))

    rc, out = _verify(script, repo, env, "mosaic")

    assert rc != 0 and "BROKEN" in out and "mosaic_venv_path" in out, out


def _editable_env(base: Path, env_name: str, url: str) -> None:
    dist = base / "envs" / env_name / "lib" / "python3.10" / "site-packages" / "binder_comparison-0.1.0.dist-info"
    dist.mkdir(parents=True)
    (dist / "direct_url.json").write_text(json.dumps({"url": url, "dir_info": {"editable": True}}))


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
@pytest.mark.parametrize(("tool", "env_name"), [("evaluator", "binder-eval"), ("af3", "binder-eval-af3")])
class TestEditableEvaluator:
    def test_binder_compare_installed_from_a_moved_evaluator_is_broken(self, platform, tool, env_name, tmp_path):
        repo, script, env, base = _sandbox(tmp_path, platform)
        _editable_env(base, env_name, f"file://{tmp_path}/old-name/Evaluator")

        rc, out = _verify(script, repo, env, tool)

        assert rc != 0 and "BROKEN" in out, out
        assert f"{tmp_path}/old-name/Evaluator" in out and "--repair" in out, out

    def test_a_percent_encoded_path_with_a_space_matches_itself(self, platform, tool, env_name, tmp_path):
        repo, script, env, base = _sandbox(tmp_path, platform)
        spaced = tmp_path / "with space"
        (spaced / "install").mkdir(parents=True)
        spaced_script = spaced / "install" / script.name
        shutil.copy(script, spaced_script)
        _editable_env(base, env_name, f"file://{spaced}/Evaluator".replace(" ", "%20"))

        _, out = _verify(spaced_script, spaced, env, tool)

        assert "BROKEN" not in out, out


# --- --repair must be able to repair it -------------------------------------


def _discard(script: Path, checkout: Path) -> str:
    prog = "\n".join(
        [
            "set -u",
            extract_functions(script, "_canon_path", "_venv_recorded_path", "_stale_venv_reason", "_discard_relocated_venv"),
            'print_warn() { echo "WARN $*"; }',
            f'_discard_relocated_venv "{checkout}"',
        ]
    )
    return run_bash(prog, {"PATH": "/usr/bin:/bin"}, checkout.parent).stdout


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_relocated_venv_is_discarded_so_the_install_rebuilds_it(platform, tmp_path):
    checkout = tmp_path / "RFD4-Proteina"
    _venv(checkout, recorded=tmp_path / "elsewhere" / "RFD4-Proteina")
    out = _discard(INSTALLERS[platform], checkout)
    assert not (checkout / ".venv").exists(), "the stale venv survived, so --repair would skip rebuilding it"
    assert "rebuilding" in out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_healthy_venv_is_left_alone(platform, tmp_path):
    checkout = tmp_path / "RFD4-Proteina"
    _venv(checkout, recorded=checkout)
    _discard(INSTALLERS[platform], checkout)
    assert (checkout / ".venv" / "bin" / "python").exists()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
@pytest.mark.parametrize(
    ("fn", "dir_var", "skip_marker"),
    [
        ("install_rfd4", "RFD4_DIR", "venv already exists"),
        ("install_bindcraft2", "BINDCRAFT2_DIR", "venv already exists"),
        ("install_mosaic", "MOSAIC_DIR", "Setting up Mosaic venv"),
    ],
)
def test_the_install_steps_discard_a_relocated_venv_before_they_would_skip_it(
    platform, fn, dir_var, skip_marker
):
    body = extract_functions(INSTALLERS[platform], fn)
    call = f'_discard_relocated_venv "${{{dir_var}}}"'
    assert call in body, f"{fn} never discards a relocated venv"
    assert body.index(call) < body.index(skip_marker), f"{fn} discards it only after deciding to reuse it"
