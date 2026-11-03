"""Proteina-Complexa's dm-haiku is pinned, and the pin is proven by importing colabdesign.

dm-haiku 0.0.14+ calls `jax.core.take_current_trace`, which does not exist in the jax
0.4.29 that PC's upstream build pins for colabdesign. From 0.0.14 haiku also declares jax
only as an OPTIONAL extra, so plain `dm-haiku` carries no jax requirement at all: pip and uv
place a new haiku next to the old jax, report a perfectly valid resolution, and the result
cannot import. No constraints file or resolver check catches that -- only running the code
does. So `_pin_complexa_haiku` pins the version and then ASSERTS BY IMPORTING colabdesign (the
path `complexa generate` takes), never by comparing a version string.

The function is exercised against a stub venv whose `python` models the real failure: it can
import colabdesign only while the recorded haiku version is at or below the last good one.
"""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path

import pytest

from tests.shell_helpers import ARM, X86, extract_functions

INSTALLERS = {"x86": X86, "aarch64": ARM}
GOOD = (0, 0, 13)


def _version(path: Path) -> str:
    m = re.search(r'^HAIKU_VERSION="([^"]+)"', path.read_text(), re.M)
    assert m, f"{path.name}: HAIKU_VERSION constant is missing"
    return m.group(1)


def _stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(
    script: Path,
    tmp_path: Path,
    *,
    installed: str = "0.0.17",
    works_up_to: tuple[int, ...] | None = None,
    uv_installs: bool = True,
    uv_rc: int = 0,
    venv: bool = True,
    version: str | None = None,
):
    """Run _pin_complexa_haiku from *script* against a stub venv. Returns (proc, uv_calls)."""
    if works_up_to is None:  # the platform's own pin is, by construction, a version that imports
        works_up_to = tuple(int(x) for x in _version(script).split("."))
    pc = tmp_path / "pc"
    state = tmp_path / "haiku_version"
    state.write_text(installed)
    uvlog = tmp_path / "uv.log"
    uvlog.write_text("")
    if venv:
        # python: `-c ...metadata...` prints the recorded version; `-c "from colabdesign..."`
        # succeeds only while that version is at or below the last good release.
        _stub(
            pc / ".venv" / "bin" / "python",
            f"""
case "$2" in
  *importlib.metadata*) cat "{state}" ;;
  *"from colabdesign.af.model import mk_af_model"*)
    IFS=. read -r a b c < "{state}"
    t=({" ".join(map(str, works_up_to))})
    if [ "$a" -lt "${{t[0]}}" ] || {{ [ "$a" -eq "${{t[0]}}" ] && {{ [ "$b" -lt "${{t[1]}}" ] || {{ [ "$b" -eq "${{t[1]}}" ] && [ "$c" -le "${{t[2]}}" ]; }}; }}; }}; then exit 0; fi
    exit 1 ;;
  *"import jax;print(jax.__version__)"*) echo 0.4.29 ;;
esac
""",
        )
    uv = tmp_path / "bin" / "uv"
    spec_write = f'echo "${{spec#dm-haiku==}}" > "{state}"' if uv_installs else ":"
    _stub(
        uv,
        f"""
echo "$*" >> "{uvlog}"
spec="${{@: -1}}"
[ {uv_rc} -eq 0 ] && {spec_write}
exit {uv_rc}
""",
    )
    fns = extract_functions(script, "_pin_complexa_haiku")
    program = f"""
print_ok()   {{ echo "OK: $*"; }}
print_warn() {{ echo "WARN: $*"; }}
print_fail() {{ echo "FAIL: $*"; }}
print_step() {{ echo "STEP: $*"; }}
run_logged() {{ shift; "$@"; }}
PROTEINA_COMPLEXA_DIR="{pc}"
UV="{uv}"
HAIKU_VERSION="{version or _version(script)}"
{fns}
_pin_complexa_haiku
echo "rc=$?"
"""
    proc = subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=60)
    return proc, uvlog.read_text().splitlines()


@pytest.mark.parametrize("name", INSTALLERS)
def test_a_floating_haiku_is_pinned_and_the_import_then_passes(name, tmp_path):
    script = INSTALLERS[name]
    proc, uv = _run(script, tmp_path)
    out = proc.stdout
    assert "rc=0" in out, out + proc.stderr
    assert len(uv) == 1 and f"dm-haiku=={_version(script)}" in uv[0], uv
    assert "import cleanly" in out, out


@pytest.mark.parametrize("name", INSTALLERS)
def test_an_already_pinned_haiku_is_not_reinstalled(name, tmp_path):
    script = INSTALLERS[name]
    proc, uv = _run(script, tmp_path, installed=_version(script))
    assert "rc=0" in proc.stdout, proc.stdout
    assert uv == [], uv


@pytest.mark.parametrize("name", INSTALLERS)
def test_the_pin_is_asserted_by_importing_colabdesign_not_by_version_string(name, tmp_path):
    """The version matches and the import still fails: the check must say so."""
    script = INSTALLERS[name]
    proc, _ = _run(script, tmp_path, installed=_version(script), works_up_to=(0, 0, 0))
    assert "rc=1" in proc.stdout, proc.stdout
    assert "colabdesign cannot import" in proc.stdout, proc.stdout


@pytest.mark.parametrize("name", INSTALLERS)
def test_a_pin_that_does_not_fix_the_import_fails_loudly(name, tmp_path):
    proc, _ = _run(INSTALLERS[name], tmp_path, uv_installs=False)
    assert "rc=1" in proc.stdout, proc.stdout
    assert "Proteina-Complexa cannot generate" in proc.stdout, proc.stdout


@pytest.mark.parametrize("name", INSTALLERS)
def test_a_failed_pin_install_is_fatal(name, tmp_path):
    proc, _ = _run(INSTALLERS[name], tmp_path, uv_rc=1)
    assert "rc=1" in proc.stdout, proc.stdout
    assert "Could not pin dm-haiku" in proc.stdout, proc.stdout


@pytest.mark.parametrize("name", INSTALLERS)
def test_changing_the_constant_changes_what_is_installed(name, tmp_path):
    """The pin must come from HAIKU_VERSION, not from a literal beside it."""
    _, uv = _run(INSTALLERS[name], tmp_path, version="0.0.12", works_up_to=(0, 0, 12))
    assert len(uv) == 1 and "dm-haiku==0.0.12" in uv[0], uv


@pytest.mark.parametrize("name", INSTALLERS)
def test_no_venv_is_a_skip_not_a_failure(name, tmp_path):
    proc, uv = _run(INSTALLERS[name], tmp_path, venv=False)
    assert "rc=0" in proc.stdout and uv == [], proc.stdout


def test_x86_stays_below_the_jax_core_api_change():
    """x86 keeps upstream's jax 0.4.29, which has no take_current_trace (haiku 0.0.14+ needs it)."""
    major, minor, patch = (int(x) for x in _version(X86).split("."))
    assert (major, minor, patch) <= GOOD, _version(X86)


@pytest.mark.parametrize("name", INSTALLERS)
def test_install_proteina_complexa_calls_the_pin_after_the_jax_it_depends_on(name):
    """Ordering is part of the fix: haiku is pulled in by the upstream build and by jax."""
    src = INSTALLERS[name].read_text()
    body = re.search(r"^install_proteina_complexa\(\) \{\n(.*?)^\}", src, re.S | re.M).group(1)
    assert "_pin_complexa_haiku ||" in body, f"{name}: install_proteina_complexa never calls the haiku pin"
    call = body.index("_pin_complexa_haiku ||")
    anchor = body.index("build_uv_env.sh") if name == "x86" else body.index("jax[cuda12]==0.6.2")
    assert call > anchor


def test_the_two_installers_share_one_body():
    a = extract_functions(X86, "_pin_complexa_haiku")
    b = extract_functions(ARM, "_pin_complexa_haiku")
    assert a == b
