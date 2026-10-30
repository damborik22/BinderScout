"""One probe per tool. Probes COUNT; they never parse.

A monitor must not crash on a half-written CSV, which is exactly the file state
it will meet while a tool is running. Counting is also cheap enough to need no
cache -- and a cache is staleness, which defeats the point.

Layouts here were read off disk on 2026-10-30 rather than taken from docs:
  rfd3 -> rfd3/diffusion/*.cif.gz
  rfd4 -> rfd4/generate/inference_samples/<name>_<i>/<name>_<i>_generated.cif
"""

import json
import os
import re
from pathlib import Path

# Glob patterns are relative to the RUN directory. First non-empty match wins,
# so a tool with two historical layouts can list both newest-first.
_FILE_GLOBS = {
    "rfd3": ["rfd3/diffusion/*.cif.gz"],
    "rfd4": ["rfd4/generate/**/inference_samples/*/*_generated.cif"],
    "bindcraft": ["bindcraft/**/Accepted/*.pdb", "bindcraft/outputs/*.pdb"],
    "pxdesign": ["pxdesign/**/*.pdb"],
    "proteina_complexa": ["proteina_complexa/**/evaluation_results/**/*.pdb"],
}

# Tools whose progress is a ROW COUNT, not a file count.
_CSV_SOURCES = {
    # BindCraft 2's budget is a quota of ACCEPTED designs and it writes
    # structures for rejected candidates too, so a file count overstates it.
    "bindcraft2": "bindcraft2/3_Ranked/!_Ranked.csv",
    "mosaic": "mosaic/designs.csv",
}

# BoltzGen's design count lives in a metrics CSV whose name carries a step or a
# budget, so it is a glob rather than a path. Preference order is the
# extractor's, and a test pins the two lists together: BoltzGen writes thousands
# of files under intermediate_designs/ that are NOT designs, so counting
# structures would report a run that has finished nothing as nearly complete.
_CSV_GLOBS = {
    "boltzgen": ("final_designs_metrics_*.csv", "aggregate_metrics_*.csv"),
}


# BoltzGen generates raw designs here first, for hours, before any metrics file
# exists. They are not finished designs, but they ARE progress, and 18 hours of
# it was invisible while the probe reported 0.
_BOLTZGEN_RAW_GLOB = "boltzgen/**/intermediate_designs/*.cif"


def boltzgen_count_sources() -> tuple:
    """The files BoltzGen's design count is read from, in preference order."""
    return _CSV_GLOBS["boltzgen"]


def _probe_boltzgen(run_dir: Path, tool_dir: Path, cfg: dict) -> tuple:
    """(done, total, paths, phase) for whichever phase the arm is in.

    Two phases, two denominators: `--num_designs` raw designs are generated,
    then analysed, then filtered down to `--budget` final ones. Reporting the
    banked count alone shows 0 for the entire generation phase.
    """
    params = _settings_params(tool_dir)
    for pattern in _CSV_GLOBS["boltzgen"]:
        hits = sorted(tool_dir.rglob(pattern))
        if hits:
            budget = params.get("budget")
            return _rows(hits[-1]), (budget if isinstance(budget, int) else None), [hits[-1]], "banked"

    raw = sorted(run_dir.glob(_BOLTZGEN_RAW_GLOB))
    requested = params.get("num_designs")
    total = requested if isinstance(requested, int) else cfg.get("n_designs")
    return len(raw), total, raw, "generating"


# Tools that mark progress by creating a directory per design.
_DIR_GLOBS = {
    "protein_hunter": ["protein_hunter/*/run_*"],
}

KNOWN_TOOLS = tuple(sorted({*_FILE_GLOBS, *_CSV_SOURCES, *_CSV_GLOBS, *_DIR_GLOBS}))

# config.json's tools_enabled uses a different name from the directory on disk
# for a couple of tools. Without this the renderer shows a second, empty row
# with no denominator next to the real one.
_ALIASES = {"pxdesign_local": "pxdesign", "proteina_complexa_local": "proteina_complexa"}

# Each tool's own settings.json records the count it was ACTUALLY given;
# cfg["n_designs"] is only the campaign-wide default.
_COUNT_KEYS = ("num_designs", "n_designs", "number_of_final_designs")

# Below this, rfd3 centred the frame on the whole motif instead of the epitope:
# the binder nucleates inside the target and every design in the arm is void.
# Measured good runs sit at ~23 A, the broken one at 0.008 A.
_FIXED_COM_FLOOR_A = 1.0


def resolve_alias(tool: str) -> str:
    """The directory name on disk for a config's tool key."""
    return _ALIASES.get(tool, tool)


def probe_started(tool_dir: Path) -> bool:
    """Did this tool get as far as starting?

    Every run script writes settings.json BEFORE the design step, so settings
    with no designs means the tool started and died -- the 0-second
    EnvironmentNameNotFound / argument-discarding-wrapper class. A bare
    directory means it never launched. Conflating the two is expensive: one
    gets relaunched, the other left alone.
    """
    return (Path(tool_dir) / "settings.json").is_file()


def _settings_params(tool_dir: Path) -> dict:
    """The tool's own `design_params`, or an empty dict."""
    try:
        return json.loads((tool_dir / "settings.json").read_text()).get("design_params") or {}
    except (OSError, ValueError):
        return {}


def _declared_total(tool_dir: Path):
    """The count this tool was given, from its own settings.json."""
    params = _settings_params(tool_dir)
    for key in _COUNT_KEYS:
        value = params.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return None


def _log_dirs(run_dir: Path) -> list:
    """Where to look for this arm's log.

    Campaign logs live outside the run directory and are named after the box and
    the attempt (`bm4_ph_v2.log`), not after the tool -- so the directory list is
    configurable and attribution is by content, not by filename.
    """
    dirs = [Path(run_dir) / "logs"]
    extra = os.environ.get("BINDERSCOUT_LOG_DIRS", "")
    dirs += [Path(d) for d in extra.split(os.pathsep) if d]
    return [d for d in dirs if d.is_dir()]


def _tail(path: Path, limit: int = 8192) -> str:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - limit))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _rows(path: Path) -> int:
    """Data rows in a CSV, tolerating a truncated or header-only file."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return max(0, sum(1 for _ in fh) - 1)
    except OSError:
        return 0


def _activity_mtime(tool_dir: Path):
    """Newest write anywhere in the arm, counted or not.

    BoltzGen writes thousands of intermediates and no counted design for hours.
    Those intermediates are the only evidence the arm is working, so they set the
    "last ..." clock -- while being kept out of `mtimes`, which feeds cadence and
    must see finished designs only.
    """
    newest = None
    try:
        for child in tool_dir.rglob("*"):
            try:
                if not child.is_file():
                    continue
                m = child.stat().st_mtime
            except OSError:
                continue
            if newest is None or m > newest:
                newest = m
    except OSError:
        return None
    return newest


def _stat_mtimes(paths: list) -> list:
    out = []
    for p in paths:
        try:
            out.append(p.stat().st_mtime)
        except OSError:
            continue
    return sorted(out)


def _log_warnings(run_dir: Path, tool: str) -> list:
    """Surface run_arm.sh's own END/FAILED markers, wherever the log happens to live.

    The marker carries the tool name INSIDE the file, so a log named after the
    box is still attributed correctly and another tool's log is not. This is how
    the Protein-Hunter OOM of 2026-10-30 should have been seen three hours
    earlier than it was.
    """
    end = re.compile(r"END\s+" + re.escape(tool) + r"\s+rc=(\d+)")
    failed = re.compile(re.escape(tool) + r"\s+FAILED")
    for directory in _log_dirs(run_dir):
        logs = sorted(directory.glob("*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        for log in logs[:50]:
            tail = _tail(log)
            m = end.search(tail)
            if m and m.group(1) != "0":
                return [f"log reports rc={m.group(1)} ({log.name})"]
            if m is None and failed.search(tail):
                return [f"log reports FAILED ({log.name})"]
    return []


def _rfd3_warnings(run_dir: Path) -> list:
    """`|fixed_com|` near zero means infer_ori_strategy: hotspots is missing.

    It fails SILENTLY -- no error, no warning, n_chainbreaks still 0 -- and cost
    304 backbones once. Checked on the first sidecar, as CLAUDE.md prescribes.
    """
    sidecars = sorted((Path(run_dir) / "rfd3" / "diffusion").glob("*.json"))
    if not sidecars:
        return []
    try:
        com = json.loads(sidecars[0].read_text()).get("metrics", {}).get("fixed_com")
    except (OSError, ValueError):
        return []
    if not com:
        return ["rfd3 sidecar carries no metrics.fixed_com"]
    mag = sum(float(x) ** 2 for x in com) ** 0.5
    if mag < _FIXED_COM_FLOOR_A:
        return [f"|fixed_com| {mag:.3f} A -- infer_ori_strategy missing, designs likely void"]
    return []


def probe_tool(tool: str, run_dir: Path, cfg: dict) -> dict:
    """Count a tool's finished designs without parsing any of them.

    Returns done / total / mtimes / started / warnings. `total` is None for a
    tool with no known layout: a guessed denominator is a lie, and None renders
    as "total unknown".
    """
    run_dir = Path(run_dir)
    requested, tool = tool, _ALIASES.get(tool, tool)
    tool_dir = run_dir / tool
    total = _declared_total(tool_dir) or (cfg.get("n_designs") if tool in KNOWN_TOOLS else None)

    paths: list = []
    phase = None
    if tool == "boltzgen":
        done, total, paths, phase = _probe_boltzgen(run_dir, tool_dir, cfg)
    elif tool in _CSV_SOURCES:
        csv_path = run_dir / _CSV_SOURCES[tool]
        done = _rows(csv_path) if csv_path.is_file() else 0
        paths = [csv_path] if csv_path.is_file() else []
    else:
        globs = _FILE_GLOBS.get(tool) or _DIR_GLOBS.get(tool)
        if globs is None:
            # Unknown tool: still report liveness and age, but no denominator.
            paths = [p for p in tool_dir.rglob("*") if p.is_file()]
        else:
            for pattern in globs:
                hits = sorted(run_dir.glob(pattern))
                if hits:
                    paths = hits
                    break
        done = len(paths)

    warnings = _log_warnings(run_dir, tool)
    if tool == "rfd3":
        warnings += _rfd3_warnings(run_dir)

    return {
        "tool": requested,
        "done": done,
        "total": total,
        "mtimes": _stat_mtimes(paths),
        "activity_mtime": _activity_mtime(tool_dir),
        "phase": phase,
        "started": probe_started(tool_dir),
        "warnings": warnings,
    }
