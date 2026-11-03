"""The wizard and the TUI find an env wherever the installer put it.

install.sh finds envs under $CONDA_ENVS_PATH and a condarc `envs_dirs`, but the Python readers
only probed <base>/envs/<name>, so a tool the installer had just finished was "not installed" in
the wizard. Both now ask binderscout_paths.find_env_prefix.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "configurator"))
import configurator as conf  # noqa: E402
from tui.app import _detect_tools  # noqa: E402


def _base(root: Path) -> Path:
    (root / "etc" / "profile.d").mkdir(parents=True)
    (root / "etc" / "profile.d" / "conda.sh").write_text("# conda\n")
    (root / "envs").mkdir()
    return root


def test_the_wizard_finds_an_env_under_conda_envs_path(tmp_path, monkeypatch):
    base = _base(tmp_path / "base")
    (tmp_path / "shared" / "BindCraft").mkdir(parents=True)
    monkeypatch.setattr(conf, "CONDA_ENVS_DIR", base / "envs")
    monkeypatch.setattr(conf, "INSTALL_STATE_DIR", tmp_path / "no_markers")
    monkeypatch.delenv("CONDA_ENVS_PATH", raising=False)
    assert conf.detect_installs()["bindcraft"] is False

    monkeypatch.setenv("CONDA_ENVS_PATH", str(tmp_path / "shared"))
    assert conf.detect_installs()["bindcraft"] is True


def test_the_wizard_finds_an_env_listed_in_a_condarc(tmp_path, monkeypatch):
    base = _base(tmp_path / "base")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".condarc").write_text(f"envs_dirs:\n  - {tmp_path / 'elsewhere'}\n")
    (tmp_path / "elsewhere" / "BoltzGen").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CONDA_ENVS_PATH", raising=False)
    monkeypatch.setattr(conf, "CONDA_ENVS_DIR", base / "envs")
    monkeypatch.setattr(conf, "INSTALL_STATE_DIR", tmp_path / "no_markers")
    assert conf.detect_installs()["boltzgen"] is True


def test_the_wizard_probes_a_package_inside_an_env_outside_the_base(tmp_path, monkeypatch):
    base = _base(tmp_path / "base")
    env = tmp_path / "shared" / "binderscout_protein_hunter"
    (env / "lib" / "python3.10" / "site-packages" / "pyrosetta").mkdir(parents=True)
    ph = tmp_path / "Protein-Hunter"
    ph.mkdir()
    monkeypatch.setenv("CONDA_ENVS_PATH", str(tmp_path / "shared"))
    monkeypatch.setattr(conf, "CONDA_ENVS_DIR", base / "envs")
    monkeypatch.setattr(conf, "PROTEIN_HUNTER_DIR", ph)
    monkeypatch.setattr(conf, "INSTALL_STATE_DIR", tmp_path / "no_markers")
    assert conf.detect_installs()["protein_hunter"] is True


def test_the_tui_finds_an_env_under_conda_envs_path(tmp_path, monkeypatch):
    base = _base(tmp_path / "base")
    (tmp_path / "shared" / "BoltzGen").mkdir(parents=True)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setenv("BINDERSCOUT_CONDA", str(base))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CONDA_ENVS_PATH", raising=False)
    assert _detect_tools(checkout)["BoltzGen"] is False

    monkeypatch.setenv("CONDA_ENVS_PATH", str(tmp_path / "shared"))
    assert _detect_tools(checkout)["BoltzGen"] is True
