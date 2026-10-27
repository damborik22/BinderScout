"""The documented first command must exist, and the install/report docs must be real.

Three defects, one documentation surface:

* The quick start in both `README.md` and `CLAUDE.md` opened with bare
  `binderscout install`, which is `command not found` (exit 127) on a fresh
  clone — the `binderscout` shortcut is created *by* the installer, so it
  cannot be used to run it. `binderscout.py --help` deliberately short-circuits
  before the shortcut is written, so the documented help does not fix it
  either, and `USAGE` printed the same unusable command back at the reader.
* The `--tool` synopsis and flag table omitted real options (`evaluator`,
  `rfd4`, `tmprot`, `--force`, `--skip-preflight`, `--verify`, `--repair`), so
  the only documented recovery from a half-built environment was undiscoverable.
* The report section named `top20_candidates.csv`, which is never written, and
  documented 3 of the 9 files a report run emits — including omitting
  `top30_slim.csv`, the table a human opens to choose what to order.

Every assertion below reads the *real* source of truth — the installer's own
`case` arms, the report writer's own `output_dir / "…"` expressions, and
`binderscout.py --help` as a subprocess with the shortcut off `PATH` — rather
than a second copy of the list.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CLAUDE = REPO / "CLAUDE.md"
INSTALLER = REPO / "install" / "install.sh"
INSTALLER_AARCH = REPO / "install" / "install_aarch.sh"
REPORT_PY = REPO / "Evaluator" / "binder_comparison" / "cli" / "report.py"
SLIM_PY = REPO / "Evaluator" / "binder_comparison" / "visualization" / "top30_slim.py"


def _section(text: str, heading: str) -> str:
    """The body under `heading`, up to the next heading of the same or higher level.

    Fenced code blocks are skipped when looking for the end: a shell comment like
    `# 1. Clone` is not a Markdown heading, and treating it as one truncated the
    quick-start section to nothing.
    """
    start = text.index(heading)
    level = len(re.match(r"#*", heading.strip()).group(0))
    body: list[str] = []
    in_fence = False
    for line in text[start + len(heading) :].splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(rf"^#{{1,{level}}} ", line):
            break
        body.append(line)
    return "\n".join(body)


# --- BUG-01: the first command a new user types ------------------------------


def _first_install_command(text: str, heading: str) -> str:
    """The first shell line in a quick start that invokes the installer."""
    for line in _section(text, heading).splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "install" not in stripped:
            continue
        if re.match(r"^(\./|python3? |bash |binderscout\b)", stripped):
            return stripped
    raise AssertionError(f"no install command found under {heading!r}")


def test_the_readme_quick_start_opens_with_a_command_that_resolves():
    cmd = _first_install_command(README.read_text(), "\n## Quick start\n")
    assert not cmd.startswith("binderscout "), (
        f"README quick start's first command is {cmd!r}, but `binderscout` is created BY "
        "the installer — on a fresh clone this is command not found (exit 127). "
        "Use ./binderscout.py for the bootstrap command."
    )
    assert "binderscout.py" in cmd or cmd.startswith("bash install/"), cmd


def test_the_claude_md_quick_start_opens_with_a_command_that_resolves():
    cmd = _first_install_command(CLAUDE.read_text(), "\n### Quick start\n")
    assert not cmd.startswith("binderscout "), (
        f"CLAUDE.md quick start's first command is {cmd!r} — same chicken-and-egg as the README's."
    )
    assert "binderscout.py" in cmd or cmd.startswith("bash install/"), cmd


def test_help_advertises_an_invocation_that_exists_when_the_shortcut_does_not():
    """`--help` must not print a command the reader cannot run.

    Run with a PATH that cannot contain the shortcut, which is the fresh-clone
    situation. The usage block must then offer the script, not the shortcut.
    """
    env = dict(os.environ, PATH="/usr/bin:/bin")
    out = subprocess.run(
        [sys.executable, str(REPO / "binderscout.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        check=True,
    ).stdout
    # The usage block is the lines between the "Usage:" and "Commands:" headings
    # (both carry ANSI attributes, hence the substring search rather than a regex).
    usage = out[out.index("Usage:") : out.index("Commands:")]
    assert "./binderscout.py install" in usage, (
        f"with no `binderscout` on PATH the usage block must name ./binderscout.py; it printed:\n{usage}"
    )
    bare = [ln for ln in usage.splitlines() if re.match(r"^\s*binderscout\b", ln)]
    assert not bare, f"usage advertises an unresolvable command: {bare}"


def test_the_shortcut_message_survives_a_non_tty_run(tmp_path):
    """The one line telling the user how to run `binderscout` must reach the log.

    `os.execv()` does not flush Python's buffers, and stdout is block-buffered
    whenever it is not a terminal — so in any piped, logged or CI run the
    shortcut notice was written into a buffer that was then thrown away. The
    shortcut itself appeared on disk with nothing on screen to say so.
    """
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), PATH=f"{home / '.local' / 'bin'}:/usr/bin:/bin")
    proc = subprocess.run(
        [sys.executable, str(REPO / "binderscout.py"), "install", "--help"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
    )
    assert (home / ".local" / "bin" / "binderscout").is_file(), "no shortcut was written at all"
    # Assert the ~/.local/bin line SPECIFICALLY, not the bare substring "Shortcut
    # installed": that phrase is printed by the BinderScout/bin/ copy as well, and
    # bin/ is gitignored, so on CI (where it does not exist) the assertion passed
    # even with this whole fix reverted. Match on the PATH verdict, which only the
    # ~/.local/bin branch prints.
    assert str(home / ".local" / "bin" / "binderscout") in proc.stdout, (
        "nothing named the ~/.local/bin shortcut — this is the copy that makes the bare "
        f"`binderscout` command work. stdout was:\n{proc.stdout[:2000]}"
    )
    assert "you can now run" in proc.stdout, (
        "the shortcut directory IS on PATH in this run, so the message must say the bare "
        f"command now works. stdout was:\n{proc.stdout[:2000]}"
    )
    # The banner naming the selected installer is printed AFTER the shortcut notice
    # and immediately before os.execv. A flush at the top of _dispatch() does not
    # save it; only flushing inside the exec helper does. Without this assertion
    # `binderscout install | tee install.log` silently loses the x86-vs-aarch64
    # diagnostic the banner exists for.
    assert "BinderScout → install" in proc.stdout, (
        f"the pre-exec banner never reached the pipe — execv discarded it. stdout was:\n{proc.stdout[:2000]}"
    )


# --- BUG-03: the install options the README claims ---------------------------


def _installer_tool_names() -> set[str]:
    """The canonical (first) label of each `--tool` case arm in install.sh."""
    block = INSTALLER.read_text().split('case "${2,,}" in', 1)[1].split("esac", 1)[0]
    names = {m.group(1).split("|")[0] for m in re.finditer(r"^\s*([a-z0-9|_-]+)\)", block, re.M)}
    assert len(names) > 10, f"parsed only {names} out of install.sh — did the case block move?"
    return names


def _installer_flags(installer: Path = INSTALLER) -> set[str]:
    """Every long option this installer's top-level parse loop has a case arm for."""
    text = installer.read_text()
    start = text.index("while [[ $# -gt 0 ]]")
    block = text[start:]
    flags = {
        tok
        for m in re.finditer(r"^        (-[-a-z0-9|]+)\)", block, re.M)
        for tok in m.group(1).split("|")
        if tok.startswith("--")
    }
    assert "--tool" in flags and len(flags) > 8, flags
    return flags - {"--help"}


def test_a_documented_flag_is_accepted_by_both_installers():
    """`binderscout install` routes to install_aarch.sh on a DGX Spark.

    So a flag documented with no architecture caveat must have a case arm in BOTH
    files, or the documented command hits install_aarch.sh's catch-all arm
    (`Unknown option: $1` / exit 1) on that platform. This is how `--repair`
    shipped: documented for everyone, implemented only on x86. The README states
    the one real exception (`--tool rfd4` is x86_64-only) in the row itself.
    """
    documented = _readme_install_reference()
    x86 = {f for f in _installer_flags(INSTALLER) if f in documented}
    aarch = _installer_flags(INSTALLER_AARCH)
    missing = sorted(f for f in x86 - aarch if "x86" not in documented.split(f, 1)[1][:400])
    assert not missing, (
        f"documented without an arch caveat but absent from install_aarch.sh's parser: {missing} "
        "— on aarch64 these exit 1"
    )


def _readme_install_reference() -> str:
    """The synopsis block plus the `binderscout install` option table.

    Scoped deliberately: a plain substring search over the whole CLI-reference
    section passes on prose ("extra evaluator tools") and on unrelated tables
    (`screen-tmprot` among the binder-compare subcommands), which would let a
    genuinely undocumented `--tool` name slip through.
    """
    text = README.read_text()
    section = _section(text, "\n## `binderscout` CLI reference\n")
    synopsis = section[
        section.index("binderscout install") : section.index("\n```", section.index("binderscout install"))
    ]
    return synopsis + _section(text, "\n### `binderscout install`\n")


def _readme_documented_tool_names() -> set[str]:
    """Tool names the README offers to `--tool`, from the `--tool a|b|c` runs it prints."""
    names: set[str] = set()
    for run in re.findall(r"--tool\s+([a-z0-9|\\-]+)", _readme_install_reference()):
        names.update(tok for tok in re.split(r"\\?\|", run) if tok)
    return names


def test_every_installer_tool_name_is_documented():
    missing = sorted(_installer_tool_names() - _readme_documented_tool_names())
    assert not missing, (
        f"install.sh accepts `--tool {', '.join(missing)}` but the README's install reference "
        "never offers them, so there is no documented way to ask for them."
    )


def test_the_readme_does_not_offer_a_tool_name_the_installer_rejects():
    accepted = {
        tok
        for m in re.finditer(
            r"^\s*([a-z0-9|_-]+)\)",
            INSTALLER.read_text().split('case "${2,,}" in', 1)[1].split("esac", 1)[0],
            re.M,
        )
        for tok in m.group(1).split("|")
    }
    extra = sorted(_readme_documented_tool_names() - accepted)
    assert not extra, f"README offers `--tool {extra}`, which install.sh exits 1 on."


def test_every_installer_flag_is_documented():
    documented = _readme_install_reference()
    missing = sorted(f for f in _installer_flags() if f not in documented)
    assert not missing, (
        f"install.sh accepts {missing} but the README's install reference does not document them "
        "(--repair and --force are the only recovery paths for a half-built environment)."
    )


# --- BUG-11: the files a report run actually writes --------------------------


def _report_outputs() -> set[str]:
    """Filenames the report writer emits, read off its own `output_dir / "…"` uses."""
    names: set[str] = set()
    for src in (REPORT_PY, SLIM_PY):
        names.update(re.findall(r'output_dir\s*/\s*"([^"]+)"', src.read_text()))
    assert "metrics.csv" in names and len(names) > 5, names
    return names


def test_the_readme_documents_every_file_a_report_run_writes():
    text = README.read_text()
    documented = text[text.index("Report output lands in") : text.index("\n#### `Evaluator/evaluate.sh`")]
    missing = sorted(n for n in _report_outputs() if n not in documented)
    assert not missing, (
        f"a report run writes {missing}, which the README's output table does not list — "
        "undiscoverable without reading cli/report.py."
    )


def test_the_readme_does_not_name_a_report_file_that_is_never_written():
    """`top20_candidates.csv` was documented for long enough to be scripted against."""
    text = README.read_text()
    phantom = sorted(set(re.findall(r"`(top\d+_[a-z0-9_]+\.csv)`", text)) - _report_outputs())
    assert not phantom, (
        f"README names {phantom}, which no report run writes — anyone scripting against it gets a missing file."
    )
