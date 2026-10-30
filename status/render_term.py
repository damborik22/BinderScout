"""ANSI renderer. Campaign-first, because that is the question being asked."""

from status.schema import DEAD, DONE, QUEUED, RUNNING

_BAR_CELLS = 10

_COLOR = {
    DONE: "\033[32m",
    RUNNING: "\033[36m",
    DEAD: "\033[31m",
    QUEUED: "\033[90m",
}
_RESET = "\033[0m"
_BOLD = "\033[1m"

_LABEL = {DONE: "done", RUNNING: "running", DEAD: "DEAD", QUEUED: "queued"}


def _bar(done, total) -> str:
    if not total:
        return "[" + "?".center(_BAR_CELLS) + "]"
    filled = min(_BAR_CELLS, int(_BAR_CELLS * done / total))
    return "[" + "#" * filled + "-" * (_BAR_CELLS - filled) + "]"


def _duration(seconds) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds / 3600:.1f}h"


def _has_evidence(arm) -> bool:
    """Did this arm ever actually run on this box?

    Every box carries the run directory, but each arm runs on exactly one of
    them. Without this, a finished arm on bm1 also renders as `queued` on the
    four boxes whose copy of the directory is empty -- ten noise rows per box,
    burying the two that matter.
    """
    return bool(
        arm.get("started") or (arm.get("done") or 0) > 0 or (arm.get("proc") or {}).get("alive") or arm.get("warnings")
    )


def _rows(doc):
    """Flatten hosts -> runs into campaign-first rows, one row per real arm."""
    seen = {}
    for host, result in doc.get("hosts", {}).items():
        if not result.get("reachable"):
            continue
        for run_name, run in (result.get("runs") or {}).items():
            for tool, arm in (run.get("tools") or {}).items():
                seen.setdefault((run_name, tool), []).append((host, arm))

    by_run = {}
    for (run_name, tool), candidates in seen.items():
        evidence = [(h, a) for h, a in candidates if _has_evidence(a)]
        if evidence:
            rows = [(h, tool, a) for h, a in evidence]
        else:
            # Started nowhere: genuinely not launched yet, so say so once.
            rows = [("-", tool, candidates[0][1])]
        by_run.setdefault(run_name, []).extend(rows)
    return by_run


def render(doc: dict, color: bool = False) -> str:
    def paint(text, state):
        return f"{_COLOR.get(state, '')}{text}{_RESET}" if color else text

    out = []
    stamp = doc.get("generated_at", "")
    out.append(f"{_BOLD if color else ''}BinderScout campaign status{_RESET if color else ''}   {stamp}")

    by_run = _rows(doc)
    for run_name in sorted(by_run):
        arms = sorted(by_run[run_name], key=lambda r: r[1])
        out.append("")
        out.append(f"{_BOLD if color else ''}{run_name}{_RESET if color else ''}")

        designs = 0
        live = 0
        for host, tool, arm in arms:
            state = arm.get("state", QUEUED)
            done, total = arm.get("done", 0), arm.get("total")
            designs += done or 0
            live += 1 if state == RUNNING else 0

            count = f"{done}/{total}" if total else f"{done}/?"
            bits = []
            gpu = (arm.get("proc") or {}).get("gpu_mem_mib")
            if state == RUNNING and gpu:
                bits.append(f"gpu {gpu / 1024:.1f}GiB")
            if arm.get("eta_s"):
                bits.append(f"~{_duration(arm['eta_s'])} left")
            if arm.get("output_age_s") is not None:
                bits.append(f"last {_duration(arm['output_age_s'])}")
            out.append(
                f"  {tool:<18s} {host:<6s} {_bar(done, total)} {count:>8s}  "
                f"{paint(_LABEL.get(state, state), state):<9s} {'  '.join(bits)}".rstrip()
            )
            for w in arm.get("warnings") or []:
                out.append(f"  {'':<18s} {'':<6s} {paint('! ' + w, DEAD)}")

        out.append(f"  {'-' * 56}")
        out.append(f"  {designs} designs   {live} of {len(arms)} arms running")

    down = [(h, r.get("error", "")) for h, r in doc.get("hosts", {}).items() if not r.get("reachable")]
    if down:
        out.append("")
        for host, err in sorted(down):
            out.append(paint(f"  {host:<6s} unreachable  {err}", DEAD))

    if not by_run and not down:
        out.append("")
        out.append("  no runs found")
    return "\n".join(out) + "\n"
