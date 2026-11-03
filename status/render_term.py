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
    them. Without this, a finished arm on host-a also renders as `queued` on the
    four boxes whose copy of the directory is empty -- ten noise rows per box,
    burying the two that matter.
    """
    return bool(
        arm.get("started") or (arm.get("done") or 0) > 0 or (arm.get("proc") or {}).get("alive") or arm.get("warnings")
    )


def _rows(doc):
    """Flatten hosts -> runs into campaign-first rows, one row per real arm.

    Dedup stays keyed on (run, tool): a campaign can hold two RFD3 runs -- a
    first batch and a larger second one -- and collapsing on (campaign, tool)
    would hide one of them. Grouping happens afterwards, on the label.
    """
    labels = doc.get("campaigns") or {}
    seen = {}
    for host, result in doc.get("hosts", {}).items():
        if not result.get("reachable"):
            continue
        for run_name, run in (result.get("runs") or {}).items():
            for tool, arm in (run.get("tools") or {}).items():
                seen.setdefault((run_name, tool), []).append((host, arm))

    by_group = {}
    members = {}
    for (run_name, tool), candidates in seen.items():
        evidence = [(h, a) for h, a in candidates if _has_evidence(a)]
        if evidence:
            rows = [(h, tool, a) for h, a in evidence]
        else:
            # Started nowhere: genuinely not launched yet, so say so once.
            rows = [("-", tool, candidates[0][1])]
        group = labels.get(run_name, run_name)
        by_group.setdefault(group, []).extend(rows)
        members.setdefault(group, []).append(run_name)
    return by_group, members


def _deadline_for(doc, group, member_runs):
    """A campaign's deadline, keyed by its label or by any run inside it."""
    due = doc.get("deadlines") or {}
    if group in due:
        return due[group]
    for run in member_runs:
        if run in due:
            return due[run]
    return None


def render(doc: dict, color: bool = False) -> str:
    def paint(text, state):
        return f"{_COLOR.get(state, '')}{text}{_RESET}" if color else text

    out = []
    stamp = doc.get("generated_at", "")
    out.append(f"{_BOLD if color else ''}BinderScout campaign status{_RESET if color else ''}   {stamp}")

    by_run, members = _rows(doc)
    for run_name in sorted(by_run):
        arms = sorted(by_run[run_name], key=lambda r: r[1])
        out.append("")
        head = f"{_BOLD if color else ''}{run_name}{_RESET if color else ''}"
        iso = _deadline_for(doc, run_name, members.get(run_name, []))
        if iso:
            head += f"   due {iso[:10]}"
        out.append(head)

        designs = 0
        live = 0
        finished = 0
        gone = 0
        for host, tool, arm in arms:
            state = arm.get("state", QUEUED)
            done, total = arm.get("done", 0), arm.get("total")
            designs += done or 0
            live += 1 if state == RUNNING else 0
            finished += 1 if state == DONE else 0
            gone += 1 if state == DEAD else 0

            count = f"{done}/{total}" if total else f"{done}/?"
            # BoltzGen spends hours generating raw designs before any are
            # banked; without the phase, both numbers read as "designs".
            phase = arm.get("phase")
            bits = []
            gpu = (arm.get("proc") or {}).get("gpu_mem_mib")
            if state == RUNNING and gpu:
                bits.append(f"gpu {gpu / 1024:.1f}GiB")
            if arm.get("eta_s"):
                bits.append(f"~{_duration(arm['eta_s'])} left")
            if arm.get("output_age_s") is not None:
                bits.append(f"last {_duration(arm['output_age_s'])}")
            if phase:
                bits.insert(0, phase)
            out.append(
                f"  {tool:<18s} {host:<6s} {_bar(done, total)} {count:>8s}  "
                f"{paint(_LABEL.get(state, state), state):<9s} {'  '.join(bits)}".rstrip()
            )
            for w in arm.get("warnings") or []:
                out.append(f"  {'':<18s} {'':<6s} {paint('! ' + w, DEAD)}")

        out.append(f"  {'-' * 56}")
        tail = f"  {designs} designs banked   {live} running   {finished} done"
        if gone:
            tail += f"   {paint(str(gone) + ' dead', DEAD)}"
        tail += f"   {len(arms)} arms"
        out.append(tail)

    down = [(h, r.get("error", "")) for h, r in doc.get("hosts", {}).items() if not r.get("reachable")]
    if down:
        out.append("")
        for host, err in sorted(down):
            out.append(paint(f"  {host:<6s} unreachable  {err}", DEAD))

    if not by_run and not down:
        out.append("")
        out.append("  no runs found")
    return "\n".join(out) + "\n"
