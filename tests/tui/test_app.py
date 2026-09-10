"""Tests for the TUI entry point — no curses required."""

import sys
from pathlib import Path

import tui.app as app


def test_launch_tui_falls_back_when_curses_missing(monkeypatch):
    """If `import curses` fails, launch_tui must run the numbered-menu fallback.

    Regression: the previous `except (ImportError, curses.error)` referenced
    `curses` while it was unbound, raising NameError instead of falling back.
    """
    calls = []
    # Setting a module to None in sys.modules makes `import curses` raise ImportError.
    monkeypatch.setitem(sys.modules, "curses", None)
    monkeypatch.setattr(app, "_simple_menu_main", lambda repo: calls.append(repo))

    app.launch_tui(Path("."))

    assert calls == [Path(".")]


def test_evaluate_menu_lists_subcommands_instead_of_erroring(monkeypatch):
    """`bindmaster evaluate` with no arguments reaches argparse with a required
    subcommand missing: one usage line and exit 2. The menu entry promised "shows
    available subcommands" and delivered that error, so it asks for --help.
    """
    seen: list[list[str]] = []
    monkeypatch.setattr(app, "_run_subprocess", lambda cmd, label: seen.append(cmd) or 0)

    app._simple_submenu_evaluate(Path("/repo"))

    assert seen, "the menu entry ran nothing"
    cmd = seen[0]
    assert cmd[-2:] == ["evaluate", "--help"], f"expected an evaluate --help invocation, got {cmd}"
