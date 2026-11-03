"""The rc-foundry pin is ONE constant, and the install actually uses it.

install.sh carried `FOUNDRY_COMMIT="v0.1.9"` for the log line while pip installed a
hardcoded `rc-foundry[rfd3]==0.1.9` and `rc-foundry[mpnn]==0.1.9`. Bumping the constant
changed the message and not the install, so the pin looked load-bearing and was not.
install_aarch.sh already had the right shape (`FOUNDRY_VERSION`, used in both specs); this
holds both installers to it by RUNNING install_rfd3 against a recording stub and reading the
specs pip is handed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.shell_helpers import ARM, X86, extract_functions

INSTALLERS = {"x86": X86, "aarch64": ARM}


def _constant(script: Path) -> str:
    m = re.search(r'^FOUNDRY_VERSION="([^"]+)"', script.read_text(), re.M)
    assert m, f"{script.name}: FOUNDRY_VERSION constant is missing"
    return m.group(1)


def _foundry_specs(script: Path, tmp_path: Path, *, override: str | None = None) -> list[str]:
    """Run install_rfd3 with every side effect stubbed; return the rc-foundry specs it hands pip."""
    log = tmp_path / "calls.log"
    log.write_text("")
    program = f"""
print_step() {{ :; }}; print_ok() {{ :; }}; print_warn() {{ :; }}; print_fail() {{ echo "FAIL: $*" >&2; }}
_refuse_if_env_in_use() {{ return 0; }}; ensure_conda_in_path() {{ :; }}; env_exists() {{ return 0; }}
_pin_rfd3_atomworks() {{ return 0; }}; smoke_test() {{ return 0; }}; _write_rfd3_shortcut() {{ :; }}
run_logged() {{ printf '%s\\n' "$*" >> "{log}"; return 0; }}
CONDA_CMD=conda; RFD3_ENV=rfd3env; FOUNDRY_WEIGHTS_DIR="{tmp_path}/weights"
FOUNDRY_VERSION="{_constant(script)}"
{extract_functions(script, "install_rfd3")}
{f'FOUNDRY_VERSION="{override}"' if override else ""}
install_rfd3
echo "rc=$?"
"""
    proc = subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=60)
    assert "rc=0" in proc.stdout, proc.stdout + proc.stderr
    # Only what pip is handed -- the run_logged LABEL may repeat the spec and is not an install.
    return re.findall(r"pip install -q (rc-foundry\[[a-z0-9,]+\]==\S+)", log.read_text())


@pytest.mark.parametrize("name", INSTALLERS)
def test_both_extras_are_installed_at_the_constants_version(name, tmp_path):
    script = INSTALLERS[name]
    specs = _foundry_specs(script, tmp_path)
    v = _constant(script)
    assert sorted(specs) == sorted([f"rc-foundry[rfd3]=={v}", f"rc-foundry[mpnn]=={v}"]), specs


@pytest.mark.parametrize("name", INSTALLERS)
def test_changing_the_constant_changes_the_spec(name, tmp_path):
    """The whole point: a bump must reach pip, not just the log line."""
    specs = _foundry_specs(INSTALLERS[name], tmp_path, override="9.9.9")
    assert sorted(specs) == ["rc-foundry[mpnn]==9.9.9", "rc-foundry[rfd3]==9.9.9"], specs


@pytest.mark.parametrize("name", INSTALLERS)
def test_no_rc_foundry_version_is_hardcoded_anywhere(name):
    """A literal beside the constant is exactly how the pin stopped being load-bearing."""
    src = INSTALLERS[name].read_text()
    literals = re.findall(r"rc-foundry\[[^\]]*\]==[0-9][^\s\"']*", src)
    assert not literals, f"{name}: hardcoded rc-foundry pin(s) {literals}; use ${{FOUNDRY_VERSION}}"


def test_both_installers_pin_the_same_release():
    assert _constant(X86) == _constant(ARM)


@pytest.mark.parametrize("name", INSTALLERS)
def test_the_log_label_names_the_version_that_is_installed(name, tmp_path):
    """The label printed to the operator and the spec given to pip come from the same variable."""
    src = INSTALLERS[name].read_text()
    assert "FOUNDRY_COMMIT" not in src, "the old log-only constant is back"
    assert "Installing rc-foundry[rfd3]==${FOUNDRY_VERSION}" in src
