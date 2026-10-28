"""The two optional screens announced themselves by failing.

BUG-10  A `--tool all` install that failed at the USEARCH build leaves
        binder-eval-soluprot standing, so evaluate.sh's name-only auto-detect
        passed, the screen RAN, and the missing binary surfaced mid-evaluation as
        a twelve-line Python traceback plus a red `ERROR conda.cli.main_run`. The
        handling underneath was already right -- the run continues, says so, and
        says refolding is unaffected -- and the FileNotFoundError text is itself
        excellent, listing all four locations searched. The defect is purely
        packaging and timing: a scientist reads a traceback as a broken run, and
        AF3 gets a tidy one-line [note] for the same condition.

        TmProt reproduces it exactly and master has no equivalent: its binary is
        resolved INSIDE the child env, so an env with no console script raises
        RuntimeError mid-evaluation in the same shape.

        Second half: stdout/stderr from the `conda run` children interleaved out
        of order, so the traceback printed BEFORE the child's own header and the
        log read as if the step crashed before it started.

BUG-12  The cross-engine gate shortfall -- the most actionable thing the report
        says -- reached the user as a raw UserWarning carrying a file path, a line
        number and a line of our own source, which reads as an internal error.
        evaluate.sh pitches the identical condition correctly earlier in the same
        run.
"""

from __future__ import annotations

import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EVALUATE = REPO / "Evaluator" / "evaluate.sh"


def _function(name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}\n", EVALUATE.read_text(), re.S | re.M)
    assert m, f"evaluate.sh does not define {name}()"
    return m.group(1)


# ─────────────────────────────────────────────── BUG-10: probe, do not crash


def test_soluprot_is_probed_for_usearch_not_just_for_its_env():
    """The env name is necessary and not sufficient: SoluProt cannot score
    without USEARCH, and a failed build leaves the env behind."""
    text = EVALUATE.read_text()
    assert "find_usearch" in text, "no USEARCH preflight — the screen still crashes to discover this"
    # Before the step, not inside it.
    assert text.index("find_usearch >/dev/null") < text.index("binder-compare filter-soluprot")


def test_the_usearch_probe_mirrors_the_runners_search_order():
    """A probe stricter than the resolver would skip a screen that WOULD work.

    soluprot_runner._resolve_usearch tries, in order: the explicit argument,
    $SOLUPROT_USEARCH, <dir>/usearch.<arch>, a bare <dir>/usearch, then PATH.
    The shell probe cannot see the explicit argument; it must cover the rest.
    """
    body = _function("find_usearch")
    assert "SOLUPROT_USEARCH" in body
    assert "SOLUPROT_HOME" in body, "the runner honours $SOLUPROT_HOME for the scripts dir"
    assert "usearch.${arch}" in body
    assert "command -v usearch" in body, "the resolver falls back to PATH"

    runner = (REPO / "Evaluator" / "binder_comparison" / "refolding" / "soluprot_runner.py").read_text()
    resolver = runner[runner.index("def _resolve_usearch") : runner.index("def _find_entry_script")]
    for token in ("SOLUPROT_USEARCH", "usearch", "which"):
        assert token in resolver, f"the resolver no longer mentions {token} — re-check the probe above"


def test_tmprot_is_probed_for_its_binary_not_just_for_its_env():
    """Resolved inside the child env, so only the env can answer."""
    text = EVALUATE.read_text()
    assert "TMPROT_BIN:-tmprot" in text, "no tmprot binary preflight"
    assert text.index("TMPROT_BIN:-tmprot") < text.index("binder-compare screen-tmprot")


@pytest.mark.parametrize("screen", ["soluprot", "tmprot"])
def test_the_skip_notice_says_ranking_is_unaffected(screen):
    """A red failure mid-evaluation read as "the whole run is broken". Neither
    screen touches the refold pool or the ranking -- say so where it is skipped."""
    text = EVALUATE.read_text()
    notices = [ln for ln in text.splitlines() if "will be skipped" in ln and screen in ln.lower()]
    assert len(notices) >= 2, f"{screen} should have both an env notice and a binary notice: {notices}"
    for notice in notices:
        block = text[text.index(notice) :][:500]
        assert "ranking is unaffected" in block, (
            f"this {screen} skip notice does not say the ranking is safe:\n{notice}"
        )
        assert "binderscout install --tool" in block, "say how to get it"


def test_child_step_logs_are_chronological():
    """Python block-buffers stdout off a terminal while stderr stays unbuffered,
    so a child's traceback arrived before the child's own header."""
    text = EVALUATE.read_text()
    assert "export PYTHONUNBUFFERED=1" in text
    # Before the first conda run, or it does not reach the children that matter.
    assert text.index("export PYTHONUNBUFFERED=1") < text.index("conda run -n")


class TestTheUsearchProbeBehaviour:
    """Run find_usearch with a controlled filesystem."""

    def _run(self, tmp_path, env: dict[str, str] | None = None) -> tuple[int, str]:
        harness = tmp_path / "p.sh"
        harness.write_text(
            "#!/usr/bin/env bash\nset -uo pipefail\n"
            f'SCRIPT_DIR="{tmp_path}"\n'
            f"find_usearch() {{\n{_function('find_usearch')}}}\n"
            "find_usearch\n"
        )
        base = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        base.update(env or {})
        proc = subprocess.run(["bash", str(harness)], capture_output=True, text=True, env=base)
        return proc.returncode, proc.stdout.strip()

    def test_nothing_anywhere_is_a_skip(self, tmp_path):
        rc, _out = self._run(tmp_path)
        assert rc == 1, "an absent USEARCH must report absent, so the screen is skipped"

    def test_a_per_arch_bundled_binary_is_found(self, tmp_path):
        import platform

        d = tmp_path / "tools" / "soluprot"
        d.mkdir(parents=True)
        binary = d / f"usearch.{platform.machine()}"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        rc, out = self._run(tmp_path)
        assert rc == 0 and out.endswith(binary.name), out

    def test_a_bare_bundled_binary_is_found(self, tmp_path):
        d = tmp_path / "tools" / "soluprot"
        d.mkdir(parents=True)
        binary = d / "usearch"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        rc, out = self._run(tmp_path)
        assert rc == 0 and out.endswith("usearch"), out

    def test_soluprot_home_wins_over_the_default_dir(self, tmp_path):
        """The runner honours it, so the probe must too, or a working install
        elsewhere is reported absent."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        binary = elsewhere / "usearch"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        rc, out = self._run(tmp_path, {"SOLUPROT_HOME": str(elsewhere)})
        assert rc == 0 and str(elsewhere) in out, out

    def test_an_explicit_env_override_wins(self, tmp_path):
        binary = tmp_path / "my_usearch"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        rc, out = self._run(tmp_path, {"SOLUPROT_USEARCH": str(binary)})
        assert rc == 0 and out == str(binary), out

    def test_a_non_executable_override_is_not_accepted(self, tmp_path):
        """Pointing at a text file is a misconfiguration, not an install."""
        decoy = tmp_path / "not_a_binary"
        decoy.write_text("hello\n")
        rc, _out = self._run(tmp_path, {"SOLUPROT_USEARCH": str(decoy)})
        assert rc == 1


# ───────────────────────────────────── BUG-12: a notice, not a UserWarning


@pytest.fixture
def two_engine_pool():
    pd = pytest.importorskip("pandas")
    sys.path.insert(0, str(REPO / "Evaluator"))
    from binder_comparison.comparison.scoring import compute_consensus_iptm

    df = pd.DataFrame(
        {
            "binder_id": ["d1", "d2"],
            "sequence": ["AAAA", "CCCC"],
            # The real column names (_ENGINE_IPTM_COLS) -- with anything else the
            # pool has ZERO engines, which trips the other warning branch and makes
            # these tests pass for the wrong reason.
            "boltz_pae_iptm": [0.80, 0.60],
            "esmfold2_pae_iptm": [0.70, 0.50],
        }
    )
    return compute_consensus_iptm(df)


def _rank(df, min_engines):
    sys.path.insert(0, str(REPO / "Evaluator"))
    from binder_comparison.cli.report import _rank_and_report_the_gate

    return _rank_and_report_the_gate(df, min_engines)


def test_the_gate_shortfall_reaches_stdout_on_the_report_channel(two_engine_pool, capsys):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _rank(two_engine_pool, 3)
    out = capsys.readouterr().out
    assert "[rank] WARNING:" in out, "the shortfall must be on the report's own channel"
    assert "no design was refolded by 3+ engines" in out
    assert "--min-engines" in out, "the remedy must survive the re-pitch"


def test_no_line_of_the_notice_carries_a_traceback_shape(two_engine_pool, capsys):
    """What made it read as an internal error: a path, a line number, and a line
    of our source."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _rank(two_engine_pool, 3)
    for line in capsys.readouterr().out.splitlines():
        if not line.startswith("[rank]"):
            continue
        assert "UserWarning" not in line
        assert "report.py:" not in line
        assert "rank_designs(" not in line


def test_the_consequence_passage_is_not_lost_in_the_re_pitch(two_engine_pool, capsys):
    """This branch's message says more than master's, and a test already asserts
    on these words. Re-pitching the presentation must not rewrite the text."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _rank(two_engine_pool, 3)
    out = capsys.readouterr().out
    for word in ("outrank", "designer-bias", "shortlist"):
        assert word in out, f"the re-pitched notice dropped {word!r}"


def test_the_warning_is_still_raised_for_anything_programmatic(two_engine_pool):
    """Tests and callers filter on it; the human copy is additional, not a
    replacement."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _rank(two_engine_pool, 3)
    messages = [str(w.message) for w in caught]
    assert any(m.startswith("[rank]") for m in messages), messages


def test_a_pool_that_clears_the_gate_says_nothing(two_engine_pool, capsys):
    """The notice must fire on the shortfall, not on every run."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _rank(two_engine_pool, 2)
    assert "[rank] WARNING:" not in capsys.readouterr().out


def test_an_unrelated_warning_is_passed_through_untouched(two_engine_pool, capsys):
    """Swallowing a pandas FutureWarning to re-pitch ours would be a worse bug
    than the one being fixed."""
    sys.path.insert(0, str(REPO / "Evaluator"))
    import binder_comparison.cli.report as rep

    def _noisy(df, min_engines):
        warnings.warn("something else entirely", FutureWarning, stacklevel=2)
        return df

    original = rep.rank_designs
    rep.rank_designs = _noisy
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rep._rank_and_report_the_gate(two_engine_pool, 3)
    finally:
        rep.rank_designs = original

    assert any("something else entirely" in str(w.message) for w in caught)
    assert "[rank] WARNING:" not in capsys.readouterr().out


def test_the_report_command_actually_uses_the_wrapper():
    """The call site, not just the function.

    Every test above calls _rank_and_report_the_gate directly, so reverting
    report.run() to a bare `rank_designs(...)` -- which is the entire bug -- left
    all of them green. Asserted against run()'s own AST rather than by driving
    the whole report, which needs a full refold pool: what matters is that no
    direct call survives in the one function a human's report goes through.
    """
    import ast

    src = (REPO / "Evaluator" / "binder_comparison" / "cli" / "report.py").read_text()
    run_fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run")
    called = {n.func.id for n in ast.walk(run_fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_rank_and_report_the_gate" in called, "report.run() does not go through the gate wrapper"
    assert "rank_designs" not in called, (
        "report.run() still calls rank_designs directly — its UserWarning reaches the "
        "user with a file path, a line number and a line of our source"
    )


def test_long_notices_are_wrapped():
    sys.path.insert(0, str(REPO / "Evaluator"))
    from binder_comparison.cli.report import _gate_notice_lines

    lines = _gate_notice_lines("word " * 80)
    assert len(lines) > 1
    assert all(len(line) <= 92 for line in lines), [len(line) for line in lines]
    assert " ".join(lines).split() == ("word " * 80).split(), "wrapping must not lose or reorder words"
