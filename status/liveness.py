"""Is the arm actually working? The only continuous signal we have.

Measured 2026-10-30 on the live TfR1 RFD3 arm: 0 designs written, log silent for
664 s, and the GPU at 99% with 6692 MiB held by its PID. The design count and
the log both said "dead"; only the process said "healthy". So liveness is read
from the process table and the GPU, not from output files.

DELIBERATELY NOT using the `-f` full-command-line process matcher: it matches
its own command line, so it reports every arm as running -- including the dead
ones -- which silently defeats the whole module. This is a known trap, and the
reason a queue script should wait with `kill -0`. We scan /proc
ourselves and exclude our own process lineage, which is the part a shell-out
cannot do.
"""

import os
import re
import subprocess
from pathlib import Path


def own_lineage() -> set:
    """This process and every ancestor of it.

    Without this the scan finds ITSELF: our own argv contains both the run
    directory and the tool name, because that is what we were asked about.
    """
    seen = set()
    pid = os.getpid()
    while pid and pid not in seen:
        seen.add(pid)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            # comm may contain spaces and parens; ppid is the field after ')'.
            pid = int(stat[stat.rindex(")") + 1 :].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return seen


def process_table() -> dict:
    """pid -> argv string, excluding our own lineage."""
    mine = own_lineage()
    table = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in mine:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        table[pid] = " ".join(raw.decode("utf-8", errors="replace").split("\0")).strip()
    return table


def gpu_memory_by_pid() -> dict:
    """pid -> MiB held on the GPU, empty when there is no usable nvidia-smi."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            found[int(parts[0])] = int(parts[1])
    return found


def gpus() -> list:
    """Per-card utilisation, for the campaign header."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    cards = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            cards.append(
                {
                    "name": parts[0],
                    "util_pct": int(parts[1]) if parts[1].isdigit() else None,
                    "mem_used_mib": int(parts[2]) if parts[2].isdigit() else None,
                    "mem_total_mib": int(parts[3]) if parts[3].isdigit() else None,
                }
            )
    return cards


def tool_alive(tool: str, run_dir, table: dict | None = None, gpu_mem: dict | None = None) -> dict:
    """Find the process working on this arm.

    Matched on the run directory AND the tool name appearing in the command
    line, because that is how every generated run script invokes its tool
    (`rfd3 design out_dir=<run>/rfd3/diffusion ...`). Our own lineage is already
    excluded by process_table().
    """
    table = process_table() if table is None else table
    gpu_mem = gpu_memory_by_pid() if gpu_mem is None else gpu_mem
    # Match the ARM'S OWN OUTPUT DIRECTORY, not the tool name.
    #
    # BindCraft 2's console script is literally named `bindcraft` (its package
    # imports as `bindcraft` too -- see CLAUDE.md), so no amount of word-boundary
    # cleverness on the executable can tell the two apart: on the live fleet this
    # reported BindCraft as running on a box that was running BindCraft 2. The
    # run directory can: every generated run script passes `<run>/<tool>/...` as
    # its output path, and those paths are unambiguous.
    #
    # The lookahead is load-bearing: `<run>/bindcraft` is a prefix of
    # `<run>/bindcraft2`, and `rfd3` of nothing but the same trap waits there.
    #
    # Both spellings of the path are matched. Generated scripts bake the RESOLVED path,
    # while a run directory reached through a symlinked $HOME or checkout is spelled
    # the other way, and a needle built from only one of them reports a live arm as dead.
    arm = Path(run_dir) / tool
    spellings = dict.fromkeys((str(arm), str(arm.resolve())))
    needle = re.compile("(?:" + "|".join(re.escape(sp) for sp in spellings) + r")(?![A-Za-z0-9])")
    for pid, argv in table.items():
        if needle.search(argv):
            return {"alive": True, "pid": pid, "gpu_mem_mib": gpu_mem.get(pid)}
    return {"alive": False, "pid": None, "gpu_mem_mib": None}
