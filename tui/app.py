"""
BindMaster interactive TUI — curses menu with simple-input fallback.

stdlib only. Launched by ``bindmaster`` (no args).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ── ANSI colours (fallback menu) ──────────────────────────────────────────────

BOLD = "\033[1m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
DIM = "\033[2m"
RESET = "\033[0m"


# ── Tool / run detection ─────────────────────────────────────────────────────


def _detect_tools(repo: Path) -> dict[str, bool]:
    """Lightweight check for installed design tools (no heavy imports)."""
    return {
        "BindCraft": (repo / "BindCraft" / "bindcraft_environment.yml").exists(),
        "BoltzGen": (repo / "BoltzGen" / "boltzgen" / "__init__.py").exists(),
        "Mosaic": (repo / "Mosaic" / ".venv" / "bin" / "python").exists(),
        "PXDesign": (repo / "PXDesign" / "pxdesign").is_dir(),
    }


def _find_conda_base(repo: Path) -> Path | None:
    """Return conda base directory (local first, then system). Lightweight."""
    local = repo / "conda"
    if (local / "etc" / "profile.d" / "conda.sh").exists():
        return local
    for candidate in [
        Path.home() / "miniforge3",
        Path.home() / "mambaforge",
        Path.home() / "miniconda3",
        Path.home() / "anaconda3",
        Path("/opt/conda"),
        Path("/opt/miniforge3"),
    ]:
        if (candidate / "etc" / "profile.d" / "conda.sh").exists():
            return candidate
    return None


def _list_runs(repo: Path) -> list[Path]:
    """Return sorted list of run directories containing run_all.sh."""
    runs_dir = repo / "runs"
    if not runs_dir.is_dir():
        return []
    results = []
    for d in sorted(runs_dir.iterdir()):
        if d.is_dir() and (d / "run_all.sh").exists():
            results.append(d)
    return results


def _run_status_line(run_dir: Path) -> str:
    """Return a short status string for a run directory."""
    parts = []
    if (run_dir / "evaluation").is_dir():
        parts.append(f"{GREEN}evaluated{RESET}")
    for tool in ("mosaic", "boltzgen", "bindcraft", "pxdesign"):
        tool_dir = run_dir / tool
        if tool_dir.is_dir() and any(tool_dir.iterdir()):
            parts.append(tool)
    if not parts:
        parts.append(f"{DIM}configured{RESET}")
    return ", ".join(parts)


# ── Subprocess helper ─────────────────────────────────────────────────────────


def _run_subprocess(cmd: list[str], label: str) -> int:
    """Run a subprocess, returning the exit code."""
    print(f"\n{'=' * 60}\n  {label}\n{'=' * 60}\n")
    result = subprocess.run(cmd)
    print("\nPress Enter to return to menu...")
    input()
    return result.returncode


# ── Curses TUI ────────────────────────────────────────────────────────────────


def _curses_run_subprocess(stdscr, cmd: list[str], label: str) -> int:  # type: ignore[type-arg]
    """Temporarily leave curses, run a subprocess, then restore."""
    import curses

    curses.def_prog_mode()
    curses.endwin()
    rc = _run_subprocess(cmd, label)
    curses.reset_prog_mode()
    stdscr.refresh()
    return rc


def _curses_pick(stdscr, title: str, items: list[str], hints: list[str] | None = None) -> int | None:  # type: ignore[type-arg]
    """Arrow-key sub-menu. Returns selected index or None (back)."""
    import curses

    sel = 0
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        # Title
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addnstr(1, 2, title, w - 4)
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        for i, item in enumerate(items):
            y = 3 + i
            if y >= h - 2:
                break
            if i == sel:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addnstr(y, 4, f" {item} ", w - 6)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addnstr(y, 4, f"  {item}", w - 6)
            if hints and i < len(hints) and hints[i]:
                hint_x = 4 + len(item) + 4
                if hint_x < w - 2:
                    stdscr.attron(curses.color_pair(2))
                    stdscr.addnstr(y, hint_x, hints[i], w - hint_x - 2)
                    stdscr.attroff(curses.color_pair(2))

        back_y = 3 + len(items) + 1
        if back_y < h - 1:
            if sel == len(items):
                stdscr.attron(curses.A_REVERSE)
                stdscr.addnstr(back_y, 4, " <- Back ", w - 6)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addnstr(back_y, 4, "  <- Back", w - 6)

        footer_y = min(back_y + 2, h - 1)
        stdscr.attron(curses.color_pair(2))
        stdscr.addnstr(footer_y, 2, "Up/Down: navigate  Enter: select  Esc: back", w - 4)
        stdscr.attroff(curses.color_pair(2))

        stdscr.refresh()
        key = stdscr.getch()
        total = len(items) + 1  # items + back
        if key == curses.KEY_UP:
            sel = (sel - 1) % total
        elif key == curses.KEY_DOWN:
            sel = (sel + 1) % total
        elif key in (10, 13, curses.KEY_ENTER):
            if sel == len(items):
                return None
            return sel
        elif key in (27, ord("b"), curses.KEY_BACKSPACE, 127):
            return None


def _curses_main(stdscr, repo: Path) -> None:  # type: ignore[type-arg]
    """Main curses event loop."""
    import curses

    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)  # title
    curses.init_pair(2, curses.COLOR_YELLOW, -1)  # hint
    curses.init_pair(3, curses.COLOR_GREEN, -1)  # ok
    curses.init_pair(4, curses.COLOR_RED, -1)  # missing

    menu_items = [
        "Install tools",
        "Configure run",
        "Run designs",
        "Evaluate results",
        "Run status",
        "Quit",
    ]
    sel = 0

    while True:
        tools = _detect_tools(repo)
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        # Header
        header = "BindMaster"
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addnstr(1, 2, header, w - 4)
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Tool status bar
        status_parts: list[str] = []
        for name, installed in tools.items():
            status_parts.append(f"{name}: {'OK' if installed else '--'}")
        y_status = 2
        stdscr.addnstr(y_status, 2, "Tools: ", w - 4)
        x = 9
        for name, installed in tools.items():
            pair = curses.color_pair(3) if installed else curses.color_pair(4)
            tag = "OK" if installed else "--"
            label = f"{name}: "
            if x + len(label) + len(tag) + 4 < w:
                stdscr.addnstr(y_status, x, label, w - x - 2)
                x += len(label)
                stdscr.attron(pair | curses.A_BOLD)
                stdscr.addnstr(y_status, x, tag, w - x - 2)
                stdscr.attroff(pair | curses.A_BOLD)
                x += len(tag) + 3

        # Hint if nothing installed
        no_tools = not any(tools.values())
        hint_y = 4
        if no_tools:
            stdscr.attron(curses.color_pair(2))
            stdscr.addnstr(hint_y, 2, "No design tools installed. Select 'Install tools' to get started.", w - 4)
            stdscr.attroff(curses.color_pair(2))
            hint_y += 2
        else:
            hint_y = 4

        # Menu
        for i, item in enumerate(menu_items):
            y = hint_y + i
            if y >= h - 2:
                break
            if i == sel:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addnstr(y, 4, f" {item} ", w - 6)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addnstr(y, 4, f"  {item}", w - 6)

        # Footer
        footer_y = min(hint_y + len(menu_items) + 1, h - 1)
        stdscr.attron(curses.color_pair(2))
        stdscr.addnstr(footer_y, 2, "Up/Down: navigate  Enter: select  q: quit", w - 4)
        stdscr.attroff(curses.color_pair(2))

        stdscr.refresh()
        key = stdscr.getch()

        if key == curses.KEY_UP:
            sel = (sel - 1) % len(menu_items)
        elif key == curses.KEY_DOWN:
            sel = (sel + 1) % len(menu_items)
        elif key in (10, 13, curses.KEY_ENTER):
            action = menu_items[sel]
            if action == "Quit":
                break
            elif action == "Install tools":
                _curses_run_subprocess(stdscr, ["bash", str(repo / "install" / "install.sh")], "Install tools")
            elif action == "Configure run":
                _curses_run_subprocess(
                    stdscr, [sys.executable, str(repo / "configurator" / "configurator.py")], "Configure run"
                )
            elif action == "Run designs":
                _curses_submenu_runs(stdscr, repo)
            elif action == "Evaluate results":
                _curses_submenu_evaluate(stdscr, repo)
            elif action == "Run status":
                _curses_submenu_status(stdscr, repo)
        elif key == ord("q"):
            break


def _curses_submenu_runs(stdscr, repo: Path) -> None:  # type: ignore[type-arg]
    """Sub-menu: pick a run to launch."""
    runs = _list_runs(repo)
    if not runs:
        _curses_show_message(stdscr, "No runs found. Use 'Configure run' first.")
        return
    names = [r.name for r in runs]
    hints = [_run_status_line(r) for r in runs]
    idx = _curses_pick(stdscr, "Run designs", names, hints)
    if idx is not None:
        script = runs[idx] / "run_all.sh"
        _curses_run_subprocess(stdscr, ["bash", str(script)], f"Run: {runs[idx].name}")


def _curses_submenu_evaluate(stdscr, repo: Path) -> None:  # type: ignore[type-arg]
    """Sub-menu: pick a run to evaluate."""
    runs = _list_runs(repo)
    if not runs:
        _curses_show_message(stdscr, "No runs found. Use 'Configure run' first.")
        return
    names = [r.name for r in runs]
    hints = [_run_status_line(r) for r in runs]
    idx = _curses_pick(stdscr, "Evaluate results", names, hints)
    if idx is not None:
        mosaic_py = repo / "Mosaic" / ".venv" / "bin" / "python"
        evaluator = repo / "evaluator" / "evaluator.py"
        if not mosaic_py.exists():
            _curses_show_message(stdscr, "Mosaic must be installed first (evaluator needs Mosaic venv).")
            return
        _curses_run_subprocess(stdscr, [str(mosaic_py), str(evaluator), str(runs[idx])], f"Evaluate: {runs[idx].name}")


def _curses_submenu_status(stdscr, repo: Path) -> None:  # type: ignore[type-arg]
    """Sub-menu: show run status (read-only view)."""
    import curses

    runs = _list_runs(repo)
    if not runs:
        _curses_show_message(stdscr, "No runs found.")
        return
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
    stdscr.addnstr(1, 2, "Run status", w - 4)
    stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
    for i, run in enumerate(runs):
        y = 3 + i
        if y >= h - 2:
            break
        name = run.name
        evaluated = (run / "evaluation").is_dir()
        if evaluated:
            stdscr.attron(curses.color_pair(3))
            stdscr.addnstr(y, 4, "*", 1)
            stdscr.attroff(curses.color_pair(3))
        else:
            stdscr.addnstr(y, 4, " ", 1)
        stdscr.addnstr(y, 6, name, w - 20)
        # tool indicators
        info = []
        for tool in ("mosaic", "boltzgen", "bindcraft", "pxdesign"):
            td = run / tool
            if td.is_dir() and any(td.iterdir()):
                info.append(tool)
        if evaluated:
            info.append("evaluated")
        detail = ", ".join(info) if info else "configured"
        detail_x = max(6 + len(name) + 2, 40)
        if detail_x + len(detail) < w:
            stdscr.attron(curses.color_pair(2))
            stdscr.addnstr(y, detail_x, detail, w - detail_x - 2)
            stdscr.attroff(curses.color_pair(2))

    footer_y = min(3 + len(runs) + 1, h - 1)
    stdscr.attron(curses.color_pair(2))
    stdscr.addnstr(footer_y, 2, "Press any key to return...", w - 4)
    stdscr.attroff(curses.color_pair(2))
    stdscr.refresh()
    stdscr.getch()


def _curses_show_message(stdscr, msg: str) -> None:  # type: ignore[type-arg]
    """Show a message and wait for keypress."""
    import curses

    stdscr.erase()
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(2))
    stdscr.addnstr(h // 2, 2, msg, w - 4)
    stdscr.attroff(curses.color_pair(2))
    stdscr.attron(curses.color_pair(2))
    stdscr.addnstr(h // 2 + 2, 2, "Press any key to return...", w - 4)
    stdscr.attroff(curses.color_pair(2))
    stdscr.refresh()
    stdscr.getch()


# ── Simple fallback menu ─────────────────────────────────────────────────────


def _simple_menu_main(repo: Path) -> None:
    """Numbered-input fallback for dumb terminals."""
    menu_items = [
        ("Install tools", "install"),
        ("Configure run", "configure"),
        ("Run designs", "run"),
        ("Evaluate results", "evaluate"),
        ("Run status", "status"),
        ("Quit", "quit"),
    ]

    while True:
        tools = _detect_tools(repo)
        print(f"\n{BOLD}{CYAN}BindMaster{RESET}\n")

        # Tool status
        parts = []
        for name, installed in tools.items():
            tag = f"{GREEN}OK{RESET}" if installed else f"{RED}--{RESET}"
            parts.append(f"{name}: {tag}")
        print(f"  Tools: {'  |  '.join(parts)}\n")

        if not any(tools.values()):
            print(f"  {YELLOW}No design tools installed. Select 'Install tools' to get started.{RESET}\n")

        for i, (label, _) in enumerate(menu_items, 1):
            print(f"  {BOLD}{i}{RESET}) {label}")
        print()

        try:
            raw = input(f"{BOLD}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        try:
            choice = int(raw)
        except ValueError:
            if raw.lower() in ("q", "quit", "exit"):
                break
            print(f"{RED}Invalid choice.{RESET}")
            continue

        if choice < 1 or choice > len(menu_items):
            print(f"{RED}Invalid choice.{RESET}")
            continue

        action = menu_items[choice - 1][1]
        if action == "quit":
            break
        elif action == "install":
            _run_subprocess(["bash", str(repo / "install" / "install.sh")], "Install tools")
        elif action == "configure":
            _run_subprocess([sys.executable, str(repo / "configurator" / "configurator.py")], "Configure run")
        elif action == "run":
            _simple_submenu_runs(repo)
        elif action == "evaluate":
            _simple_submenu_evaluate(repo)
        elif action == "status":
            _simple_submenu_status(repo)


def _simple_submenu_runs(repo: Path) -> None:
    """Simple numbered sub-menu: pick a run to launch."""
    runs = _list_runs(repo)
    if not runs:
        print(f"\n{YELLOW}No runs found. Use 'Configure run' first.{RESET}")
        return
    print(f"\n{BOLD}Run designs{RESET}\n")
    for i, r in enumerate(runs, 1):
        print(f"  {BOLD}{i}{RESET}) {r.name}  {DIM}({_run_status_line(r)}){RESET}")
    print(f"  {BOLD}0{RESET}) Back\n")
    try:
        raw = input(f"{BOLD}>{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if raw == "0" or not raw:
        return
    try:
        idx = int(raw) - 1
    except ValueError:
        return
    if 0 <= idx < len(runs):
        _run_subprocess(["bash", str(runs[idx] / "run_all.sh")], f"Run: {runs[idx].name}")


def _simple_submenu_evaluate(repo: Path) -> None:
    """Simple numbered sub-menu: pick a run to evaluate."""
    runs = _list_runs(repo)
    if not runs:
        print(f"\n{YELLOW}No runs found. Use 'Configure run' first.{RESET}")
        return
    print(f"\n{BOLD}Evaluate results{RESET}\n")
    for i, r in enumerate(runs, 1):
        print(f"  {BOLD}{i}{RESET}) {r.name}  {DIM}({_run_status_line(r)}){RESET}")
    print(f"  {BOLD}0{RESET}) Back\n")
    try:
        raw = input(f"{BOLD}>{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if raw == "0" or not raw:
        return
    try:
        idx = int(raw) - 1
    except ValueError:
        return
    if 0 <= idx < len(runs):
        mosaic_py = repo / "Mosaic" / ".venv" / "bin" / "python"
        evaluator = repo / "evaluator" / "evaluator.py"
        if not mosaic_py.exists():
            print(f"\n{RED}Mosaic must be installed first (evaluator needs Mosaic venv).{RESET}")
            return
        _run_subprocess([str(mosaic_py), str(evaluator), str(runs[idx])], f"Evaluate: {runs[idx].name}")


def _simple_submenu_status(repo: Path) -> None:
    """Simple run status display."""
    runs = _list_runs(repo)
    if not runs:
        print(f"\n{YELLOW}No runs found.{RESET}")
        return
    print(f"\n{BOLD}Run status{RESET}\n")
    for r in runs:
        evaluated = (r / "evaluation").is_dir()
        marker = f"{GREEN}*{RESET}" if evaluated else " "
        info = []
        for tool in ("mosaic", "boltzgen", "bindcraft", "pxdesign"):
            td = r / tool
            if td.is_dir() and any(td.iterdir()):
                info.append(tool)
        if evaluated:
            info.append("evaluated")
        detail = ", ".join(info) if info else "configured"
        print(f"  {marker} {r.name:<30s} {DIM}{detail}{RESET}")
    print()


# ── Public entry point ────────────────────────────────────────────────────────


def launch_tui(repo: Path) -> None:
    """Launch interactive TUI. Curses if possible, numbered menu otherwise."""
    try:
        import curses

        curses.wrapper(_curses_main, repo)
    except (ImportError, curses.error):
        _simple_menu_main(repo)
