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
