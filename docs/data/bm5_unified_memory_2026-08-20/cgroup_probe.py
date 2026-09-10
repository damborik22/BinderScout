#!/usr/bin/env python3
"""Probe: are NVRM/CUDA allocations charged to the caller's cgroup v2 memcg on GB10?

Run inside a systemd --user scope with MemoryMax set.  Allocates device memory in
STEP_MIB increments up to MAX_MIB; after each step records the scope's
memory.current/peak/events, cudaMemGetInfo free, and system MemAvailable.
Every line is flushed+fsynced so the record survives an OOM kill or a driver wedge.
"""

import ctypes
import os
import sys
import time

STEP_MIB = int(os.environ.get("STEP_MIB", 512))
MAX_MIB = int(os.environ.get("MAX_MIB", 12288))
LOG = os.environ.get("PROBE_LOG", "/tmp/cgroup_probe.log")

log = open(LOG, "w")


def say(msg):
    print(msg)
    sys.stdout.flush()
    log.write(msg + "\n")
    log.flush()
    os.fsync(log.fileno())


# --- locate our own cgroup ---------------------------------------------------
cg = "/sys/fs/cgroup" + open("/proc/self/cgroup").read().strip().split(":")[-1]


def cgread(f, default="?"):
    try:
        return open(os.path.join(cg, f)).read().strip()
    except OSError:
        return default


def cgnum(f):
    v = cgread(f, "0").split()[0]
    try:
        return int(v) / 2**20  # MiB
    except ValueError:
        return -1


say(f"cgroup      : {cg}")
say(f"memory.max  : {cgread('memory.max')}  (bytes; 'max' = unlimited => TEST IS VACUOUS)")
say(f"memory.swap.max: {cgread('memory.swap.max')}")
say(f"baseline memory.current: {cgnum('memory.current'):.0f} MiB")

# --- CUDA runtime ------------------------------------------------------------
rt = None
for lib in ("libcudart.so", "libcudart.so.13", "libcudart.so.12"):
    try:
        rt = ctypes.CDLL(lib)
        break
    except OSError:
        continue
if rt is None:
    say("FATAL: no libcudart")
    sys.exit(2)

rt.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
rt.cudaMalloc.restype = ctypes.c_int
rt.cudaMemset.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
rt.cudaMemset.restype = ctypes.c_int
rt.cudaMemGetInfo.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
rt.cudaGetErrorString.restype = ctypes.c_char_p
rt.cudaDeviceSynchronize.restype = ctypes.c_int


def cuda_free_mib():
    f, t = ctypes.c_size_t(), ctypes.c_size_t()
    rt.cudaMemGetInfo(ctypes.byref(f), ctypes.byref(t))
    return f.value / 2**20


def mem_available_mib():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable"):
            return int(line.split()[1]) / 1024
    return -1


say(f"baseline cuda free: {cuda_free_mib():.0f} MiB | MemAvailable: {mem_available_mib():.0f} MiB")
say("")
say(f"{'alloc_MiB':>10} {'cg.current':>11} {'cg.peak':>9} {'cuda_free':>10} {'MemAvail':>9}  rc")

held, total = [], 0
step_bytes = STEP_MIB * 2**20
while total < MAX_MIB:
    p = ctypes.c_void_p()
    rc = rt.cudaMalloc(ctypes.byref(p), step_bytes)
    if rc != 0:
        msg = rt.cudaGetErrorString(rc).decode()
        say(f"{total + STEP_MIB:>10} {'-':>11} {'-':>9} {'-':>10} {'-':>9}  FAIL rc={rc} ({msg})")
        break
    # touch it -- on unified memory the physical pages may only land on first write
    rt.cudaMemset(p, 1, step_bytes)
    rt.cudaDeviceSynchronize()
    held.append(p)
    total += STEP_MIB
    say(
        f"{total:>10} {cgnum('memory.current'):>11.0f} {cgnum('memory.peak'):>9.0f} "
        f"{cuda_free_mib():>10.0f} {mem_available_mib():>9.0f}  ok"
    )
    time.sleep(0.05)

say("")
say(f"final memory.events: {cgread('memory.events').replace(chr(10), ' | ')}")
say(f"total device MiB held: {total}")
