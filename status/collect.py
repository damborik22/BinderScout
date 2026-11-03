"""Discover runs, classify each arm, derive cadence. No I/O beyond the probes."""

import itertools
import json
import math
import os
import statistics
import time
from pathlib import Path

from status import liveness
from status.probes import KNOWN_TOOLS, probe_started, probe_tool, resolve_alias
from status.schema import DEAD, DONE, QUEUED, RUNNING, SCHEMA_VERSION

__all__ = [
    "cadence",
    "checkout_marker_path",
    "classify",
    "collect_local",
    "eta_seconds",
    "home_relative",
    "probe_started",
    "record_checkout",
    "resolve_repo",
]

# Writes closer together than this belong to one batch. RFD3 emits ten designs
# inside a single second, so anything from ~0.5 s up gives the same answer.
_BURST_WINDOW_S = 2.0

# Finding a checkout on a box that was not told where it is (the ssh-shipped probe). No
# directory NAME is assumed: a checkout is a directory holding `binderscout.py` and `runs/`.
_SCAN_MAX_DEPTH = 2  # ~/x and ~/x/y
_SCAN_MAX_DIRS = 2000


def classify(done: int, total, proc_alive: bool, started: bool, output_age_s=None) -> str:
    """The state of one arm.

    `output_age_s` is accepted and deliberately IGNORED. RFD3 is silent for ~70
    minutes between batches while perfectly healthy, so letting age override a
    live process would mark working arms dead -- and the campaign's response to
    "dead" is to relaunch. Age is rendered as context, never used to decide.
    """
    if total is not None and done >= total:
        return DONE
    if proc_alive:
        return RUNNING
    # settings.json exists but the process is gone: it started and died.
    return DEAD if started else QUEUED


def cadence(mtimes) -> dict:
    """Batch size and inter-batch gap, from write timestamps alone."""
    ordered = sorted(mtimes)
    if not ordered:
        return {"batches": 0, "batch_size": None, "gap_s": None}

    bursts = [[ordered[0]]]
    for t in ordered[1:]:
        if t - bursts[-1][-1] > _BURST_WINDOW_S:
            bursts.append([t])
        else:
            bursts[-1].append(t)

    sizes = [len(b) for b in bursts]
    starts = [b[0] for b in bursts]
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    return {
        "batches": len(bursts),
        "batch_size": int(statistics.median(sizes)),
        # One batch is not a cadence. A fabricated ETA is worse than none.
        "gap_s": float(statistics.median(gaps)) if gaps else None,
    }


def eta_seconds(done: int, total, mtimes):
    """Seconds remaining, from observed cadence. None whenever that is unknown."""
    if total is None or done >= total:
        return None
    c = cadence(mtimes)
    if not c["gap_s"] or not c["batch_size"]:
        return None
    batches_left = math.ceil((total - done) / c["batch_size"])
    return batches_left * c["gap_s"]


def home_relative(path) -> str:
    """A path with the account name taken out of it.

    This document is published to a page, and an absolute checkout path names
    the Unix account. Captured across the fleet it named four of them. Which
    checkout a box used is still worth reporting -- the spellings differ per box
    -- so it is reported against $HOME rather than dropped.

    $HOME is tried as spelled AND resolved: when it is a symlink, a checkout path
    that has been resolved no longer sits under the spelled home, and publishing it
    whole would name the account (and the storage behind the link).
    """
    path = Path(path)
    home = Path.home()
    for base in dict.fromkeys((home, home.resolve())):
        if path == base:
            return "~"
        try:
            return "~/" + str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def checkout_marker_path() -> Path:
    """Where the shortcut installer records which checkout this box uses."""
    return Path.home() / ".config" / "binderscout" / "checkout"


def record_checkout(repo) -> None:
    """Write the marker. Raises OSError; the caller decides whether that matters.

    Every CLI invocation calls this, from whatever checkout ran it. `runs/` is gitignored, so a
    scratch clone or a linked worktree has none: such a checkout must not repoint a marker that
    already names a working one, or the ssh probe would report zero runs.
    """
    marker = checkout_marker_path()
    repo = Path(repo).resolve()
    text = str(repo) + "\n"
    if marker.is_file() and marker.read_text() == text:
        return
    if not (repo / "runs").is_dir() and _read_marker() is not None:
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(text)


def _is_checkout(path: Path, need_runs: bool) -> bool:
    return (path / "binderscout.py").is_file() and (not need_runs or (path / "runs").is_dir())


def _read_marker() -> Path | None:
    try:
        recorded = Path(checkout_marker_path().read_text().strip())
    except (OSError, ValueError, RuntimeError):
        return None
    return recorded if recorded.is_absolute() and _is_checkout(recorded, need_runs=True) else None


def _scan_for_checkout() -> Path | None:
    """Breadth-first, shallowest first, name-agnostic, bounded. Hidden dirs are skipped.

    A symlink directly under $HOME is followed (a checkout often lives on other storage and is
    linked into the home directory); deeper symlinks are not. Every directory is entered once,
    by realpath, so a link back to $HOME or two links to one checkout cost nothing extra.
    """
    try:
        level = [Path.home()]
    except RuntimeError:  # no resolvable home directory
        return None
    seen = {os.path.realpath(level[0])}
    visited = 0
    for depth in range(_SCAN_MAX_DEPTH):
        children = []
        for parent in level:
            try:
                with os.scandir(parent) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=depth == 0):
                    continue
                real = os.path.realpath(entry.path)
                if real in seen:
                    continue
                seen.add(real)
                visited += 1
                if visited > _SCAN_MAX_DIRS:
                    return None
                child = Path(entry.path)
                if _is_checkout(child, need_runs=True):
                    return child
                children.append(child)
        level = children
    return None


def resolve_repo(explicit=None) -> Path | None:
    """Find the checkout on THIS box without hard-coding a path or a directory name.

    Order: the caller's own root; $BINDERSCOUT_DIR; the marker the shortcut installer
    wrote; a bounded scan of $HOME. The probe shipped over ssh has no checkout to ask,
    so it relies on the last three.
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get("BINDERSCOUT_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return _read_marker() or _scan_for_checkout()


def _enabled_tools(run_dir: Path, cfg: dict) -> list:
    """Tools this run was configured with, from config then from run scripts."""
    # Resolve aliases BEFORE de-duplicating: tools_enabled can carry both
    # `pxdesign_local` and `pxdesign`, which are one arm and one row.
    enabled = [resolve_alias(t) for t, on in (cfg.get("tools_enabled") or {}).items() if on]
    enabled = list(dict.fromkeys(t for t in enabled if t != "evaluator"))
    if not enabled:
        enabled = [p.name[len("run_") : -len(".sh")] for p in sorted(run_dir.glob("run_*.sh"))]
        enabled = [t for t in enabled if t not in ("all", "evaluate")]
    # A directory present but unconfigured still gets probed: an arm relocated
    # by hand is exactly the thing worth seeing.
    for child in sorted(run_dir.iterdir()):
        if child.is_dir() and child.name in KNOWN_TOOLS and child.name not in enabled:
            enabled.append(child.name)
    return enabled


def collect_local(repo_root=None, host: str = "local") -> dict:
    """Probe every run on this box. Never raises on one bad run directory."""
    repo = resolve_repo(repo_root)
    if repo is None:
        return {"reachable": True, "host": host, "runs": {}, "gpu": [], "error": "no checkout found"}

    table = liveness.process_table()
    gpu_mem = liveness.gpu_memory_by_pid()
    runs = {}

    for run_dir in sorted((repo / "runs").iterdir()) if (repo / "runs").is_dir() else []:
        cfg_path = run_dir / "config.json"
        if not run_dir.is_dir() or not cfg_path.is_file():
            continue
        try:
            raw = json.loads(cfg_path.read_text())
        except (OSError, ValueError):
            continue
        cfg = {**raw, **(raw.get("cfg") or {})}

        tools = {}
        for tool in _enabled_tools(run_dir, raw):
            try:
                p = probe_tool(tool, run_dir, cfg)
                proc = liveness.tool_alive(tool, run_dir, table=table, gpu_mem=gpu_mem)
                c = cadence(p["mtimes"])
                newest = p.get("activity_mtime") or (max(p["mtimes"]) if p["mtimes"] else None)
                tools[tool] = {
                    "state": classify(p["done"], p["total"], proc["alive"], p["started"]),
                    "done": p["done"],
                    "total": p["total"],
                    "started": p["started"],
                    "phase": p.get("phase"),
                    "output_age_s": (time.time() - newest) if newest else None,
                    "batch_size": c["batch_size"],
                    "gap_s": c["gap_s"],
                    "eta_s": eta_seconds(p["done"], p["total"], p["mtimes"]),
                    "proc": proc,
                    "warnings": p["warnings"],
                }
            except OSError as exc:  # one unreadable arm must not blank the box
                tools[tool] = {"state": QUEUED, "done": 0, "total": None, "warnings": [f"probe failed: {exc}"]}

        runs[run_dir.name] = {"n_designs": cfg.get("n_designs"), "tools": tools}

    return {
        "reachable": True,
        "host": host,
        "schema": SCHEMA_VERSION,
        "repo": home_relative(repo),
        "gpu": liveness.gpus(),
        "runs": runs,
    }


if __name__ == "__main__":  # shipped over stdin by remote.py
    print(json.dumps(collect_local(host=os.environ.get("BINDERSCOUT_HOST_LABEL", "local"))))
