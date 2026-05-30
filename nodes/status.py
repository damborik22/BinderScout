#!/usr/bin/env python3
"""
BindMaster nodes — show GPU/process status across configured hosts.

Fans out `ssh + nvidia-smi` to each host in parallel and prints one row per GPU.
Stdlib only; no daemon, no shared state — just ssh.

Config: ~/.bindmaster/nodes.json (auto-created with BM1/2/4 on first run).
Schema:
    {
      "nodes": [
        {"name": "bm1", "host": "bm1"},
        {"name": "bm2", "host": "bm2", "ssh_user": "alice"}
      ]
    }
- "host" is whatever you'd pass to `ssh` (hostname, IP, or ~/.ssh/config alias).
- "ssh_user" is optional; if omitted, ssh's own defaults apply.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
RESET = "\033[0m"

DEFAULT_CONFIG = Path.home() / ".bindmaster" / "nodes.json"

DEFAULT_NODES = {
    "nodes": [
        {"name": "bm1", "host": "bm1"},
        {"name": "bm2", "host": "bm2"},
        {"name": "bm4", "host": "bm4"},
    ]
}

# Single ssh roundtrip: gather GPU info + compute procs + pid→user mapping.
REMOTE_PROBE = r"""
echo '===GPU==='
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu \
           --format=csv,noheader,nounits 2>/dev/null || echo 'NO_NVIDIA_SMI'
echo '===PROC==='
nvidia-smi --query-compute-apps=pid,process_name,used_memory \
           --format=csv,noheader,nounits 2>/dev/null
echo '===PS==='
ps -eo pid,user:32,comm= --no-headers 2>/dev/null
"""


@dataclass
class GPU:
    index: int
    name: str
    mem_used_mib: int
    mem_total_mib: int
    util_pct: int


@dataclass
class GPUProc:
    pid: int
    user: str
    process: str
    mem_mib: int


@dataclass
class NodeStatus:
    name: str
    host: str
    reachable: bool = False
    error: str | None = None
    gpus: list[GPU] = field(default_factory=list)
    procs: list[GPUProc] = field(default_factory=list)


def load_config(path: Path) -> list[dict]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_NODES, indent=2) + "\n")
        print(f"{YELLOW}Created default config: {path}{RESET}", file=sys.stderr)
        print(f"{DIM}Edit it to add/remove hosts.{RESET}", file=sys.stderr)
    data = json.loads(path.read_text())
    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError(f"{path}: 'nodes' must be a list")
    return nodes


def probe_host(node: dict, timeout: int) -> NodeStatus:
    name = node["name"]
    host = node["host"]
    user = node.get("ssh_user")
    target = f"{user}@{host}" if user else host

    status = NodeStatus(name=name, host=host)

    connect_timeout = max(timeout - 3, 3)
    cmd = [
        "ssh",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "LogLevel=ERROR",
        target,
        "bash -s",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=REMOTE_PROBE,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        status.error = f"timeout after {timeout}s"
        return status

    if result.returncode != 0:
        stderr = (result.stderr or "").strip().splitlines()
        status.error = stderr[-1] if stderr else f"ssh exit {result.returncode}"
        return status

    status.reachable = True
    _parse_probe(result.stdout, status)
    return status


def _parse_probe(stdout: str, status: NodeStatus) -> None:
    section: str | None = None
    gpu_lines: list[str] = []
    proc_lines: list[str] = []
    ps_lines: list[str] = []
    for line in stdout.splitlines():
        if line == "===GPU===":
            section = "gpu"
            continue
        if line == "===PROC===":
            section = "proc"
            continue
        if line == "===PS===":
            section = "ps"
            continue
        if section == "gpu":
            gpu_lines.append(line)
        elif section == "proc":
            proc_lines.append(line)
        elif section == "ps":
            ps_lines.append(line)

    if any("NO_NVIDIA_SMI" in line for line in gpu_lines):
        status.error = "nvidia-smi unavailable"
        return

    for line in gpu_lines:
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            status.gpus.append(
                GPU(
                    index=int(parts[0]),
                    name=parts[1],
                    mem_used_mib=int(parts[2]),
                    mem_total_mib=int(parts[3]),
                    util_pct=int(parts[4]),
                )
            )
        except ValueError:
            continue

    pid_to_user: dict[int, str] = {}
    for line in ps_lines:
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid_to_user[int(parts[0])] = parts[1]
        except ValueError:
            continue

    for line in proc_lines:
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            mem_mib = int(parts[2]) if parts[2].isdigit() else 0
        except ValueError:
            continue
        status.procs.append(
            GPUProc(
                pid=pid,
                user=pid_to_user.get(pid, "?"),
                process=parts[1],
                mem_mib=mem_mib,
            )
        )


def classify(gpu: GPU) -> tuple[str, str]:
    """Return (label, ansi_color) — one of FREE / PARTIAL / BUSY."""
    free_mib = gpu.mem_total_mib - gpu.mem_used_mib
    if gpu.util_pct < 5 and gpu.mem_used_mib < 1024:
        return "FREE", GREEN
    if gpu.util_pct < 50 and free_mib > 8 * 1024:
        return "PARTIAL", YELLOW
    return "BUSY", RED


def _short_name(gpu_name: str) -> str:
    return gpu_name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")


def _fmt_gib(mib: int) -> str:
    return f"{mib / 1024:.1f}"


def render_table(statuses: list[NodeStatus]) -> None:
    headers = ["NODE", "GPU", "FREE VRAM", "UTIL", "USER", "PROCESS", "STATUS"]
    rows: list[list[str]] = []
    status_colors: list[str] = []

    for st in statuses:
        if not st.reachable:
            rows.append([st.name, "-", "-", "-", "-", "-", st.error or "unreachable"])
            status_colors.append(RED)
            continue
        if not st.gpus:
            rows.append([st.name, "-", "-", "-", "-", "-", "no GPU"])
            status_colors.append(DIM)
            continue

        for gpu in st.gpus:
            label, color = classify(gpu)
            free_gib = _fmt_gib(gpu.mem_total_mib - gpu.mem_used_mib)
            total_gib = _fmt_gib(gpu.mem_total_mib)
            top = max(st.procs, key=lambda p: p.mem_mib, default=None)
            if top is None or label == "FREE":
                user = "-"
                proc_label = "-"
            else:
                user = top.user
                proc_label = f"{top.process} (pid {top.pid})"
            rows.append(
                [
                    st.name,
                    f"{gpu.index} {_short_name(gpu.name)}",
                    f"{free_gib} / {total_gib} GiB",
                    f"{gpu.util_pct}%",
                    user,
                    proc_label,
                    label,
                ]
            )
            status_colors.append(color)

    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]
    header_line = "  ".join(f"{h:<{w}}" for h, w in zip(headers, widths))
    print(f"{BOLD}{header_line}{RESET}")
    print(f"{DIM}{'  '.join('─' * w for w in widths)}{RESET}")
    for row, color in zip(rows, status_colors):
        cells = [f"{c:<{w}}" for c, w in zip(row, widths)]
        cells[-1] = f"{color}{cells[-1]}{RESET}"
        print("  ".join(cells))


def render_json(statuses: list[NodeStatus]) -> None:
    out = [
        {
            "name": st.name,
            "host": st.host,
            "reachable": st.reachable,
            "error": st.error,
            "gpus": [
                {
                    "index": g.index,
                    "name": g.name,
                    "mem_used_mib": g.mem_used_mib,
                    "mem_total_mib": g.mem_total_mib,
                    "util_pct": g.util_pct,
                }
                for g in st.gpus
            ],
            "procs": [{"pid": p.pid, "user": p.user, "process": p.process, "mem_mib": p.mem_mib} for p in st.procs],
        }
        for st in statuses
    ]
    print(json.dumps(out, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="bindmaster nodes",
        description="Show GPU/process status across configured hosts (ssh + nvidia-smi).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Path to nodes.json (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of a table")
    parser.add_argument("--timeout", type=int, default=8, help="Per-host ssh timeout in seconds (default: 8)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel ssh workers (default: 8)")
    args = parser.parse_args()

    if shutil.which("ssh") is None:
        print(f"{RED}✗ ssh not found in PATH{RESET}", file=sys.stderr)
        return 1

    nodes = load_config(args.config)
    if not nodes:
        print(f"{RED}✗ no nodes configured in {args.config}{RESET}", file=sys.stderr)
        return 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe_host, n, args.timeout): n for n in nodes}
        results: dict[str, NodeStatus] = {}
        for fut in concurrent.futures.as_completed(futures):
            node = futures[fut]
            results[node["name"]] = fut.result()

    ordered = [results[n["name"]] for n in nodes if n["name"] in results]
    if args.json:
        render_json(ordered)
    else:
        render_table(ordered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
