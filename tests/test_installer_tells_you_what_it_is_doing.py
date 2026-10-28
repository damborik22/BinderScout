"""The installer's two silences: no progress for 90 minutes, and no toolchain check.

BUG-07  The installer prints "full output in install.log" before a 45-90 min step
        and then does not keep that promise: run_logged() buffered the child's
        output into a temp file and flushed it only once the step had FINISHED.
        Verified live during a real install: 5+ minutes into the BindCraft step
        install.log had not grown and its tail was still the pre-step banner, while
        pip was demonstrably running. There is no other log file.

        The only live feedback was a spinner on /dev/tty, so under `nohup`,
        `ssh host 'install ...'`, tmux send-keys, CI, or any redirect -- i.e. how a
        scientist actually runs a 90-minute job on a shared workstation -- there was
        no output whatsoever for an hour and a half.

        Major rather than cosmetic because of what it makes people do: the rational
        response to "no output for 40 minutes and the log I was told to watch is
        empty" is Ctrl-C, which leaves a half-built conda env -- and a half-built
        env is the input to the next bug.

BUG-08  `--tool all` ran for ~57 minutes, installed nine tools, reached step 10/10,
        and then reported that SoluProt could not build USEARCH v12 because `make`
        is missing. Preflight checked disk, GPU and network and all three passed.
        A stock Ubuntu Server image has no `make`, so this is the common case, and
        everything needed to detect it is three `command -v` calls against a tool
        selection preflight already knows.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALLERS = [REPO / "install" / "install.sh", REPO / "install" / "install_aarch.sh"]
IDS = [p.name for p in INSTALLERS]


def _function(path: Path, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}\n", path.read_text(), re.S | re.M)
    assert m, f"{path.name} does not define {name}()"
    return m.group(1)


# ─────────────────────────────────────────────────── BUG-07: the log must stream


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_run_logged_writes_to_the_log_not_a_temp_file(path):
    """Asserted on the redirect, because that IS the bug.

    The old body did `"$@" >> "${tmpfile}"` and then `cat "${tmpfile}" >>
    "${LOG_FILE}"` after `wait`, so `tail -f install.log` showed nothing until the
    step was over -- which for BindCraft is 45-90 minutes.
    """
    body = _function(path, "run_logged")
    assert '"$@" >> "${LOG_FILE}" 2>&1 &' in body, "the child's output must go straight to the log"
    assert "mktemp" not in body, "a temp file reintroduces the buffering"
    assert "tmpfile" not in body


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_run_logged_speaks_up_without_a_tty(path):
    """The spinner is a /dev/tty write; a redirected run got nothing at all."""
    body = _function(path, "run_logged")
    assert "still running:" in body, "a non-TTY run needs a heartbeat, not silence"
    # In the else-branch of the has_tty test, not somewhere unreachable.
    tty_split = body.index('if [[ "${has_tty}" == true ]]')
    assert "still running:" in body[tty_split:], "the heartbeat must be the non-TTY branch"


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_the_failure_tail_is_scoped_to_this_step(path):
    """Streaming into one cumulative log means the tail has to know where the step
    began, or a failing step reports the previous step's output."""
    body = _function(path, "run_logged")
    assert "start_line" in body
    assert 'tail -n +"${start_line}" "${LOG_FILE}"' in body


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_the_banner_names_a_command_that_works(path):
    """ "full output in install.log" was advice that did nothing while it was given.

    Name the command instead -- it is the one the user would otherwise have to
    guess, and `tail -f` is only honest now that the log streams.
    """
    text = path.read_text()
    for m in re.finditer(r'print_warn "This (?:will take|takes)[^"]*"', text):
        assert "tail -f" in m.group(0), f"{path.name}: {m.group(0)} does not say how to follow it"


class TestRunLoggedBehaviour:
    """Execute the real function rather than reading it.

    run_logged is extracted and run against stub print_* helpers, with stdin and
    stdout redirected so `has_tty` is false -- the configuration the bug was about.
    """

    def _harness(self, tmp_path, path: Path, script: str, heartbeat_after: int | None = None) -> str:
        body = f"run_logged() {{\n{_function(path, 'run_logged')}}}\n"
        if heartbeat_after is not None:
            # The shipped threshold is 120 s, which no test should wait for. The
            # constant itself is asserted separately below.
            body = body.replace("waited >= 120", f"waited >= {heartbeat_after}")
        harness = tmp_path / "harness.sh"
        harness.write_text(
            textwrap.dedent("""\
                #!/usr/bin/env bash
                set -uo pipefail
                RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; RESET=''
                ARCH="$(uname -m)"
                LOG_FILE="$1"; shift
                print_ok()   { echo "OK   $*"; }
                print_warn() { echo "WARN $*"; }
                print_fail() { echo "FAIL $*"; }
                """)
            + body
            + script
        )
        harness.chmod(0o755)
        log = tmp_path / "install.log"
        log.write_text("")
        proc = subprocess.run(
            ["bash", str(harness), str(log)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.log_text = log.read_text()
        self.returncode = proc.returncode
        return proc.stdout + proc.stderr

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_the_log_grows_while_the_step_is_still_running(self, tmp_path, path):
        """The claim the banner makes, measured.

        A child that prints four lines over four seconds, with the log sampled at
        ~2 s: the old body left it empty until the child exited.
        """
        script = textwrap.dedent("""\
            run_logged "slow step" bash -c 'for i in 1 2 3 4; do echo "chunk $i"; sleep 1; done' &
            RL=$!
            sleep 2
            echo "MIDWAY_LINES=$(wc -l < "${LOG_FILE}")"
            wait $RL
            """)
        out = self._harness(tmp_path, path, script)
        midway = int(re.search(r"MIDWAY_LINES=(\d+)", out).group(1))
        assert midway >= 1, f"the log was still empty mid-step (got {midway} lines)\n{out}"
        assert "chunk 4" in self.log_text, "and the whole step must still land in the log"

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_redirected_run_reports_that_it_is_alive(self, tmp_path, path):
        script = 'run_logged "slow step" sleep 3\n'
        out = self._harness(tmp_path, path, script, heartbeat_after=1)
        assert "still running: slow step" in out, f"no heartbeat without a TTY:\n{out}"

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_short_step_returns_promptly_and_says_nothing(self, tmp_path, path):
        """The heartbeat must not cost a one-second command two minutes of polling."""
        script = 'run_logged "quick step" true\n'
        out = self._harness(tmp_path, path, script)
        assert "OK   quick step" in out
        assert "still running" not in out

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_failing_step_shows_its_own_output_not_the_previous_step_s(self, tmp_path, path):
        script = textwrap.dedent("""\
            run_logged "earlier step" bash -c 'echo EARLIER_STEP_MARKER'
            run_logged "failing step" bash -c 'echo this-step-line; exit 7'
            echo "RC=$?"
            """)
        out = self._harness(tmp_path, path, script)
        assert "RC=7" in out, "the exit code must be propagated"
        assert "this-step-line" in out
        assert "EARLIER_STEP_MARKER" not in out, "the tail leaked the previous step's output"
        # Both steps are still in the cumulative log -- that is the point of dropping
        # the temp file, not a side effect to be undone.
        assert "EARLIER_STEP_MARKER" in self.log_text

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_retries_accumulate_in_the_log(self, tmp_path, path):
        """The old body truncated the temp file on each attempt, so a step that
        succeeded on attempt 3 left no trace of why 1 and 2 failed."""
        marker = tmp_path / "attempts"
        script = (
            f'run_logged --retries 3 "flaky step" bash -c \'echo "attempt-output"; '
            f"n=$(cat {marker} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {marker}; "
            f"[ $n -ge 2 ]'\n"
        )
        out = self._harness(tmp_path, path, script)
        assert "OK   flaky step" in out
        assert self.log_text.count("attempt-output") == 2, (
            f"both attempts must be in the log, found {self.log_text.count('attempt-output')}"
        )

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_the_shipped_heartbeat_interval_is_two_minutes(self, path):
        """Asserted because every behavioural test above overrides it."""
        assert "waited >= 120" in _function(path, "run_logged")


# ───────────────────────────────────────── BUG-08: fail in seconds, not in an hour


def _toolchain_table(path: Path) -> dict[str, str]:
    """The TOOLCHAIN_TOOLS array as {DO_ flag: why}."""
    text = path.read_text()
    m = re.search(r"^TOOLCHAIN_TOOLS=\(\n(.*?)^\)\n", text, re.S | re.M)
    assert m, f"{path.name} has no TOOLCHAIN_TOOLS table"
    out = {}
    for line in m.group(1).splitlines():
        line = line.strip().strip('"')
        if not line or line.startswith("#"):
            continue
        flag, _label, why = line.split("|", 2)
        out[flag] = why
    return out


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_every_flag_in_the_table_is_a_real_flag(path):
    """A typo'd DO_ name would make the entry silently never fire -- the same shape
    as the bug, one level up."""
    text = path.read_text()
    for flag in _toolchain_table(path):
        assert re.search(rf"^{re.escape(flag)}=", text, re.M), f"{path.name}: {flag} is not a DO_* flag it defines"


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_soluprot_is_in_the_table(path):
    """It is the one in `--tool all`, so it is the one that cost an hour -- and it
    source-builds USEARCH v12 on BOTH platforms."""
    assert "DO_SOLUPROT" in _toolchain_table(path)


def test_aarch64_lists_the_two_tools_that_only_compile_there():
    """gemmi 0.6.5 has no aarch64 wheel and builds from its sdist (Protein-Hunter);
    biotraj has none either and compiles (BindCraft 2). Both are wheels on x86, which
    is why this table is per-installer rather than shared."""
    arm = _toolchain_table(REPO / "install" / "install_aarch.sh")
    x86 = _toolchain_table(REPO / "install" / "install.sh")
    assert "DO_PROTEIN_HUNTER" in arm and "DO_PROTEIN_HUNTER" not in x86
    assert "DO_BINDCRAFT2" in arm and "DO_BINDCRAFT2" not in x86


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_preflight_calls_the_toolchain_check(path):
    """Checking it in preflight is the whole fix: the diagnostics at the build site
    were already good, and purely too late."""
    body = _function(path, "preflight")
    assert "check_build_toolchain" in body, "the check must run in preflight, not at build time"


class TestToolchainCheckBehaviour:
    """Run check_build_toolchain with a controlled PATH."""

    def _run(
        self,
        tmp_path,
        path: Path,
        flags: dict[str, bool],
        have: tuple[str, ...],
        arch: str | None = None,
    ) -> tuple[int, str]:
        fakebin = tmp_path / "bin"
        fakebin.mkdir(exist_ok=True)
        for name in have:
            target = fakebin / name
            target.write_text("#!/bin/sh\nexit 0\n")
            target.chmod(0o755)

        table = _toolchain_table(path)
        decls = "\n".join(f"{flag}={str(flags.get(flag, False)).lower()}" for flag in table)
        body = _function(path, "check_build_toolchain")
        src = re.search(r"^TOOLCHAIN_TOOLS=\(\n.*?^\)\n", path.read_text(), re.S | re.M).group(0)

        harness = tmp_path / "tc.sh"
        harness.write_text(
            textwrap.dedent("""\
                #!/usr/bin/env bash
                set -uo pipefail
                RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; RESET=''
                ARCH="__ARCH__"   # the installers set this from uname at the top;
                                  # uname is not on the stubbed PATH, so inject it
                CONDA_CMD=mamba
                print_ok()   { echo "OK   $*"; }
                print_warn() { echo "WARN $*"; }
                print_fail() { echo "FAIL $*"; }
                """).replace("__ARCH__", arch or os.uname().machine)
            + src
            + decls
            + "\n"
            + f"check_build_toolchain() {{\n{body}}}\n"
            + "check_build_toolchain\n"
        )
        harness.chmod(0o755)
        # A PATH with ONLY the stubs, so the script's `command -v` cannot find the
        # host's binaries -- which means bash must be invoked by absolute path, since
        # it is not on that PATH either.
        bash = shutil.which("bash") or "/bin/bash"
        proc = subprocess.run(
            [bash, str(harness)],
            capture_output=True,
            text=True,
            env={"PATH": str(fakebin), "HOME": str(tmp_path)},
        )
        return proc.returncode, proc.stdout + proc.stderr

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_compiling_tool_with_no_make_is_refused(self, tmp_path, path):
        rc, out = self._run(tmp_path, path, {"DO_SOLUPROT": True}, have=("git", "gcc", "g++"))
        assert rc == 1, out
        assert "Missing build toolchain" in out
        assert "make" in out
        assert "SoluProt" in out, "name which selected tool needs it"

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_the_remedy_works_without_root(self, tmp_path, path):
        """A scientist on a managed workstation may not have sudo, and the tools
        are installable from conda-forge."""
        _rc, out = self._run(tmp_path, path, {"DO_SOLUPROT": True}, have=("git",))
        assert "sudo apt-get install" in out
        assert "conda-forge" in out
        assert "--skip-preflight" in out, "say how to override a check that is wrong"

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_soluprot_is_named_as_optional(self, tmp_path, path):
        """A red failure after an hour read as "the whole install is broken". It is
        not: SoluProt is a label and ranking does not use it."""
        _rc, out = self._run(tmp_path, path, {"DO_SOLUPROT": True}, have=("git",))
        assert "OPTIONAL" in out

    def test_the_optional_note_is_not_shown_when_soluprot_is_not_selected(self, tmp_path):
        """Found by running this on BM5: the note printed on a Protein-Hunter +
        BindCraft 2 selection too, where it describes none of the named tools."""
        path = REPO / "install" / "install_aarch.sh"
        _rc, out = self._run(tmp_path, path, {"DO_PROTEIN_HUNTER": True, "DO_BINDCRAFT2": True}, have=("git",))
        assert "Protein-Hunter" in out and "BindCraft 2" in out
        assert "OPTIONAL" not in out

    @pytest.mark.parametrize(
        ("arch", "expected"),
        [("x86_64", "gxx_linux-64"), ("aarch64", "gxx_linux-aarch64")],
    )
    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_the_conda_remedy_names_this_platform_s_package(self, tmp_path, path, arch, expected):
        """Also found on BM5. conda-forge names its compiler metapackages per
        platform, so the hardcoded gxx_linux-64 was a copy-pasteable command that
        cannot resolve on a Spark -- in the one message aimed at the operator who
        has no root and therefore nothing else to try.
        """
        _rc, out = self._run(tmp_path, path, {"DO_SOLUPROT": True}, have=("git",), arch=arch)
        assert f"-c conda-forge make {expected}" in out, out

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_tool_that_needs_no_compiler_is_not_refused(self, tmp_path, path):
        """`--tool mosaic` on a box with no toolchain must still install."""
        rc, out = self._run(tmp_path, path, {}, have=())
        assert rc == 0, out
        assert "Missing build toolchain" not in out

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_everything_present_passes(self, tmp_path, path):
        rc, out = self._run(tmp_path, path, {"DO_SOLUPROT": True}, have=("git", "make", "gcc", "g++"))
        assert rc == 0, out
        assert "Toolchain:" in out

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_conda_cross_compiler_counts_as_a_compiler(self, tmp_path, path):
        """Not a nicety: it is already how Proteina-Complexa's cpdb-protein builds on
        a box with no system gcc, so demanding the system one would refuse a
        configuration that works today.
        """
        arch = os.uname().machine
        rc, out = self._run(
            tmp_path,
            path,
            {"DO_SOLUPROT": True},
            have=("git", "make", f"{arch}-conda-linux-gnu-gcc", f"{arch}-conda-linux-gnu-g++"),
        )
        assert rc == 0, out

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_git_has_no_substitute(self, tmp_path, path):
        """USEARCH is cloned before it is built, so git is not optional the way a
        specific compiler name is."""
        arch = os.uname().machine
        rc, out = self._run(
            tmp_path,
            path,
            {"DO_SOLUPROT": True},
            have=("make", "gcc", "g++", f"{arch}-conda-linux-gnu-gcc"),
        )
        assert rc == 1, out
        assert "git" in out


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_both_installers_still_lint(path):
    proc = subprocess.run(
        ["shellcheck", "--shell=bash", "--severity=warning", str(path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout
