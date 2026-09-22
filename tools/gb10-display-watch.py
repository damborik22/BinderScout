#!/usr/bin/env python3
"""gb10-display-watch — detector for the DISPLAY failure mode on DGX Spark (GB10).

This is the counterpart to gb10-guard.py, which watches memory. They cover two INDEPENDENT
failure modes and neither one protects against the other's.

  memory mode (2026-09-17/18)   45 OOM kills, 35-40 NVRM NV_ERR_NO_MEMORY, guard trips,
                                system daemons die -> total freeze
  display mode (2026-09-21)     0 OOM kills, 2 NVRM errors, guard never trips,
                                MemAvailable > 100 GiB the whole time,
                                nvidia-modeset stuck in D state >122 s, then gnome-shell
                                dies with code=dumped status=5/TRAP

The second one cost a hard reset and a lost desktop session with memory completely healthy.
gpurun, the MPS cap and gb10-guard all did their jobs correctly and the desktop died anyway.
Compute and display share one GPU, and rustdesk holds a persistent CUDA compute context, so
they are never cleanly separated; a long compute job starves or wedges the KMS/compositor path.

WHY THIS ONLY WATCHES
---------------------
gb10-guard kills because a memory runaway takes the entire machine down with it -- the job is
lost either way, so killing it early is strictly better. That reasoning does NOT transfer here.
Losing the desktop is survivable (SSH stays up), while killing a design campaign to save a
compositor may be the wrong trade -- and only the operator knows which. So by default this
logs, warns the user, and leaves the decision alone. --kill-on-crit is opt-in.

WHAT IT GIVES YOU
  1. EARLY WARNING for the rule in CLAUDE.md ("no sustained GPU compute while someone is using
     the desktop"), fired while the desktop is still alive and the job can still be stopped
     cleanly.
  2. ONSET RECORD when the signature appears, with a full timestamped snapshot -- so the next
     post-mortem reads a file instead of reconstructing from a journal with a dead RTC.
"""

import ctypes
import json
import os
import subprocess
import sys
import time

POLL_S = float(os.environ.get("GB10_DW_POLL_S", 5.0))
D_WARN_S = float(os.environ.get("GB10_DW_D_WARN_S", 30.0))
D_CRIT_S = float(os.environ.get("GB10_DW_D_CRIT_S", 60.0))
UTIL_BUSY_PCT = float(os.environ.get("GB10_DW_UTIL_BUSY_PCT", 50.0))
SUSTAINED_S = float(os.environ.get("GB10_DW_SUSTAINED_S", 600.0))  # 10 min of compute
RENOTIFY_S = float(os.environ.get("GB10_DW_RENOTIFY_S", 1800.0))
KILL_ON_CRIT = os.environ.get("GB10_DW_KILL_ON_CRIT", "").lower() in ("1", "true", "yes")


def _writable(path):
    d = os.path.dirname(path)
    return os.access(d, os.W_OK) if os.path.isdir(d) else False


# This watcher needs NO privilege -- every /proc/<pid>/stat it reads is world-readable and NVML
# needs no root -- so it runs as a --user unit, which is also what lets notify-send reach the
# desktop. Fall back to user-writable paths rather than demanding root just to log.
_RUN = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
LOG_PATH = os.environ.get("GB10_DW_LOG") or (
    "/var/log/gb10-display-watch.log"
    if _writable("/var/log/x")
    else os.path.expanduser("~/.local/state/gb10-display-watch.log")
)
STATE_PATH = os.environ.get("GB10_DW_STATE") or (
    "/run/gb10-guard/display-state" if _writable("/run/gb10-guard/x") else f"{_RUN}/gb10-display-state"
)
JOB_DIR = "/run/gb10-guard/jobs"

# The display/KMS path. If any of these sits in D (uninterruptible) for D_CRIT_S, the GPU is not
# servicing the display side -- that is the 09-21 signature.
WATCH_COMMS = (
    "nvidia-modeset/kthread_q",
    "nvidia-modeset/deferred_close_kthread_q",
    "Xorg",
    "gnome-shell",
    "mutter-x11-fram",
    "gdm-x-session",
    "nvidia",
)


def boottime():
    return time.clock_gettime(time.CLOCK_BOOTTIME)


_logf = None


def log(msg):
    line = f"[{boottime():12.3f}] {msg}"
    print(line, flush=True)
    global _logf
    try:
        if _logf is None:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            _logf = open(LOG_PATH, "a", buffering=1)
            try:
                os.chmod(LOG_PATH, 0o644)
            except OSError:
                pass
        _logf.write(line + "\n")
        _logf.flush()
        os.fsync(_logf.fileno())
    except OSError:
        pass


def proc_state(pid):
    """(state_char, comm) from /proc/<pid>/stat. World-readable, so no privilege needed."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            data = fh.read()
        rp = data.rindex(b")")
        return data[rp + 2 : rp + 3].decode(), data[data.index(b"(") + 1 : rp].decode()
    except (OSError, ValueError):
        return None, None


def watched_pids():
    out = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        st, comm = proc_state(int(entry))
        if comm and comm in WATCH_COMMS:
            out[int(entry)] = (st, comm)
    return out


def desktop_active():
    """True if a graphical session is active. Cheap: read sysfs/loginctl state, no fork if we can
    avoid it -- but loginctl is only consulted at startup-ish cadence by the caller."""
    try:
        r = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            f = line.split()
            if len(f) >= 4 and "seat" in line and ("tty" in line or "x11" in line):
                s = subprocess.run(
                    ["loginctl", "show-session", f[0], "-p", "Active", "-p", "Type"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout
                if "Active=yes" in s and ("Type=x11" in s or "Type=wayland" in s):
                    return True
    except (OSError, subprocess.SubprocessError):
        pass
    return False


class NVML:
    """Utilisation and compute-client list with NO fork. nvidia-smi would have to fault its binary
    in from NVMe at exactly the moment the GPU path is wedged."""

    def __init__(self):
        self.lib = None
        self.h = None
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
            self.lib, self.h = lib, h
            log("NVML initialised")
            return True
        except OSError:
            return False

    def util(self):
        if not self.init():
            return None

        class U(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        u = U()
        if self.lib.nvmlDeviceGetUtilizationRates(self.h, ctypes.byref(u)) != 0:
            return None
        return int(u.gpu)

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
        self.lib.nvmlDeviceGetComputeRunningProcesses_v3(self.h, ctypes.byref(n), None)
        if n.value == 0:
            return {}
        arr = (P * (n.value + 8))()
        n = ctypes.c_uint(n.value + 8)
        if self.lib.nvmlDeviceGetComputeRunningProcesses_v3(self.h, ctypes.byref(n), arr) != 0:
            return {}
        return {
            int(arr[i].pid): int(arr[i].usedGpuMemory // (1024 * 1024)) for i in range(n.value) if arr[i].usedGpuMemory
        }


def comm_of(pid):
    try:
        with open(f"/proc/{pid}/comm") as fh:
            return fh.read().strip()
    except OSError:
        return "?"


def meminfo_mib():
    want = {b"MemFree:": 0, b"MemAvailable:": 0}
    try:
        with open("/proc/meminfo", "rb") as fh:
            for raw in fh:
                k = raw.split(maxsplit=1)[0]
                if k in want:
                    want[k] = int(raw.split()[1]) // 1024
    except OSError:
        pass
    return want[b"MemFree:"], want[b"MemAvailable:"]


def notify(title, body):
    """Warn the person at the keyboard while the desktop still works. Best-effort."""
    for cmd in (["notify-send", "-u", "critical", title, body], ["wall", f"{title}: {body}"]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
            return
        except (OSError, subprocess.SubprocessError):
            continue


def snapshot(reason, extra):
    """The forensic payload. The RTC on this box is dead, so everything is keyed on CLOCK_BOOTTIME
    plus the boot id -- wall-clock timestamps do not survive a reboot here."""
    try:
        with open("/proc/sys/kernel/random/boot_id") as fh:
            boot_id = fh.read().strip()
    except OSError:
        boot_id = "?"
    free, avail = meminfo_mib()
    rec = {
        "boottime": round(boottime(), 3),
        "boot_id": boot_id,
        "reason": reason,
        "mem_free_mib": free,
        "mem_available_mib": avail,
        "note": (
            "DISPLAY-path event. Distinguish from the memory mode: if mem_available_mib is "
            "high and gb10-guard did not trip, this is NOT a memory problem and no memory "
            "control would have prevented it. See the 'OTHER failure mode' section in "
            "~/.claude/CLAUDE.md"
        ),
    }
    rec.update(extra)
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(rec, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATE_PATH)
        os.chmod(STATE_PATH, 0o644)
    except OSError:
        pass
    return rec


def main():
    nvml = NVML()
    d_since = {}  # pid -> boottime when it entered D
    reported = set()  # pids already reported at CRIT this episode
    busy_since = None  # when sustained compute began
    last_notify = 0.0
    desktop = False
    last_desktop_check = 0.0

    log(
        f"gb10-display-watch up: poll={POLL_S}s d_warn={D_WARN_S}s d_crit={D_CRIT_S}s "
        f"busy>{UTIL_BUSY_PCT}% for {SUSTAINED_S / 60:.0f}min, kill_on_crit={KILL_ON_CRIT}"
    )

    while True:
        time.sleep(POLL_S)
        now = boottime()

        if now - last_desktop_check > 30:
            desktop = desktop_active()
            last_desktop_check = now

        # ---- 1. onset detection: the display path stuck in uninterruptible sleep -------------
        pids = watched_pids()
        for pid, (st, comm) in pids.items():
            if st == "D":
                d_since.setdefault(pid, now)
                held = now - d_since[pid]
                if held >= D_CRIT_S and pid not in reported:
                    reported.add(pid)
                    _free, avail = meminfo_mib()
                    snapshot(
                        "display_path_uninterruptible",
                        {
                            "pid": pid,
                            "comm": comm,
                            "d_state_seconds": round(held, 1),
                            "gpu_util_pct": nvml.util(),
                            "compute_clients": {
                                str(p): {"comm": comm_of(p), "mib": m} for p, m in nvml.compute_procs().items()
                            },
                        },
                    )
                    log(
                        f"CRITICAL: {comm} (pid {pid}) in D state for {held:.0f}s — display path "
                        f"is wedged. MemAvailable {avail} MiB (memory is NOT the problem). "
                        f"Snapshot -> {STATE_PATH}"
                    )
                    notify(
                        "GB10: display path wedged",
                        f"{comm} stuck {held:.0f}s. Desktop may die. Stop GPU compute now. Details: {STATE_PATH}",
                    )
                    if KILL_ON_CRIT:
                        for p in nvml.compute_procs():
                            if comm_of(p) not in ("rustdesk", "nvidia-cuda-mps-server"):
                                log(f"--kill-on-crit: SIGTERM {p} ({comm_of(p)})")
                                try:
                                    os.kill(p, 15)
                                except OSError:
                                    pass
                elif held >= D_WARN_S and pid not in reported:
                    log(f"watch: {comm} (pid {pid}) in D state {held:.0f}s")
            else:
                if pid in d_since and now - d_since[pid] >= D_WARN_S:
                    log(f"recovered: {comm} (pid {pid}) left D state after {now - d_since[pid]:.0f}s")
                d_since.pop(pid, None)
                reported.discard(pid)

        # ---- 2. early warning: the rule, enforced while the desktop is still alive ------------
        util = nvml.util()
        procs = nvml.compute_procs()
        real = {p: m for p, m in procs.items() if comm_of(p) not in ("rustdesk", "nvidia-cuda-mps-server")}

        if real and util is not None and util >= UTIL_BUSY_PCT:
            busy_since = busy_since or now
            if desktop and now - busy_since >= SUSTAINED_S and now - last_notify >= RENOTIFY_S:
                last_notify = now
                who = ", ".join(f"{comm_of(p)}({p}) {m} MiB" for p, m in real.items())
                registered = os.path.isdir(JOB_DIR) and any(os.path.exists(os.path.join(JOB_DIR, str(p))) for p in real)
                log(
                    f"RULE VIOLATION: sustained GPU compute ({util}% for "
                    f"{(now - busy_since) / 60:.0f} min) with an ACTIVE desktop session. "
                    f"Clients: {who}. Registered with gb10-guard: {registered}. "
                    f"Being capped does NOT protect the display path."
                )
                notify(
                    "GB10: compute running against a live desktop",
                    f"{(now - busy_since) / 60:.0f} min of sustained GPU work while the desktop "
                    f"is in use. This is what wedged the compositor on 2026-09-21. "
                    f"Move it to a headless box.",
                )
                snapshot(
                    "sustained_compute_with_active_desktop",
                    {
                        "gpu_util_pct": util,
                        "minutes": round((now - busy_since) / 60, 1),
                        "clients": {str(p): {"comm": comm_of(p), "mib": m} for p, m in real.items()},
                    },
                )
        else:
            busy_since = None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
