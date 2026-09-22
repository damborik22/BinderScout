# GB10 unified-memory freeze — root cause and failsafe

Companion to `PLAN_bm5_unified_memory.md`. Written 2026-09-18 after the 2026-09-17 freeze.
Every claim below was verified on this box or in the shipped driver source; inferences are
marked as such.

## What actually happens

**1. A job is told to take most of the computer, and complies.**
On GB10 there is no framebuffer. `cudaMemGetInfo(total)` == `SC_PHYS_PAGES` == `MemTotal` ==
121.69 GiB, so every *"fraction of device memory"* knob is a fraction of the whole machine.
JAX's default (`preallocate=true`, `MEM_FRACTION=0.75`) reserves **91.3 GiB at import**.
Recorded in `memory_policy.py`: 2026-08-18 AF3 at 0.8 → 97.4 GiB → hard reboot;
2026-08-19 Boltz-2 at the 0.75 default → 91.3 GiB.

**2. Those pages become invisible and irreversible.**
The resman allocates them with `GFP_KERNEL | __GFP_NOWARN | __GFP_RETRY_MAYFAIL`
(`nvidia/nv-vm.c:236,258-261`). That makes them `MIGRATE_UNMOVABLE` and on no LRU:

| property | consequence |
|---|---|
| not on any LRU | not reclaimable, **not swappable**, not compactable |
| no `__GFP_ACCOUNT` anywhere in the RM core | charged to **no process and no cgroup** |
| `__GFP_RETRY_MAYFAIL` | the driver's own allocations **never trigger the OOM killer** |

Measured: 8.00 GiB of `cudaMalloc` inside a `MemoryMax=4G` scope charged **+14.7 MiB** to
`memory.current`, `oom_kill 0`, exit 0. The same 8 GiB came 1:1 out of `MemFree` and landed
in **no** `/proc/meminfo` counter. (Pinned host memory and `cudaMallocManaged` *are* charged
and *were* cleanly cgroup-OOM-killed — so a cgroup cap is real, but only for the host side.)

**3. The kernel then destroys the machine instead of the job.**
`oom_badness()` scores a task by RSS + swapents + pgtables. The offender owns none of the
95–120 GiB, so it scores ≈0. The OOM killer picks the largest *visible* task — a ~1 MB system
daemon — and repeats. From the 2026-09-17 journal, **45** consecutive global OOM kills, of which a sample:

```
bluetoothd  wpa_supplicant  accounts-daemon  smartd  systemd-timesyncd  switcheroo-control
sudo  gdm-x-session  cron ×3  lldpd  avahi-daemon  rtkit-daemon  agetty  nvidia-persistenced
loginctl  dashboard-service  ps
```
The largest anon-rss among all 45 victims was **1280 kB**. Console (`agetty`), display (`gdm-x-session`) and the GPU
persistence daemon are gone; the job is untouched. Meanwhile `nv_alloc_system_pages` sits in
direct reclaim **holding the RM rw-semaphore**, so Xorg and nvidia-modeset block behind it
for 122–491 s. That is the freeze. It is not the OOM killer failing to fire — it is the OOM
killer firing repeatedly and **aiming at the wrong target every time**.

## Why swap is not the fix

At the 2026-09-17 freeze, anon was **268 MiB** of a 121.69 GiB pool and **8.8 GiB of swap was
still free**. 98.5% of the pool was driver-held and structurally unswappable. Swap can only
absorb the host-side term. Worse, a larger swap *lengthens* the interval in which the box is
technically alive but unusable — it converts a prompt kill into a longer thrash.

**Verdict: keep swap at 16 GiB. Do not grow it. Do not add zram.** The 16 GiB is still worth
having for the host-side shape (the 2026-06-05 event: `binder-compare`, 22.6 GiB anon-rss).

## The failsafe, in priority order

Prevention is the fix; everything else is a backstop. Once the pages are taken, nothing —
not cgroups, not the OOM killer, not swap — can get them back.

| # | layer | what it does | file |
|---|---|---|---|
| 0 | **budget before allocation** | every job launched with an explicit GiB cap; refuses if OS headroom < 40 GiB *or* if the cap will not fit in live `MemFree`. Per-tool budgets in `tools/gb10-env.sh:gb10_budget`, applied automatically by the `bin/` wrappers | `tools/gpurun`, `tools/gb10-env.sh` |
| 1 | **driver-enforced ceiling** | MPS per-client pinned limit → clean `RESOURCE_EXHAUSTED` in the job. **Live and proven** 2026-09-18: 4 GiB refused under a 2 GiB cap on 580.159.03 | `~/.config/systemd/user/bindmaster-mps.service` |
| 2 | **reactive guard** | watches `MemFree`, STOPs+KILLs the GPU holder at 40 GiB | `tools/gb10-guard.py` |
| 3 | **widen the window** | `min_free_kbytes` 44 MiB → 2 GiB; `watermark_scale_factor` 10 → 200 | `tools/sysctl/99-gb10-unified-memory.conf` |
| 4 | **host-side backstop** | earlyoom for the anon shape only — it cannot see driver pages | apply stage `earlyoom` |
| 5 | **guaranteed recovery** | PID 1 owns `/dev/watchdog0` → auto-reboot instead of a hard reset | apply stage `watchdog` |

| — | **display-path detector** | separate failure mode entirely; watches for compute starving the compositor | `tools/gb10-display-watch.py` |

The last row is not a memory control and does not belong to the stack above it. See "The OTHER
failure mode" in `~/.claude/CLAUDE.md`: on 2026-09-21 a properly capped, properly registered job
wedged `nvidia-modeset` and killed the desktop with `MemAvailable` above 100 GiB. Every memory
control worked correctly and none of them helped. Install it with
`systemctl --user enable --now gb10-display-watch` (a user unit — it needs no privilege, and the
user session is what lets its warning reach the screen).

Install: `sudo tools/apply-gb10-failsafe.sh [sysctl guard watchdog earlyoom|all]`
Revert:  `sudo tools/revert-gb10-failsafe.sh <same stages>`

## Things that look like solutions and are not

- **`cgroup memory.max` on the GPU job.** Bounds anon/pinned/managed only. Plain `cudaMalloc`
  escapes it entirely. Verified here, not assumed.
- **The `dmem` cgroup controller.** Listed in `cgroup.controllers`, but `dmem.capacity` and
  `dmem.current` are both empty — `nm` on the installed `nvidia.ko` shows zero `dmem_cgroup`
  symbols. Inert on 580.159.03. Re-check after a driver upgrade; if `dmem.capacity` is still
  empty, GB10 registers no DRM memory region and dmem is not a path at any driver version.
- **`XLA_PYTHON_CLIENT_PREALLOCATE=false`.** The dGPU habit, and backwards here: it removes
  the only JAX-side ceiling. On unified memory you *want* the fixed slab that fails at import.
- **`XLA_PYTHON_CLIENT_ALLOCATOR=platform`.** Bypasses BFC, so `MEM_FRACTION` caps nothing.
- **`vm.overcommit_memory=2`.** CUDA/JAX reserve address space with `MAP_NORESERVE`/`PROT_NONE`;
  strict mode fires ENOMEM unpredictably.
- **MGLRU `min_ttl_ms`.** Makes the kernel OOM *more often* — i.e. runs the broken victim
  selection more often. Fix aim before rate.
- **Thresholding a guard on `MemFree` alone.** `cudaMemGetInfo(free)` does track `MemFree`, but
  the driver's allocation path drives reclaim, so page cache *is* available to a starting job.
  Guard v1 tripped at `MemFree ≤ 40 GiB` while 55.7 GiB sat in cache and PSI was flat zero, and
  killed 23 jobs in one afternoon. Trip needs low `MemFree` **and** evidence reclaim is failing.
- **Lowering `vm.swappiness`.** Shrinks reclaimable memory for no benefit against unswappable pages.

## Known gaps

- **MPS breaks per-process GPU attribution** — all client memory is reported against
  `nvidia-cuda-mps-server`. `gb10-guard` falls back to `/dev/nvidia*` fd ownership + anon RSS
  when that happens, but layers 1 and 2 are in tension and the fallback is untested under load.
- **`gpu_mem_guard.sh watch` thresholds on `MemAvailable`**, which is the wrong metric (CUDA
  cannot use reclaimable page cache; the two differ by ~26 GiB here). It is superseded by
  `gb10-guard.service` and must not be run alongside it — two killers racing is worse than one.
- **MPS deliberately uses a non-default pipe directory** (`/tmp/bindmaster-mps/pipe`), so only
  jobs launched via `gpurun` / the `bin/` wrappers / `gpu_mem_guard.sh run` join it. On NVIDIA's
  default pipe every CUDA client auto-joins — including `rustdesk`, whose session would then die
  with the MPS server. Ad-hoc CUDA work is covered by `gb10-guard`, not by MPS.
- **The design tools are uncapped**: Mosaic, BindCraft, BoltzGen, PXDesign, Protein-Hunter,
  RFD3 have no wrapper and were never validated under MPS. Only the three refold engines were.
- **The RTC is dead** (`timedatectl`: "Failed to read RTC: Input/output error"), so journal
  wall-clock timestamps across boots are unreliable. Correlate on `CLOCK_BOOTTIME` and
  `/proc/sys/kernel/random/boot_id`. This silently invalidates most timestamp forensics here.
- **No BMC / out-of-band management** on DGX Spark FE, and no usable serial console. A
  switchable outlet plus the firmware "Power On Behavior" setting is the only true remote
  power path. The watchdog (layer 5) is what removes the need for it in the common case.
- **A watchdog reset is an unclean reboot** (panic → WS1 hard reset), not a graceful one. It
  is the fallback, not the plan — hence `RuntimeWatchdogSec=180`, long enough for layer 2.
