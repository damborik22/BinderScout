"""AF3 writes its confidence scores at full precision, and the installers keep it that way.

Upstream AF3 rounds iPTM, pTM and ranking_score to TWO decimals. On the 563-design benchmark
that gave AF3 81 distinct iPTM values against 563 for every other engine, which understates it
in every rank-based metric. The fix edits the INSTALLED package, so it is lost on reinstall and
must be re-applied by the installers; and it must run as a script FILE, because `conda run`
does not forward stdin and a heredoc-fed patch executes nothing while exiting 0 (which is how
the PXDesign patches were skipped for months).

These tests run the real script against a synthetic ``alphafold3`` package, so no AF3, GPU or
conda environment is needed.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "install" / "patches" / "af3_full_precision.py"
INSTALLERS = (REPO / "install" / "install.sh", REPO / "install" / "install_aarch.sh")

# What the x86 / current upstream build looks like around the two rounding sites.
CURRENT = """\
def convert(data):
  if isinstance(data, np.ndarray):
    rounded_data = np.round(data.astype(np.float64), decimals=2).tolist()
  elif isinstance(data, str):
    rounded_data = data
  else:
    rounded_data = np.round(data, decimals=2)
  return rounded_data
"""
# The older v3.0.2 build that BM5 carried also rounded the PAE matrix to ONE decimal.
WITH_PAE = (
    CURRENT
    + """\
pae = np.round(
    np.clip(np.asarray(o.pae, dtype=np.float64), 0.0, 99.9), 1
).astype(float)
"""
)


def _run(pkg_root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(pkg_root)}
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True)


def _package(tmp_path: Path, source: str) -> Path:
    model = tmp_path / "alphafold3" / "model"
    model.mkdir(parents=True)
    (tmp_path / "alphafold3" / "__init__.py").write_text("")
    target = model / "confidence_types.py"
    target.write_text(source)
    return target


def test_check_reports_an_unpatched_package(tmp_path):
    _package(tmp_path, CURRENT)
    assert _run(tmp_path, "--check").returncode == 1


def test_apply_writes_full_precision_and_check_then_passes(tmp_path):
    target = _package(tmp_path, CURRENT)
    done = _run(tmp_path)
    assert done.returncode == 0, done.stderr
    text = target.read_text()
    assert text.count("decimals=6") == 2 and "decimals=2" not in text
    assert _run(tmp_path, "--check").returncode == 0


def test_apply_is_idempotent_and_keeps_the_original(tmp_path):
    target = _package(tmp_path, CURRENT)
    assert _run(tmp_path).returncode == 0
    once = target.read_text()
    assert _run(tmp_path).returncode == 0
    assert target.read_text() == once
    assert (target.parent / "confidence_types.py.orig").read_text() == CURRENT, (
        "the backup must hold the pristine upstream file, not a patched one"
    )


def test_the_older_build_with_rounded_pae_is_patched_too(tmp_path):
    target = _package(tmp_path, WITH_PAE)
    assert _run(tmp_path).returncode == 0
    assert "99.9), 3" in target.read_text()


def test_source_the_patch_does_not_recognise_fails_loudly_and_is_left_alone(tmp_path):
    """If upstream rewrites the rounding, reporting success would be the silent no-op again."""
    target = _package(tmp_path, "x = 1\n")
    done = _run(tmp_path)
    assert done.returncode != 0
    assert target.read_text() == "x = 1\n"
    assert _run(tmp_path, "--check").returncode == 1


def test_a_missing_package_fails(tmp_path):
    assert _run(tmp_path).returncode != 0


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_installer_applies_the_patch_as_a_script_file_not_a_heredoc(installer):
    text = installer.read_text()
    call = re.search(r'python "\$\{BINDERSCOUT_DIR\}/install/patches/af3_full_precision\.py"', text)
    assert call, f"{installer.name} does not run install/patches/af3_full_precision.py"
    # The script must be an argument to python. Feeding python a heredoc under conda run runs nothing.
    window = text[call.start() : call.start() + 400]
    assert "<<" not in window, f"{installer.name} feeds the AF3 patch to python via a heredoc"
    assert "return 1" in window, f"{installer.name} ignores a failed AF3 precision patch"


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_the_patch_runs_after_the_package_is_built_so_a_reinstall_cannot_undo_it(installer):
    text = installer.read_text()
    build = text.index("Building + installing AlphaFold 3 from source")
    patch = text.index("af3_full_precision.py", build)
    assert patch > build


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_verify_detects_a_lost_patch(installer):
    text = installer.read_text()
    assert "_af3_full_precision()" in text
    arm = text[text.index("        af3)\n", text.index("verify_tool()")) :][:1400]
    assert "_af3_full_precision" in arm, f"{installer.name}: --verify cannot see a missing AF3 precision patch"
