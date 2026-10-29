"""The "Installed Tools" table must list every tool the installer can install, each read through its own probe.

`print_tool_status` is the table the installer prints on every run, and the one an operator reads to confirm
an engine landed. It is a hand-maintained `for _tool in BindCraft BoltzGen ...` list, and each row string does
three jobs at once: it is lowercased into the marker key (`_key="${_tool,,}"`), spliced into the name of the
probe function that decides "installed" (`_fn="is_${_key}_installed"`), and -- with underscores swapped for
hyphens in install.sh -- printed. Two ways for that list to go wrong, and neither can crash or warn:

* **A row that cannot reach its probe.** Write `Proteina_Complexa` as `Proteina-Complexa` (tempting: install.sh
  prints `${_tool//_/-}` anyway, so the underscores look like a detour) and the probe becomes
  `is_proteina-complexa_installed`, which does not exist. `_tool_is_installed` runs it with stderr discarded,
  so the exit 127 is invisible and the row reads "not installed" for a perfectly good install -- on every
  box, forever. The marker lookup misses as well: `proteina-complexa`, against the file that
  `_install_step proteina_complexa` wrote.

* **A tool with no row.** The list is written once and not extended when a tool is added, and it has been
  short before on both platforms: install.sh named six tools until de5d688 extended it to eleven, and
  install_aarch.sh named five until 26fa144 extended it to nine. Until then RFD3, AF3, ESMFold2 and SoluProt
  -- the DEFAULT refold engine among them -- "never appeared under a heading that claims to list the
  installed tools" (install_aarch.sh's own comment). Both were fixed and nothing pinned the fix.

Nothing ran the table. `test_the_reader_requires_marker_and_probe` greps `print_tool_status`'s body for the
string `_tool_is_installed`, which checks that the RULE is used and never which ROWS it is applied to, and
`TestEveryToolKeyHasAProbe` compares tool keys with install.sh's probes and with the back-fill list, never
with the table.

So the real `print_tool_status` and the reader it calls are extracted from each installer and executed under
bash. Every `is_<key>_installed` that the SAME installer defines becomes a stub that succeeds (install_aarch.sh
has no Proteina-Complexa or Protein-Hunter probe, and its table has no such rows), and the table it prints is
read back. Executed rather than grepped because the defect is in what the shell does with the row, not in
anything that reads as wrong in the source.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALLERS = {
    "install.sh": (REPO / "install" / "install.sh").read_text(encoding="utf-8"),
    "install_aarch.sh": (REPO / "install" / "install_aarch.sh").read_text(encoding="utf-8"),
}
EACH_INSTALLER = pytest.mark.parametrize("name", sorted(INSTALLERS))

# main() hands every tool to `_install_step <canonical key> <install function>`, and the key is the name of the
# marker file written on success: these are, by construction, the tools the installer can install and mark.
_INSTALL_STEP = re.compile(r"\b_install_step\s+([a-z][a-z0-9_]*)\s+install_\w+")
_PROBE = re.compile(r"^(is_[a-z0-9_]+_installed)\(\) \{", re.M)
# One row is `printf "  %b  %-20s  %s\n" <icon> <name> <state>`; the icon is matched as any token.
_ROW = re.compile(r"^\s*\S+\s+(?P<name>\S+)\s+(?P<state>installed|not installed)\s*$")

# print_tool_status and everything it calls that is not a probe.
_FUNCTIONS = ("is_tool_marked", "_any_tool_marked", "_tool_is_installed", "print_tool_status")


def bash_function(text: str, name: str) -> str:
    """Extract `name() { ... }` by its column-zero braces."""
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}$", text, re.S | re.M)
    assert match, f"{name}() not found"
    return match.group(0)


def installable_keys(name: str) -> list[str]:
    keys = _INSTALL_STEP.findall(INSTALLERS[name])
    assert keys, f"{name}: no `_install_step <key> install_<tool>` call found; the discovery pattern has gone stale"
    return keys


def run_status_table(
    name: str,
    tmp_path: Path,
    *,
    markers: bool,
    failing: frozenset[str] = frozenset(),
) -> dict[str, bool]:
    """Run the installer's real print_tool_status; return {tool key: its row reads "installed"}.

    Every probe the installer defines is a stub that succeeds, except those named in *failing*. With *markers*
    each tool `_install_step` can mark has its marker file, as after a full install; without, the store does
    not exist and the probe decides alone (the branch `_tool_is_installed` takes before the first marker).
    """
    text = INSTALLERS[name]
    state = tmp_path / ".install_state"
    if markers:
        state.mkdir()
        for key in installable_keys(name):
            (state / key).write_text("2026-10-28T00:00:00+00:00\tabc1234\n")
    failing_probes = {f"is_{key}_installed" for key in failing}
    script = "\n".join(
        [
            "BOLD='' RESET='' GREEN='' RED=''",  # plain text out; the installers set these to ANSI escapes
            f"INSTALL_STATE_DIR={shlex.quote(str(state))}",
            *(f"{probe}() {{ return {int(probe in failing_probes)}; }}" for probe in _PROBE.findall(text)),
            *(bash_function(text, function) for function in _FUNCTIONS),
            "print_tool_status",
        ]
    )
    harness = tmp_path / "status_table.sh"
    harness.write_text(script, encoding="utf-8")
    proc = subprocess.run(["bash", str(harness)], capture_output=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, f"{name}: print_tool_status failed: {proc.stderr}"

    rows: dict[str, bool] = {}
    for line in proc.stdout.splitlines():
        if not line.strip() or "Installed Tools" in line:
            continue
        match = _ROW.match(line)
        assert match, f"{name}: unrecognised line in the status table: {line!r}\n{proc.stdout}"
        # The table prints "Proteina-Complexa"; `_install_step` names the same tool proteina_complexa.
        rows[match["name"].lower().replace("-", "_")] = match["state"] == "installed"
    assert rows, f"{name}: print_tool_status printed no rows:\n{proc.stdout}"
    return rows


@EACH_INSTALLER
@pytest.mark.parametrize("markers", [False, True], ids=["probe-only", "marker-and-probe"])
def test_every_row_reads_installed_when_its_own_probe_passes(name, markers, tmp_path):
    """Both branches of `_tool_is_installed`: before the first marker exists, and on a fully marked box."""
    rows = run_status_table(name, tmp_path, markers=markers)
    red = sorted(key for key, installed in rows.items() if not installed)
    assert not red, (
        f"{name}: every probe is stubbed to succeed{' and every marker is written' if markers else ''}, yet "
        f"the table reads 'not installed' for {red}. print_tool_status builds the probe name and the marker "
        f"key from the loop row itself (`is_${{_tool,,}}_installed`, `${{_tool,,}}`), so a row spelled any "
        f"way but the underscore key -- Proteina-Complexa for Proteina_Complexa -- names a function and a "
        f"marker file that do not exist. _tool_is_installed discards stderr, so the missing probe is a "
        f"silent exit 127 and a good install reads 'not installed' on every box, with no error and no "
        f"warning."
    )


@EACH_INSTALLER
def test_every_tool_the_installer_can_install_has_a_row(name, tmp_path):
    """A tool added to `--tool`, the menu and `_install_step` but not to the row list never appears at all."""
    rows = run_status_table(name, tmp_path, markers=True)
    missing = sorted(set(installable_keys(name)) - set(rows))
    assert not missing, (
        f"{name}: `_install_step` can install {missing}, but the 'Installed Tools' table has no row for "
        f"{'it' if len(missing) == 1 else 'them'}. The row list is hand-maintained, and this is the bug it "
        f"has had before: 'The old list named five, so RFD3, AF3, ESMFold2 and SoluProt -- including "
        f"the DEFAULT refold engine -- never appeared under a heading that claims to list the installed "
        f"tools.' An operator checking that an engine landed gets silence, not even 'not installed'."
    )


_ONE_PROBE_FAILING = [(name, key) for name in sorted(INSTALLERS) for key in installable_keys(name)]


@pytest.mark.parametrize(
    ("name", "key"),
    _ONE_PROBE_FAILING,
    ids=[f"{name}-{key}" for name, key in _ONE_PROBE_FAILING],
)
def test_a_failing_probe_turns_its_own_row_red_and_no_other(name, key, tmp_path):
    """The other direction: the table has to be able to say 'not installed', and about the right tool."""
    rows = run_status_table(name, tmp_path, markers=True, failing=frozenset({key}))
    red = sorted(row for row, installed in rows.items() if not installed)
    assert red == [key], (
        f"{name}: only the {key} probe fails, so exactly {[key]} should read 'not installed', but the "
        f"table shows {red}. An empty list means {key} has no row or its row never consults the probe, and "
        f"the table reports 'installed' for an engine that is not there; any other name means that row "
        f"reached the wrong probe, or one that does not exist."
    )
