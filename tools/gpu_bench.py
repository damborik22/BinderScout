#!/usr/bin/env python3
"""Measure peak GPU memory and wall-clock for one refold engine at one size.

WHY THIS MEASURES DEMAND, NOT SUPPLY
------------------------------------
JAX preallocates.  With XLA_PYTHON_CLIENT_PREALLOCATE=true (our production
default, and the right one there) nvidia-smi reports the *pool*, not the working
set -- reserving a fixed fraction of the device regardless of need.  Measuring
that way is exactly how ">=100 GB GPU" entered our docs for AF3, which actually
peaks at ~4.4 GiB for a 258-token complex.  So for JAX engines this harness sets
BINDERSCOUT_XLA_PREALLOCATE=false, the one sanctioned use of that escape hatch
(memory_policy.py: "measuring an engine's true demand").

Peak is sampled from NVML across the whole process tree, because the torch
engines spawn dataloader workers that hold their own CUDA context.

Cold vs warm are reported separately: AF3's first compile was 500 s against
177 s cached on GB10, so a single number would conflate compile with inference.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# A real sequence, tiled to length: keeps amino-acid composition realistic while
# making token count the only variable across the sweep.  CBG / 2VDY chain A.
_SEED = "MPLLLYTCLLWLPTSGLWTVQAMDPNAAYVNMSNHHRGLASANVDFAFSLYKHLVALSPKKNIFISPVSISMALAMLSLGTCGHTRAQLLQGLGFNLTERSETEIHQGFQHLHQLFAKSDTSLEMTMGNALFLDGSLELLESFSADIKHYYESEVLAMNFQDWATASRQINSYVKNKTQGKIVDLFSGLDSPAILVLVNYIFFKGTWTQPFDLASTREENFYVDETTVVKVPMMLQSSTISYLHDSELPCQLVQMNYVGNGTVFFILPDKGKMNTVIAALSRDTINRWSALLPFHLVSNSLYLHYHLVRLPTVQTLKLTKPGQSHLFLHLLTKVFLPFYFDLYRSLYSPKLYSTEGVLSHTNDLLHSLKWDSATLRQMSMFHLSSMYSHTLS"


def tiled(n: int) -> str:
    s = (_SEED * (n // len(_SEED) + 2))[:n]
    return s


def _is_unified_memory() -> bool:
    """True when the GPU pool IS system RAM (GB10 / Grace-Hopper)."""
    import ctypes as _c

    free, total = _c.c_size_t(), _c.c_size_t()
    for lib in ("libcudart.so", "libcudart.so.13", "libcudart.so.12"):
        try:
            rt = _c.CDLL(lib)
        except OSError:
            continue
        try:
            if rt.cudaMemGetInfo(_c.byref(free), _c.byref(total)) == 0 and total.value:
                ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                return abs(total.value - ram) / ram < 0.2
        except (AttributeError, OSError, ValueError):
            pass
        break
    return False


def _wrap_gpurun(cmd: list[str], repo: str, cap_gib: int, disabled: bool) -> list[str]:
    """Route through gpurun when present. NEVER launch an uncapped GPU job on GB10.

    gpurun is not only an MPS cap: it registers the job in /run/gb10-guard/jobs so a
    LATER job can see this one's reservation. A job started outside it is invisible to
    that admission check -- which is how a concurrent pair wedged nvidia-modeset and
    froze this box on 2026-09-21. The freeze had no OOM kills and no guard trip; the
    driver's allocation path failed and a kernel thread hung, which no MemFree
    threshold catches.

    Cost, because it changes what the numbers mean: under MPS, per-process GPU
    attribution collapses onto nvidia-cuda-mps-server, so the NVML peak sampled here
    is not this job's alone. On such a host treat the cap as the memory figure and use
    a reservation sweep for demand.
    """
    gr = Path(repo) / "tools" / "gpurun"
    if disabled or not gr.exists():
        return cmd
    return [str(gr), "--cap", str(cap_gib), "--name", "gpubench", "--", *cmd]


def peak_sampler(root_pid: int, stop: threading.Event, out: dict, hz: float = 5.0):
    """Max summed GPU memory over the process tree, via NVML."""
    peak = 0
    while not stop.is_set():
        try:
            pids = {str(root_pid)}
            tree = subprocess.run(
                ["ps", "-o", "pid=", "--ppid", str(root_pid)], capture_output=True, text=True, timeout=5
            )
            pids |= {l.strip() for l in tree.stdout.splitlines() if l.strip()}
            for p in list(pids):
                g = subprocess.run(["ps", "-o", "pid=", "--ppid", p], capture_output=True, text=True, timeout=5)
                pids |= {l.strip() for l in g.stdout.splitlines() if l.strip()}
            q = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            total = 0
            for line in q.stdout.splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) == 2 and parts[0] in pids and parts[1].isdigit():
                    total += int(parts[1])
            peak = max(peak, total)
        except Exception:
            pass
        stop.wait(1.0 / hz)
    out["peak_mib"] = peak


def run_once(cmd: list[str], env: dict, log: Path) -> tuple[float, int, int]:
    stop = threading.Event()
    res: dict = {}
    with log.open("w") as fh:
        t0 = time.time()
        proc = subprocess.Popen(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT)
        th = threading.Thread(target=peak_sampler, args=(proc.pid, stop, res), daemon=True)
        th.start()
        rc = proc.wait()
        stop.set()
        th.join(timeout=5)
        return time.time() - t0, res.get("peak_mib", 0), rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=["boltz2", "af3", "esmfold2"])
    ap.add_argument("--target-len", type=int, required=True)
    ap.add_argument("--binder-len", type=int, default=60)
    ap.add_argument("--repo", required=True, help="BinderScout checkout")
    ap.add_argument("--python", required=True, help="engine env's python")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument(
        "--measure-demand",
        action="store_true",
        help="PREALLOCATE=false to measure demand; refused on unified-memory hosts",
    )
    ap.add_argument("--cap-gib", type=int, default=24, help="GPU cap handed to gpurun")
    ap.add_argument("--no-gpurun", action="store_true", help="skip gpurun (discrete cards only)")
    a = ap.parse_args()

    wd = Path(a.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    binder = tiled(a.binder_len)
    target = tiled(a.target_len)
    fa = wd / "binder.fasta"
    fa.write_text(f">bench_{a.engine}_{a.target_len}\n{binder}\n")

    script = Path(a.repo) / "Evaluator" / "scripts" / f"refold_{a.engine}.py"
    if not script.exists():
        print(json.dumps({"error": f"missing {script}"}))
        return 2

    env = dict(os.environ)
    env["BINDERSCOUT_ALLOW_NO_MSA"] = "1"
    if a.measure_demand:
        if _is_unified_memory():
            print(json.dumps({"error": "--measure-demand refused on a unified-memory host"}))
            return 2
        env["BINDERSCOUT_XLA_PREALLOCATE"] = "false"
    env["JAX_COMPILATION_CACHE_DIR"] = str(wd / "jaxcache")

    base = [a.python, "-u", str(script), "--sequences", str(fa), "--target-seq", target, "--no-msa", "--allow-no-msa"]
    # refold_boltz2.py takes --output-dir only; it has no -o/--output.
    outs = {
        "boltz2": ["--output-dir", str(wd / "bout")],
        "af3": ["--output", str(wd / "a.csv"), "--output-dir", str(wd / "aout")],
        "esmfold2": ["--output", str(wd / "e.csv"), "--output-dir", str(wd / "eout")],
    }
    cmd = base + outs[a.engine]
    cmd = _wrap_gpurun(cmd, a.repo, a.cap_gib, a.no_gpurun)

    cold_s, cold_peak, rc1 = run_once(cmd, env, wd / f"{a.engine}_{a.target_len}_cold.log")
    warm_s, warm_peak, rc2 = run_once(cmd, env, wd / f"{a.engine}_{a.target_len}_warm.log")

    try:
        gpu = (
            subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            .stdout.strip()
            .splitlines()[0]
        )
    except Exception:
        gpu = "unknown"
    # Report BOTH frameworks: the Mosaic venv has torch installed but the Boltz-2
    # refolder runs on JAX, so probing torch first mislabels the engine's stack.
    probe = (
        "vs = []\n"
        "try:\n"
        "    import jax; vs.append('jax ' + jax.__version__)\n"
        "except Exception: pass\n"
        "try:\n"
        "    import torch; vs.append('torch ' + torch.__version__)\n"
        "except Exception: pass\n"
        "print(' | '.join(vs) or 'unknown')"
    )
    ver = subprocess.run([a.python, "-c", probe], capture_output=True, text=True).stdout.strip()

    print(
        json.dumps(
            {
                "label": a.label,
                "engine": a.engine,
                "gpu": gpu,
                "framework": ver,
                "target_len": a.target_len,
                "binder_len": a.binder_len,
                "tokens": a.target_len + a.binder_len,
                "cold_s": round(cold_s, 1),
                "warm_s": round(warm_s, 1),
                "peak_mib_cold": cold_peak,
                "peak_mib_warm": warm_peak,
                "rc_cold": rc1,
                "rc_warm": rc2,
                "ok": rc1 == 0 and rc2 == 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
