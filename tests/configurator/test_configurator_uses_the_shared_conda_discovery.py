"""The configurator asks binderscout_paths.find_conda_base; it keeps no search of its own.

It carried a private `conda info --base` / fixed-location search whose candidate
list differed from the CLI's and the TUI's. A box with conda reachable only through
CONDA_EXE (nothing on PATH, no checkout-local conda) was "conda found" to one and
"conda not found" to another, and the generated run scripts then carried an empty
conda base.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "configurator"))
import configurator as conf  # noqa: E402


def _fake_base(root: Path) -> Path:
    (root / "etc" / "profile.d").mkdir(parents=True)
    (root / "etc" / "profile.d" / "conda.sh").write_text("# conda\n")
    (root / "bin").mkdir()
    (root / "bin" / "conda").write_text("#!/bin/sh\n")
    return root


def test_a_conda_reachable_only_through_conda_exe_is_found(tmp_path, monkeypatch):
    base = _fake_base(tmp_path / "somewhere" / "odd")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(conf, "BINDERSCOUT_DIR", checkout)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "")
    for var in ("BINDERSCOUT_CONDA", "CONDA_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CONDA_EXE", str(base / "bin" / "conda"))
    assert conf._find_conda_base() == base


def test_the_checkouts_own_conda_still_wins(tmp_path, monkeypatch):
    local = _fake_base(tmp_path / "checkout" / "conda")
    other = _fake_base(tmp_path / "odd")
    monkeypatch.setattr(conf, "BINDERSCOUT_DIR", tmp_path / "checkout")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("BINDERSCOUT_CONDA", raising=False)
    monkeypatch.setenv("CONDA_EXE", str(other / "bin" / "conda"))
    assert conf._find_conda_base() == local


def test_the_configurator_keeps_no_private_conda_search():
    src = (REPO / "configurator" / "configurator.py").read_text()
    assert '"info", "--base"' not in src
    assert "find_conda_base" in src
