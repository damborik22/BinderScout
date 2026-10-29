"""Every run script the configurator writes must parse as bash and hand its embedded Python to python3 unchanged.

run_proteina_complexa.sh, as generated in the 1.0.6 tree, is not valid bash: `bash -n` rejects it
("syntax error near unexpected token `('"). Its harvest is a multi-line `python3 -c "..."` program, and a
comment inside that program quotes "design complete" and "Proteina-Complexa: no CSV found" in double
quotes. Each quote closes bash's string early, so python3 is given a truncated program (a valid one, which
does nothing) and bash goes on to run the rest of the Python as shell commands: `rows: command not found`,
exit 127. That happens AFTER the GPU design step has finished. No sequences.csv is written and the
Evaluator ranks a pool with Proteina-Complexa missing -- the symptom the offending comment was written to
describe.

Nothing could see it. CI's shellcheck lints `git ls-files '*.sh'`, and a generated script is not tracked.
test_proteina_harvest.py does execute that harvest, but it cuts the body out of the script with a regex and
hands it to `python -I -c`, so bash is never involved. test_settings_json_convention.py does run bash, but
only on the settings heredoc, copied into a new file.

`bash -n` is necessary and not sufficient. A stray double quote that leaves the count EVEN parses cleanly
and still breaks the program: bash splits the string at the now-unquoted whitespace, so python3 receives a
truncated program plus extra arguments. The PXDesign collector with `print("...")` in place of
`print('...')` does exactly that ("'(' was never closed"). The house style is double quotes (ruff.toml), so
tidying the embedded program to match is a plausible hand edit -- and ruff will not catch it, because the
program is inside a string literal. Backticks and `$` are as live inside the string as `"` is -- bash runs a
backticked word as a command -- and the same Proteina-Complexa comments are full of them.

So there are two checks, both driven by conf.TOOL_SEQUENCE so that a tool added there is covered at once:

  1. `bash -n` over every script the configurator writes.
  2. every embedded `python3 -c "..."` statement is run, as written, under real bash with python3 replaced
     by a recorder; what python3 received must equal what the writer wrote.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

BASH = shutil.which("bash") or "bash"

ALL_TOOLS = {**{key: True for key, *_ in conf.TOOL_SEQUENCE}, "evaluator": True}

# An embedded program is `python3 -c "` alone on its line, the program, then a lone `"`. Blocks are found
# by LINE and never by counting quotes: counting is exactly what a stray quote corrupts.
OPENER = 'python3 -c "'
CLOSER = '"'

# What bash does to text inside a double-quoted string, limited to what the writers rely on: a backslash
# before $ ` " \ or a newline is dropped, and $RUN_DIR (which the script sets) expands. A bare quote, a
# backtick or any other $ is deliberately NOT modelled -- bash acts on those, and that is the defect.
DQ_STRING = re.compile(r"\\([$`\"\\\n])|\$(?:RUN_DIR\b|\{RUN_DIR\})")
STILL_LIVE = re.compile(r"[\"`$]")

# Defines python3 as a function that records its argv, one NUL-terminated file per call.
RECORDER = """\
_n=0
python3() { _n=$((_n + 1)); printf '%s\\0' "$@" > "$CALLS/call.$_n"; }
"""


@pytest.fixture
def full_cfg(tmp_path):
    """A cfg populated for *every* writer, so no tool is skipped for missing keys."""
    run_dir = tmp_path / "runs" / "test"
    run_dir.mkdir(parents=True)
    target_pdb = tmp_path / "target.pdb"
    target_pdb.write_text(
        "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      2  CA  ALA A   2       3.800   0.000   0.000  1.00  0.00           C\n"
        "ATOM      3  CA  GLU A   3       7.600   0.000   0.000  1.00  0.00           C\n"
    )
    return {
        "name": "test_target",
        "run_dir": run_dir,
        "target_pdb": target_pdb,
        "target_pdb_src": str(target_pdb),
        "target_sequence": "MAE",
        "chains": "A",
        "hotspots": "1,3",
        "min_length": 65,
        "max_length": 150,
        "n_designs": 10,
        "boltzgen_mode": "protein",
        "boltzgen_intermediate": 10000,
        "filter_preset": "default_filters",
        "advanced_preset": "default_4stage_multimer",
        "pxdesign_binder_length": 80,
        "pxdesign_n_samples": 1000,
        "pxdesign_preset": "preview",
        "pxdesign_hotspots": "1,3",
        "pxdesign_chains": "A",
    }


def _scripts():
    """(script name, writer, cfg overrides) for every script the configurator writes.

    The per-tool writers come from TOOL_SEQUENCE. run_all.sh and run_evaluate.sh are not tools, and the
    PXDesign length-scan branch writes a different script around the same collector, so those are listed
    by hand.
    """
    out = [
        pytest.param(script, getattr(conf, "write_" + script.removesuffix(".sh"), None), {}, id=key)
        for key, script, _label, _subdir in conf.TOOL_SEQUENCE
    ]
    out += [
        pytest.param(
            "run_pxdesign.sh",
            conf.write_run_pxdesign,
            {"pxdesign_length_scan": True, "pxdesign_top_per_length": 5},
            id="pxdesign_local-length-scan",
        ),
        pytest.param("run_all.sh", lambda path, cfg: conf.write_run_all(path, cfg, ALL_TOOLS), {}, id="run_all"),
        pytest.param(
            "run_evaluate.sh", lambda path, cfg: conf.write_run_evaluate(path, cfg, ALL_TOOLS), {}, id="run_evaluate"
        ),
    ]
    return out


def _emit(script, writer, overrides, cfg):
    assert callable(writer), f"the configurator has no writer for {script}"
    path = cfg["run_dir"] / script
    writer(path, {**cfg, **overrides})
    return path


def _inline_python_blocks(text, script):
    """Each `python3 -c "` statement in the script, as (line number of its opener, lines opener..closer)."""
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == OPENER:
            close = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == CLOSER), None)
            assert close is not None, f"{script}:{i + 1} opens `{OPENER}` and no later line closes it"
            blocks.append((i + 1, lines[i : close + 1]))
            i = close
        i += 1
    openings = sum(OPENER in line for line in lines)
    assert openings == len(blocks), (
        f"{script} has {openings} `{OPENER}` statements but only {len(blocks)} are laid out as a block "
        f"(opener alone on its line, closer alone on its line). This test cannot check the others; "
        f"lay them out that way or teach _inline_python_blocks the new shape."
    )
    return blocks


def _run_under_bash(statement, run_dir, workdir):
    """Run the statement exactly as written, with python3 replaced by a recorder of its argv.

    PATH is an empty directory, so a backticked word inside the string is "command not found" and cannot
    be a command. Returns (the argv of every python3 call, the finished bash process).
    """
    calls = workdir / "calls"
    calls.mkdir(parents=True)
    no_commands = workdir / "no-commands-here"
    no_commands.mkdir()
    recorder = workdir / "recorder.sh"
    recorder.write_text(RECORDER)
    script = workdir / "statement.sh"
    script.write_text("\n".join(statement) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [BASH, str(script)],
        capture_output=True,
        text=True,
        errors="replace",
        cwd=workdir,
        timeout=60,
        env={
            "PATH": str(no_commands),
            "HOME": str(workdir),
            "BASH_ENV": str(recorder),
            "CALLS": str(calls),
            "RUN_DIR": str(run_dir),
        },
    )
    argvs = [f.read_bytes().decode("utf-8").split("\0")[:-1] for f in sorted(calls.iterdir())]
    return argvs, proc


def _what_bash_should_deliver(statement, run_dir):
    """The program a correctly written statement hands to python3: the text between the quotes."""

    def expand(match):
        if match.group(1) is None:
            return str(run_dir)  # $RUN_DIR
        return "" if match.group(1) == "\n" else match.group(1)  # backslash escape

    return DQ_STRING.sub(expand, "\n" + "\n".join(statement[1:-1]) + "\n")


def _first_difference(expected, received, first_line):
    want, have = expected.split("\n"), received.split("\n")
    for offset, (w, h) in enumerate(zip(want, have)):
        if w != h:
            return f"line {first_line + offset}: the writer wrote {w[:100]!r}, python3 received {h[:100]!r}"
    return (
        f"python3's program is {len(received)} characters, the writer's {len(expected)}; one is a prefix of the other"
    )


def _shell_active_lines(script, first_line, statement):
    """The body lines still carrying a `"`, a backtick or a `$` once the modelled escapes are removed."""
    return [
        f"    {script}:{first_line + n}: {line.strip()[:90]}"
        for n, line in enumerate(statement[1:-1], 1)
        if STILL_LIVE.search(DQ_STRING.sub("", line))
    ]


def _delivery_problem(script, first_line, statement, run_dir, workdir):
    """None when bash hands python3 exactly the program the writer wrote; otherwise a report of what it did."""
    expected = _what_bash_should_deliver(statement, run_dir)
    argvs, proc = _run_under_bash(statement, run_dir, workdir)
    if argvs == [["-c", expected]] and proc.returncode == 0 and not proc.stderr:
        return None

    report = [f"{script}: bash did not hand python3 the program the writer wrote (statement at line {first_line})."]
    if len(argvs) == 1 and len(argvs[0]) == 2 and argvs[0][0] == "-c":
        report.append("  " + _first_difference(expected, argvs[0][1], first_line))
    else:
        report.append(
            f"  python3 was called {len(argvs)} time(s) with argument counts {[len(a) for a in argvs]}; "
            f"the words after -c and the program: {argvs[0][2:8] if argvs else None}"
        )
    report.append(f"  bash exited {proc.returncode} and said:\n    " + proc.stderr[:1200].replace("\n", "\n    "))
    culprits = _shell_active_lines(script, first_line, statement)
    if culprits:
        report.append('  lines holding a ", a backtick or a $ that bash acts on inside the string:')
        report += culprits
    return "\n".join(report)


class TestEveryGeneratedScriptIsValidBash:
    @pytest.mark.parametrize(("script", "writer", "overrides"), _scripts())
    def test_bash_accepts_the_generated_script(self, script, writer, overrides, full_cfg):
        """`bash -n` needs no conda, no GPU and no tool install: it only parses."""
        path = _emit(script, writer, overrides, full_cfg)
        proc = subprocess.run([BASH, "-n", str(path)], capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, f"bash rejects the generated {script} (rc={proc.returncode}):\n{proc.stderr}"


class TestEmbeddedPythonReachesPython3Intact:
    """`bash -n` cannot see a stray quote that leaves the count even, or a backtick: both parse fine and
    still change the program. Run the real statement and look at what python3 is given.

    A script with no embedded program passes trivially; a program added to any writer later is checked
    without touching this file.
    """

    @pytest.mark.parametrize(("script", "writer", "overrides"), _scripts())
    def test_bash_hands_python3_exactly_the_program_the_writer_wrote(
        self, script, writer, overrides, full_cfg, tmp_path
    ):
        path = _emit(script, writer, overrides, full_cfg)
        blocks = _inline_python_blocks(path.read_text(encoding="utf-8"), script)
        for n, (first_line, statement) in enumerate(blocks):
            problem = _delivery_problem(script, first_line, statement, full_cfg["run_dir"], tmp_path / f"statement-{n}")
            assert problem is None, problem

    def test_both_harvests_are_still_found_in_one_safe_form_or_the_other(self, full_cfg):
        """Guards the check above: were the layouts it looks for to change, it would pass over zero blocks.

        There are two safe forms, and a harvest must be in one of them.

        * An inline ``python3 -c "`` block, which the check above executes under bash to prove
          the program arrives intact. PXDesign's harvest is this shape, and it is safe only
          because its comments happen to carry no quote or backquote.
        * A heredoc with a QUOTED delimiter, which bash passes through without substitution of
          any kind. Proteina-Complexa's harvest is this shape, and had to be: its comments
          carry 9 quotes and 12 backquoted words, which made the generated script fail
          ``bash -n`` outright until the heredoc replaced the inline string. There is nothing
          for the execution check to prove here — a quoted heredoc cannot be mangled — so this
          test only insists the quoting is still there. An UNQUOTED ``<<PY`` would substitute
          again and must not pass.
        """
        unquoted_ok = {"run_pxdesign.sh"}
        for script, writer in (
            ("run_pxdesign.sh", conf.write_run_pxdesign),
            ("run_proteina_complexa.sh", conf.write_run_proteina_complexa),
        ):
            text = _emit(script, writer, {}, full_cfg).read_text(encoding="utf-8")
            inline = len(_inline_python_blocks(text, script))
            quoted_heredoc = re.search(r"python3 - <<'(\w+)'", text)
            assert inline == 1 or quoted_heredoc, (
                f"no harvest found in {script} in either safe form — neither an embedded `{OPENER}` block "
                f"nor a `python3 - <<'DELIM'` heredoc. If it moved again, update this test and "
                f"test_proteina_harvest.py together rather than let the check above go vacuous."
            )
            if script not in unquoted_ok and not inline:
                assert quoted_heredoc, f"{script}: harvest heredoc lost its quoted delimiter"
                assert f"<<{quoted_heredoc.group(1)}" not in text.replace(f"<<'{quoted_heredoc.group(1)}'", ""), (
                    f"{script}: the harvest heredoc delimiter is used unquoted somewhere, which re-enables substitution"
                )
