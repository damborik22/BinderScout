#!/usr/bin/env python3
"""gb10-guard — failsafe for DGX Spark (GB10) unified memory.

v2. The v1 design caused a 23-kill cascade on 2026-09-18 and this file is mostly a record of
why. Read the post-mortem before changing any threshold.

BACKGROUND
----------
On GB10 the GPU pool IS system RAM. The NVIDIA resman takes those pages with
GFP_KERNEL | __GFP_NOWARN | __GFP_RETRY_MAYFAIL (nvidia/nv-vm.c:236,258-261): unmovable, on no
LRU, charged to no task and no cgroup, and unable to trigger the OOM killer themselves. So
oom_badness() scores the offending job at ~0 and the kernel shoots system daemons instead —
on 2026-09-17 it fired 45 times and the largest victim held 1280 kB. This daemon exists to
supply the attribution the kernel cannot.

WHAT v1 GOT WRONG (all four are load-bearing; do not reintroduce any of them)

1. IT MEASURED THE EFFECT OF ITS OWN KILL TOO SOON. The driver returns GPU pages
   ASYNCHRONOUSLY. v1 slept 1 s after SIGKILL and re-read MemFree:
       killed 476458 (24738 MiB GPU) -> MemFree 24758 -> 24736   (went DOWN)
       killed 445695 (31353 MiB GPU) -> MemFree 35274 -> 35274   (unchanged)
   Every kill looked like it had failed, so it killed again 2 s later. That is the cascade.
   FIX: after a kill, enter a settle window and do not re-arm until the pages actually come
   back or SETTLE_S elapses.

2. IT TRIPPED ON A METRIC THAT DOES NOT MEAN EXHAUSTION. v1 used MemFree alone, on the theory
   that CUDA cannot use reclaimable page cache. True as far as it goes — but the driver's
   allocation DRIVES reclaim, so page cache is available to it in practice. Measured on an idle
   box: MemFree 53.5 GiB, MemAvailable 99.4 GiB, Cached 55.7 GiB, PSI full avg10 = 0.00. v1
   would have been one bad poll away from killing a job on a completely healthy machine.
   FIX: require MemFree low AND evidence that reclaim is actually failing (PSI stall, or
   MemAvailable also low). Try reclaiming before killing anything.

3. IT HAD NO DEADBAND. "TRIP: MemFree 40940 <= 40960" killed an 11.3 GiB AlphaFold job over a
   20 MiB shortfall.
   FIX: sustained breach over N polls, and the shortfall must exceed DEADBAND_MIB.

4. IT KILLED PROCESSES THAT WERE NOT THE PROBLEM. It killed a client holding 11 MiB, and fell
   back to ranking by anon RSS — which this file's own v1 notes called "precisely backwards" —
   and hit a pt_data_worker. It also killed pxdesign (2.4 GiB, someone else's job) to relieve a
   313 MiB shortfall caused by a different process.
   FIX: victims must hold at least MIN_VICTIM_MIB; prefer whoever is OVER THE BUDGET THEY
   DECLARED, then whoever GREW most recently; never kill on an RSS guess.

THE CENTRAL IDEA IN v2
----------------------
"Biggest" is the wrong question. A 90 GiB job that declared 90 GiB is behaving correctly; a
12 GiB job that declared 8 is not. gpurun and gb10-env register each job's declared budget in
JOB_DIR, and this daemon prefers violators. That is also what makes large single jobs safe to
run at all: the floor is a policy for the shared case, not a law of the machine.
"""

import ctypes
import json
import os
import signal
import sys
import time

# ---------------------------------------------------------------- tunables
FLOOR_MIB = int(os.environ.get("GB10_FLOOR_MIB", 24 * 1024))  # MemFree danger line
AVAIL_FLOOR_MIB = int(os.environ.get("GB10_AVAIL_FLOOR_MIB", 12 * 1024))  # nothing left to reclaim
PSI_FULL_AVG10 = float(os.environ.get("GB10_PSI_FULL_AVG10", 10.0))  # % of time ALL tasks stalled
DEADBAND_MIB = int(os.environ.get("GB10_DEADBAND_MIB", 2048))
SUSTAIN_POLLS = int(os.environ.get("GB10_SUSTAIN_POLLS", 10))  # x POLL_S = how long breached
MIN_VICTIM_MIB = int(os.environ.get("GB10_MIN_VICTIM_MIB", 1024))
POLL_S = float(os.environ.get("GB10_POLL_S", 0.2))
SETTLE_S = float(os.environ.get("GB10_SETTLE_S", 30.0))  # async page return window
RECLAIM_COOLDOWN_S = float(os.environ.get("GB10_RECLAIM_COOLDOWN_S", 120.0))
GRACE_S = float(os.environ.get("GB10_GRACE_S", 120.0))  # newly admitted job grace
NVML_REFRESH_S = float(os.environ.get("GB10_NVML_REFRESH_S", 2.0))
GROWTH_WINDOW_S = float(os.environ.get("GB10_GROWTH_WINDOW_S", 60.0))
DRY_RUN = os.environ.get("GB10_DRY_RUN", "").lower() in ("1", "true", "yes")
ALLOW_RSS_KILL = os.environ.get("GB10_ALLOW_RSS_KILL", "").lower() in ("1", "true", "yes")

LOG_PATH = os.environ.get("GB10_LOG", "/var/log/gb10-guard.log")
STATE_DIR = os.environ.get("GB10_STATE_DIR", "/run/gb10-guard")
JOB_DIR = os.path.join(STATE_DIR, "jobs")  # <pid> -> {"cap_gib":N,"name":...,"started":T}
KILL_FILE = os.path.join(STATE_DIR, "last-kill")

PROTECT_COMMS = {
    "systemd",
    "systemd-journal",
    "systemd-logind",
    "systemd-udevd",
    "sshd",
    "dbus-daemon",
    "Xorg",
    "gnome-shell",
    "mutter-x11-fram",
    "gdm3",
    "gdm-session-wor",
    "gdm-x-session",
    "rustdesk",
    "nvidia-persiste",
    "nvidia-cuda-mps",
    "agetty",
    "login",
    "init",
    "gb10-guard",
}
PROTECT_PIDS = {1, os.getpid()}
MCL_CURRENT, MCL_FUTURE = 1, 2


def boottime():
    return time.clock_gettime(time.CLOCK_BOOTTIME)


_logf = None


def log(msg):
    line = f"[{boottime():12.3f}] {msg}"
    print(line, flush=True)
    global _logf
    try:
        if _logf is None:
            _logf = open(LOG_PATH, "a", buffering=1)
            try:
                os.chmod(LOG_PATH, 0o644)  # the victim must be able to read why it died
            except OSError:
                pass
        _logf.write(line + "\n")
        _logf.flush()
        os.fsync(_logf.fileno())
    except OSError:
        pass


def meminfo():
    """MemFree, MemAvailable, Cached in MiB."""
    want = {b"MemFree:": 0, b"MemAvailable:": 0, b"Cached:": 0}
    with open("/proc/meminfo", "rb") as fh:
        for raw in fh:
            k = raw.split(maxsplit=1)[0]
            if k in want and not (k == b"Cached:" and raw.startswith(b"SwapCached")):
                want[k] = int(raw.split()[1]) // 1024
    return want[b"MemFree:"], want[b"MemAvailable:"], want[b"Cached:"]


def psi_full_avg10():
    try:
        with open("/proc/pressure/memory") as fh:
            for line in fh:
                if line.startswith("full"):
                    for field in line.split():
                        if field.startswith("avg10="):
                            return float(field.split("=", 1)[1])
    except (OSError, ValueError):
        pass
    return 0.0


def try_reclaim():
    """Drop clean page cache and let the kernel settle. Costs refaults; a SIGKILL costs a job.

    Only the page cache (1), never dentries/inodes (2/3) — those are cheap to keep and dropping
    them hurts every subsequent path lookup.
    """
    try:
        with open("/proc/sys/vm/drop_caches", "w") as fh:
            fh.write("1")
        time.sleep(0.5)
        return True
    except OSError as exc:
        log(f"reclaim failed: {exc}")
        return False


# ---------------------------------------------------------------- NVML
class NVML:
    def __init__(self):
        self.lib = None
        self.handle = None
        self.last_try = 0.0

    def init(self):
        if self.lib is not None:
            return True
        if boottime() - self.last_try < 30.0:
            return False
        self.last_try = boottime()
        try:
            lib = ctypes.CDLL("libnvidia-ml.so.1")
            if lib.nvmlInit_v2() != 0:
                return False
            h = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) != 0:
                return False
            self.lib, self.handle = lib, h
            log("NVML initialised")
            return True
        except OSError:
            return False

    def compute_procs(self):
        if not self.init():
            return {}

        class P(ctypes.Structure):
            _fields_ = [
                ("pid", ctypes.c_uint),
                ("usedGpuMemory", ctypes.c_ulonglong),
                ("gpuInstanceId", ctypes.c_uint),
                ("computeInstanceId", ctypes.c_uint),
            ]

        n = ctypes.c_uint(0)
        self.lib.nvmlDeviceGetComputeRunningProcesses_v3(self.handle, ctypes.byref(n), None)
        if n.value == 0:
            return {}
        arr = (P * (n.value + 8))()
        n = ctypes.c_uint(n.value + 8)
        if self.lib.nvmlDeviceGetComputeRunningProcesses_v3(self.handle, ctypes.byref(n), arr) != 0:
            return {}
        return {
            int(arr[i].pid): int(arr[i].usedGpuMemory // (1024 * 1024)) for i in range(n.value) if arr[i].usedGpuMemory
        }


def comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _ppid(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            data = fh.read()
        return int(data[data.rindex(b")") + 2 :].split()[1])  # field 4, past the comm parens
    except (OSError, ValueError, IndexError):
        return 0


def declared_budget(pid):
    """The cap this job registered via gpurun/gb10-env, in MiB, plus its start time.

    Walks up the process tree: a job registers its own pid, but the processes that actually hold
    GPU memory are often children it spawned (protein-hunter forks LigandMPNN every cycle; boltz
    forks pt_data_workers). Without this walk those children look UNREGISTERED and the victim
    ranking would prefer them — which is exactly how v1 came to kill a pt_data_worker.
    """
    seen = 0
    while pid > 1 and seen < 12:
        try:
            with open(os.path.join(JOB_DIR, str(pid))) as fh:
                rec = json.load(fh)
            cap = int(float(rec.get("cap_gib", 0)) * 1024) or None
            return cap, float(rec.get("started", 0))
        except (OSError, ValueError, TypeError):
            pass
        pid = _ppid(pid)
        seen += 1
    return None, 0.0


def is_protected(pid):
    return pid in PROTECT_PIDS or comm(pid) in PROTECT_COMMS


def pick_victim(gpu_map, history, excluded):
    """Rank candidates by how much they are MISBEHAVING, not by how big they are.

    Tier 1: over the budget they declared, by absolute overshoot. A job that declared 90 GiB and
            is using 88 is fine; one that declared 8 and is using 12 is the problem.
    Tier 2: largest growth inside GROWTH_WINDOW_S — whoever is actually moving the number.
    Tier 3: largest absolute holder, but only above MIN_VICTIM_MIB.
    """
    now = boottime()
    cands = []
    for pid, mib in gpu_map.items():
        if pid in excluded or is_protected(pid) or not os.path.exists(f"/proc/{pid}"):
            continue
        if mib < MIN_VICTIM_MIB:
            continue  # 11 MiB clients are never the cause
        cap_mib, started = declared_budget(pid)
        over = (mib - cap_mib) if cap_mib else 0
        hist = history.get(pid, [])
        old = next((m for t, m in hist if now - t <= GROWTH_WINDOW_S), mib)
        growth = mib - old
        fresh = started and (now - started) < GRACE_S
        cands.append((pid, mib, over, growth, cap_mib, fresh))

    overs = [c for c in cands if c[2] > 0]
    if overs:
        c = max(overs, key=lambda c: c[2])
        return c[0], (f"{c[1]} MiB GPU, {c[2]} MiB OVER its declared {c[4]} MiB budget")

    growers = [c for c in cands if c[3] > DEADBAND_MIB and not c[5]]
    if growers:
        c = max(growers, key=lambda c: c[3])
        return c[0], f"{c[1]} MiB GPU, grew {c[3]} MiB in the last {GROWTH_WINDOW_S:.0f}s"

    # Nobody is over budget and nobody is visibly growing. Prefer an unregistered job (it made no
    # promise and we cannot reason about it) over one running inside a declared budget.
    unreg = [c for c in cands if not c[4] and not c[5]]
    pool = unreg or [c for c in cands if not c[5]] or cands
    if pool:
        c = max(pool, key=lambda c: c[1])
        note = (
            "unregistered — launch it via gpurun so it can be reasoned about"
            if not c[4]
            else f"within its declared {c[4]} MiB budget — nothing is misbehaving"
        )
        return c[0], f"{c[1]} MiB GPU, {note}"
    return None, ""


def announce(pid, why, free, avail, psi):
    """Leave a world-readable record. A job that dies to SIGKILL otherwise sees only exit -9,
    indistinguishable from its own crash."""
    rec = {
        "boottime": round(boottime(), 3),
        "pid": pid,
        "comm": comm(pid),
        "reason": why,
        "mem_free_mib": free,
        "mem_available_mib": avail,
        "psi_full_avg10": psi,
        "floor_mib": FLOOR_MIB,
        "explain": (
            "Killed by gb10-guard: GB10 unified memory was exhausted and this process "
            "was the best candidate. See /var/log/gb10-guard.log and "
            "~/dev/BinderScout/docs/GB10_FREEZE_FAILSAFE.md"
        ),
    }
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = KILL_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(rec, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, KILL_FILE)
        os.chmod(KILL_FILE, 0o644)
    except OSError:
        pass


def kill_tree(pid):
    """STOP then KILL. No SIGTERM: a process inside cudaMalloc will not run a Python handler.
    No SIGCONT between them — v1 resumed the tree before TERM and let it keep allocating."""
    if DRY_RUN:
        log(f"DRY_RUN: would SIGSTOP+SIGKILL {pid} ({comm(pid)})")
        return
    for sig, wait in ((signal.SIGSTOP, 0.3), (signal.SIGKILL, 0.0)):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            log(f"ERROR: cannot signal {pid}")
            return
        if wait:
            time.sleep(wait)


def main():
    try:
        ctypes.CDLL("libc.so.6").mlockall(MCL_CURRENT | MCL_FUTURE)
    except OSError:
        log("WARNING: mlockall failed")
    try:
        with open("/proc/self/oom_score_adj", "w") as fh:
            fh.write("-1000")
    except OSError:
        pass
    os.makedirs(JOB_DIR, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o755)
        os.chmod(JOB_DIR, 0o1777)  # jobs self-register unprivileged
    except OSError:
        pass

    nvml = NVML()
    gpu_map, history, excluded = {}, {}, set()
    last_nvml = last_reclaim = 0.0
    breach = 0
    settle_until = 0.0

    log(
        f"gb10-guard v2 up: floor={FLOOR_MIB} MiB MemFree, avail_floor={AVAIL_FLOOR_MIB}, "
        f"psi>{PSI_FULL_AVG10}%, deadband={DEADBAND_MIB}, sustain={SUSTAIN_POLLS} polls, "
        f"settle={SETTLE_S}s, min_victim={MIN_VICTIM_MIB} MiB, dry_run={DRY_RUN}"
    )

    while True:
        time.sleep(POLL_S)
        now = boottime()
        free, avail, cached = meminfo()

        if now - last_nvml >= NVML_REFRESH_S:
            gpu_map = nvml.compute_procs()
            last_nvml = now
            for pid, mib in gpu_map.items():
                history.setdefault(pid, []).append((now, mib))
                history[pid] = [(t, m) for t, m in history[pid] if now - t <= GROWTH_WINDOW_S * 2]
            for pid in list(history):
                if pid not in gpu_map:
                    del history[pid]
            excluded = {p for p in excluded if os.path.exists(f"/proc/{p}")}
            for f in os.listdir(JOB_DIR):  # reap stale registrations
                if f.isdigit() and not os.path.exists(f"/proc/{f}"):
                    try:
                        os.unlink(os.path.join(JOB_DIR, f))
                    except OSError:
                        pass

        # The settle window. The driver returns pages asynchronously, so after a kill we are
        # BLIND for a while — v1's cascade is entirely explained by not waiting here.
        if now < settle_until:
            if free > FLOOR_MIB + DEADBAND_MIB:
                log(f"settled: MemFree recovered to {free} MiB")
                settle_until = 0.0
                breach = 0
            continue

        if free > FLOOR_MIB:
            breach = 0
            continue

        shortfall = FLOOR_MIB - free
        psi = psi_full_avg10()
        # Low MemFree on its own is NOT exhaustion: page cache is reclaimable and the driver's
        # allocation path drives that reclaim. Demand corroboration.
        reclaim_failing = (avail <= AVAIL_FLOOR_MIB) or (psi >= PSI_FULL_AVG10)
        if shortfall <= DEADBAND_MIB or not reclaim_failing:
            breach = 0
            continue

        breach += 1
        if breach < SUSTAIN_POLLS:
            continue

        log(
            f"BREACH sustained: MemFree {free} MiB (floor {FLOOR_MIB}, short {shortfall}), "
            f"MemAvailable {avail}, Cached {cached}, PSI full avg10 {psi:.1f}%"
        )

        # Reclaim is free relative to a SIGKILL. Try it before taking a job.
        if now - last_reclaim >= RECLAIM_COOLDOWN_S and cached > DEADBAND_MIB:
            last_reclaim = now
            log(f"reclaiming page cache ({cached} MiB) before considering a kill")
            if try_reclaim():
                free2, _avail2, _ = meminfo()
                log(f"after reclaim: MemFree {free2} MiB (was {free})")
                if free2 > FLOOR_MIB:
                    log("recovered by reclaim — no kill needed")
                    breach = 0
                    continue

        victim, why = pick_victim(gpu_map, history, excluded)
        if victim is None:
            log(
                "no eligible victim (all protected, below min size, or none registered). "
                "NOT killing — a bad kill costs more than a slow minute."
                + ("" if ALLOW_RSS_KILL else " RSS-based guessing is disabled by default.")
            )
            settle_until = now + SETTLE_S  # back off rather than spin
            breach = 0
            continue

        log(f"KILLING pid {victim} ({comm(victim)}): {why}")
        announce(victim, why, free, avail, psi)
        kill_tree(victim)
        excluded.add(victim)
        settle_until = boottime() + SETTLE_S
        breach = 0
        log(
            f"entering {SETTLE_S:.0f}s settle window — the driver returns GPU pages "
            f"asynchronously, so MemFree will NOT move immediately"
        )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
