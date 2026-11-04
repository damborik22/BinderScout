"""An installer run must not append to ~/.bashrc unless a person is at it or asked.

At the end of every full install the shortcuts dir (`<checkout>/bin`) was appended to
`~/.bashrc` unconditionally -- including for `--yes` runs, CI, and a verification clone
installing one tool just to look at it, which then took over the account's PATH for good.

Now the append happens for an interactive install (stdin is a terminal) or behind the
explicit `--add-to-path`; a `--yes` / non-TTY run prints the `export PATH=` line and leaves
the file alone. Driven against the real function text of both installers (they cannot be
sourced whole), with the terminal check stood in for, as the scripts keep it in one function
for that reason.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.shell_helpers import ARM, X86, extract_functions

INSTALLERS = {"x86": X86, "aarch64": ARM}


def _drive(script: Path, tmp_path: Path, *, auto_yes: bool, add_to_path: bool, tty: bool, runs: int = 1):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    shortcuts = tmp_path / "ck" / "bin"
    funcs = extract_functions(script, "_is_interactive", "_persist_path_dir", "_persist_shortcuts_path")
    program = (
        "set -u\n"
        'print_ok() { echo "OK: $*"; }\n'
        'print_warn() { echo "WARN: $*"; }\n'
        f"{funcs}\n"
        f"{'_is_interactive() { return 0; }' if tty else '_is_interactive() { return 1; }'}\n"
        f"AUTO_YES={'true' if auto_yes else 'false'}\n"
        f"ADD_TO_PATH={'true' if add_to_path else 'false'}\n"
        f"SHORTCUTS_DIR='{shortcuts}'\n" + "_persist_shortcuts_path\n" * runs
    )
    proc = subprocess.run(
        ["bash", "-c", program],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    rc = home / ".bashrc"
    return proc, (rc.read_text() if rc.exists() else None), shortcuts


@pytest.mark.parametrize("which", INSTALLERS)
def test_a_yes_run_leaves_bashrc_alone_even_on_a_terminal(which, tmp_path):
    proc, rc, shortcuts = _drive(INSTALLERS[which], tmp_path, auto_yes=True, add_to_path=False, tty=True)
    assert proc.returncode == 0, proc.stderr
    assert "Left ~/.bashrc alone" in proc.stdout, "control: the skip branch was reached"
    assert rc is None, f"--yes appended to ~/.bashrc: {rc!r}"
    assert f'export PATH="{shortcuts}:$PATH"' in proc.stdout, "the export hint must still be printed"


@pytest.mark.parametrize("which", INSTALLERS)
def test_a_non_tty_run_leaves_bashrc_alone(which, tmp_path):
    proc, rc, shortcuts = _drive(INSTALLERS[which], tmp_path, auto_yes=False, add_to_path=False, tty=False)
    assert "Left ~/.bashrc alone" in proc.stdout, "control: the skip branch was reached"
    assert rc is None, f"a non-interactive run appended to ~/.bashrc: {rc!r}"
    assert f'export PATH="{shortcuts}:$PATH"' in proc.stdout


@pytest.mark.parametrize("which", INSTALLERS)
def test_an_interactive_install_still_adds_it_once(which, tmp_path):
    proc, rc, shortcuts = _drive(INSTALLERS[which], tmp_path, auto_yes=False, add_to_path=False, tty=True, runs=2)
    assert proc.returncode == 0, proc.stderr
    assert rc is not None and rc.count(f'export PATH="{shortcuts}:$PATH"') == 1, rc
    assert "Added" in proc.stdout and "already in ~/.bashrc" in proc.stdout, "second run must be idempotent"
    assert f'export PATH="{shortcuts}:$PATH"' in proc.stdout


@pytest.mark.parametrize("which", INSTALLERS)
def test_the_explicit_flag_adds_it_for_a_yes_run(which, tmp_path):
    proc, rc, shortcuts = _drive(INSTALLERS[which], tmp_path, auto_yes=True, add_to_path=True, tty=False)
    assert rc is not None and f'export PATH="{shortcuts}:$PATH"' in rc, proc.stdout


@pytest.mark.parametrize("which", INSTALLERS)
def test_main_goes_through_the_gate_and_no_other_path_appends_the_shortcuts_dir(which):
    """Mutating the CALL SITE: main must call the function, and nothing outside it may write the line."""
    text = INSTALLERS[which].read_text()
    main_body = text.split("\nmain() {\n", 1)[1]
    assert re.search(r"^\s*_persist_shortcuts_path\s*$", main_body, re.M), "main no longer calls the gate"
    assert not re.search(r'>>\s*"\$\{HOME\}/\.bashrc"', main_body.split("\nmain\n")[0]), (
        "main appends to ~/.bashrc directly again"
    )


@pytest.mark.parametrize("which", INSTALLERS)
def test_the_flag_is_parsed_and_documented(which):
    text = INSTALLERS[which].read_text()
    assert re.search(r"--add-to-path\)\n\s+ADD_TO_PATH=true", text), "--add-to-path is not parsed"
    assert "--add-to-path Append the shortcuts dir" in text, "--add-to-path is missing from --help"


@pytest.mark.parametrize("which", INSTALLERS)
def test_the_uv_bootstrap_goes_through_the_same_gate(which):
    """The `uv` bootstrap used to append ~/.local/bin to ~/.bashrc unconditionally, and uv's own
    installer edits shell profiles unless told not to. Nothing but the gate may write ~/.bashrc."""
    text = INSTALLERS[which].read_text()
    curls = re.findall(r"curl -LsSf \"https://astral\.sh/uv/[^\n]*", text)
    assert curls, "control: the uv bootstrap is still there"
    assert all("UV_NO_MODIFY_PATH=1 sh" in c for c in curls), curls
    helper = text.split("_persist_path_dir() {\n", 1)[1].split("\n}\n", 1)[0]
    outside = text.replace(helper, "")
    assert not re.search(r">>\s*\"\$\{HOME\}/\.bashrc\"", outside), "something other than the gate appends to ~/.bashrc"
    assert outside.count('_persist_path_dir "${HOME}/.local/bin"') == len(curls)


@pytest.mark.parametrize("which", INSTALLERS)
def test_the_local_bin_line_is_not_added_twice_to_an_existing_bashrc(which, tmp_path):
    """An account that already has the old `${HOME}/.local/bin` line must not get a second one."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text('export PATH="${HOME}/.local/bin:${PATH}"\n')
    funcs = extract_functions(INSTALLERS[which], "_is_interactive", "_persist_path_dir")
    program = (
        'print_ok() { echo "OK: $*"; }\nprint_warn() { echo "WARN: $*"; }\n'
        f"{funcs}\n_is_interactive() {{ return 0; }}\nAUTO_YES=false\nADD_TO_PATH=true\n"
        "_persist_path_dir \"${HOME}/.local/bin\" '.local/bin'\n"
    )
    proc = subprocess.run(
        ["bash", "-c", program],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (home / ".bashrc").read_text().count(".local/bin") == 1
