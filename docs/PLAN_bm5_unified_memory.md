# PLAN — BM5 unified memory: stop the box dying, then share it

**Status:** measured · **Opened:** 2026-08-19 · **Box:** BM5 / spark-1e3d (DGX Spark, GB10, aarch64)

> Supersedes the first draft of this file, which proposed bisecting for the
> "ceiling" (0.30 → 0.90, "expect reboots"). That experiment is **cancelled** —
> see *Why we are not hunting the ceiling*. Its evidence table is kept below.

## The mechanism, settled

`cudaMemGetInfo` on GB10 returns **total = 121.69 GiB = exactly `SC_PHYS_PAGES`**.
There is no device. Every allocator knob in both frameworks is *a fraction of
device total*, so on this box those knobs are fractions **of the whole machine**.

| incident | knob | fraction x 121.7 GiB | reserved | OS left | outcome |
|---|---|---|---|---|---|
| 2026-08-18 09:22-09:39 AF3 | hard-coded `0.8` | 97.4 GiB | 99,960 MiB | ~24 GB | `NV_ERR_NO_MEMORY` every ~65 s for 17 min -> **hard reboot**, 22 d uptime lost |
| 2026-08-19 18:17 Boltz-2 | none set -> JAX default `0.75` | 91.3 GiB | 93,802 MiB | ~30 GB | 1 x `NV_ERR_NO_MEMORY`, killed before cascade |

Both match the arithmetic to within 0.3%. **The machine never ran out of memory.
An allocator was told to take 75-80% of the computer and complied.**

Measured working sets, for contrast: AF3 **4.4 GB** (258- *and* 391-token
complexes). Boltz-2 **unknown** — the "18.9 GB" in the first draft of this plan
is almost certainly `0.75 x ~23.6 GiB` measured on a 24 GB card, i.e. the same
preallocation artifact on a smaller pool. Supply, not demand.

## What we measured on this box, 2026-08-19

| probe | result |
|---|---|
| cgroup v2 `memory.max` = 8 GiB, allocate 12 GiB | **allocated all 12 GiB.** `memory.current` 5 -> 92 MiB (+0.7%); `memory.events` `max 0, oom 0`. `MemAvailable` fell 1:1. **Not charged to any memcg.** |
| MPS `set_default_device_pinned_mem_limit 0 8G` | **enforced.** raw `cudaMalloc` refused at 8,192 MiB; held 7,680 |
| MPS effect on `cudaMemGetInfo` | rewrites **free** (7.85 GiB); **does NOT rewrite total** (still 121.69 GiB) |
| JAX under 8 GiB MPS cap | computed `bytes_limit = 91.27 GiB` (still wrong) but **physically truncated to `pool_bytes = 7.28 GiB`** |
| JAX asking 8 GiB under a 4 GiB cap | `RESOURCE_EXHAUSTED: Out of memory while trying to allocate 8.00GiB` — clean, per-process, box untouched |

**Root cause of the cgroup result, from NVIDIA's own source:** the driver only
wired up the `dmem` cgroup controller starting at **610.43.02**. In 580.159.03
(ours) *and* 580.173.02 (the offered upgrade), `NV_DMEM_CGROUP_PRESENT` is unset
and `os_dmem_cgroup_try_charge()` compiles to a stub returning `NV_OK`
unconditionally. Zero accounting by construction. Kernel 6.17 has `dmem` ready
and listed in `cgroup.controllers`; the driver simply never registers.


## MEASURED 2026-08-20 — Steps 1, 2, 3 complete

All runs on BM5 under an MPS cap, `PREALLOCATE=false` for demand, target MSAs warm
(no ColabFold traffic).  **Zero NVRM errors across the entire session; uptime unbroken.**

### Boltz-2 demand vs complex size (the ladder)

| tokens | complex | peak GPU | total host footprint | outcome |
|---|---|---|---|---|
| 273 | IL7R 219 + 54 | 17,187 MiB | 22.7 GiB | folded |
| 340 | PD-L1 220 + 120 | 17,189 MiB | 22.6 GiB | folded |
| 634 | EGFR 621 + 13 | 33,490 MiB | 39.5 GiB | clean `RESOURCE_EXHAUSTED` (+22.8 GiB short) |
| 721 | EGFR 621 + 100 | 33,490 MiB | 39.6 GiB | clean `RESOURCE_EXHAUSTED` (+33.5 GiB short) |
| **869** | **EGFR 621 + 248** | 33,490 MiB | 39.9 GiB | **clean `RESOURCE_EXHAUSTED`** |

**Demand is FLAT in our regime** — 273 and 340 tokens peak identically, so the cost is
fixed (weights + fixed buffers), not N².  Same shape AF3 shows (4.4 GB at both 258 and
391 tokens).  Above ~600 tokens it jumps past 56 GiB and does not fit.

**The 869-token row is the headline.** That is the complex class that force-rebooted this
box on 2026-06-02/03 and again in the 2026-08 incidents.  It now fails as a per-process
error with the machine untouched.

This also corrects the earlier reading in this plan.  The old "820 OK / 860 hangs" rule
was **not** purely a preallocation artifact — at those sizes Boltz-2's genuine demand
exceeds what the box can give.  Both mechanisms were real: over-reservation killed small
complexes, real demand kills large ones.  Only the first is fixable by a cap.

### Per-engine demand at 340 tokens, and the final budget

| engine | framework | peak GPU | total host footprint | **cap** | basis |
|---|---|---|---|---|---|
| AF3 | JAX | 7,759 MiB | 14.1 GiB | **12 GiB** | 1.5x; completed at an 8 GiB cap, `iptm 0.9100` |
| Boltz-2 | JAX | 17,187 MiB | 22.7 GiB | **24 GiB** | 1.4x; verified completing at 24 GiB |
| ESMFold2 | PyTorch | 18,369 MiB | 30.5 GiB | **24 GiB** | 1.3x; `--model full` = same as default |

Caps sum to 60 GiB; observed total footprints sum to ~79 GiB of 121.7 GiB, leaving ~42 GiB
— above the 30 GiB floor.  **All three engines can run concurrently.**

Note `PREALLOCATE=true` means each JAX engine takes its **whole cap**, not its demand, so
the budget sums caps and not demands.  (Running `PREALLOCATE=false` in production would
free ~20 GiB but risks fragmentation on our shape-varying binder lengths — untested,
deliberately not adopted.)


### All three concurrently — demonstrated 2026-08-20

Summed measurements are an inference; this is the measurement.  Same 340-token
complex, all three launched simultaneously, caps 12 / 24 / 24 GiB.

| engine | rc | wall | vs solo |
|---|---|---|---|
| ESMFold2 | 0 | 69 s | 1.50x |
| AF3 | 0 | 106 s | 0.82x (warm compile cache, not a real speedup) |
| Boltz-2 | 0 | 211 s | 1.39x |

peak GPU **56,241 MiB** across 4 clients; **MIN MemAvailable 38.3 GiB**; total
footprint at peak 77.1 GiB against a predicted 79 GiB.  **3/3 succeeded.**

**But it is not a spotless pass.** One `NVRM: NV_ERR_NO_MEMORY ...
_memdescAllocInternal` was logged at 07:19:42, inside the run window, during the
simultaneous cold start when all three preallocate at once.  It did not cascade —
the 2026-08-18 reboot logged one every ~65 s for 17 minutes — and every job
returned rc=0.  But the configuration touched the driver's failure path once, so
"three concurrent engines" is *supported*, not *comfortable*.

**Fix before this becomes routine: stagger the starts.**  The timeline shows the
peak is purely the simultaneous cold start (56.2 GiB at t+39 s, 37.9 GiB at t+72 s,
25.5 GiB at t+105 s as engines finish).  Serialising startup removes the burst at
no throughput cost, because the engines do not finish together anyway.

Raw data, scripts and per-run CSVs: `docs/data/bm5_unified_memory_2026-08-20/`.



### Post-firmware verification — 2026-08-20 06:36, re-verified after reboot

Applied via `fwupdmgr` (NVIDIA's own LVFS channel), both `Update State: Success`:

| device | before | after |
|---|---|---|
| Embedded Controller | 0x03000302 | **0x03000508** |
| UEFI / SoC | 0x0200980f | **0x02009b0b** |

Driver and kernel were held and did **not** move (580.159.03 / 6.17.0-1026-nvidia);
`linux-modules-nvidia-580-open-6.17.0-1026-nvidia` present for the running kernel, so
the orphaned-module failure that killed this box previously did not recur.

| check | result |
|---|---|
| `gpu_mem_guard.sh verify` | **PASS** — 4 GiB refused under a 2 GiB cap |
| `cudaMemGetInfo` total vs system RAM | **121.69 GiB == 121.69 GiB — still identical** |
| real NVRM errors since boot | 0 |
| AF3 @340 tokens, numerics vs pre-firmware | **identical on every metric** |

**The firmware did not fix the root cause, exactly as predicted.**  `cudaMemGetInfo`
still reports the entire machine as device memory, so a fraction-of-total allocator still
reserves a fraction of the host.  The guard remains load-bearing; there was never a
firmware release waiting to save us.  This is the concrete evidence for that call.

*Operational note:* the reboot cleared `/tmp`, taking the test pools with it.  They were
recoverable only because they had been copied into
`docs/data/bm5_unified_memory_2026-08-20/pools/`.  Keep measurement inputs out of `/tmp`.

### Staggering + evaluate.sh wiring — 2026-08-20

`evaluate.sh` now applies the MPS ceiling on **every** run (sequential included) and
gained an opt-in `--concurrent` with `--stagger N` (default 30 s).  Default behaviour is
unchanged: engines still run one after another, now capped.

| | simultaneous (manual, 07:19) | staggered 30 s (evaluate.sh, 07:37) |
|---|---|---|
| MIN MemAvailable | 38.3 GiB | **83.3 GiB** |
| peak GPU (all clients) | 56,241 MiB | **19,047 MiB** |
| NVRM `NV_ERR_NO_MEMORY` | 1 | **0** |
| result | 3/3 ok | full pipeline exit 0, report written |

**The startup burst is gone.**  `--concurrent` refuses to run if the MPS ceiling is not
active (exit 2), because concurrency without a hard per-client cap is the configuration
that took the box down.  Signal traps (INT/TERM as well as EXIT) tear MPS down if the
script is killed — without them a `timeout` left the daemon holding machine-wide state.

**Throughput ANSWERED 2026-08-21** (6 PD-L1 binders, 300-340 tokens, on commit a91f595
i.e. after the JAX_PLATFORMS fix; concurrent arm ran first with cold caches, so the
figure is a lower bound):

| arm | wall | min MemAvailable | peak GPU | NVRM | engines valid |
|---|---|---|---|---|---|
| staggered-concurrent | **855 s** | 39.9 GiB | 56,067 MiB | 0 | all |
| sequential | **1066 s** | 86.3 GiB | 24,864 MiB | 0 | all |

**`--concurrent` is worth 1.25x — a 19.8% saving — and costs 54% of the OS headroom.**
GPU utilisation is 97% / 94%: both arms are genuinely GPU-bound.  Perfect parallelism
would be 565 s (1.9x), so contention absorbs most of the theoretical gain; the ceiling
is Boltz-2, which alone is 47% of the sequential total.

Use it when BM5 is dedicated to the refold.  Do NOT use it when anything else needs the
box: halving headroom to save 3.5 minutes on a 6-binder pool is a bad trade, and 39.9 GiB
is the tightest floor measured at these caps.

> The earlier 1-binder reading in this plan — "GPU occupancy 42 s of 480 s, the engines
> effectively serialise, the workload is CPU-bound" — was **wrong, and wrong for a
> reason worth remembering**: `evaluate.sh` was exporting `JAX_PLATFORMS=cpu`, so both
> JAX engines ran on CPU and AF3 produced nothing at all.  The measurement was of a
> broken pipeline.  See the 2026-08-21 commit a91f595.

Raw data: `docs/data/bm5_unified_memory_2026-08-20/throughput_ab_2026-08-21/`.

### Numerics under MPS — gate PASSED

| engine | result |
|---|---|
| AF3 | **identical** under MPS and without, on every metric — deterministic |
| Boltz-2 | 3 runs at the *same* cap give 3 distinct values (spread 0.00096); the between-cap difference (0.0004) is smaller |
| ESMFold2 | 3 runs without MPS give 3 distinct values (iptm spread 0.0042); the MPS value falls **inside** that range |

**MPS is numerically transparent.**  The controls were essential: without them the raw
comparisons looked like MPS was perturbing results, when two of three engines are simply
nondeterministic run-to-run.

> **Side-finding worth carrying into evaluation:** Boltz-2 and ESMFold2 are
> **nondeterministic run-to-run** on this box — iptm spreads of ~0.001 and ~0.004
> respectively.  Differences below those magnitudes in `consensus_iptm_mean` are noise,
> not signal.

## Why we are not hunting the ceiling

1. **It optimises the wrong quantity.** AF3 needs 4.4 GB. Reserving 80 GB is 18x
   the working set and still parks us near the failure band, for nothing.
2. **The ceiling is not a stable number.** It moves with page cache, desktop and
   the job's own host RSS. Bisected once, it is valid for that baseline only.
3. **It costs reboots** — ~13 for the full sweep — to learn a number we would
   never operate near.

Cap on **measured demand x a safety factor**, and make the cap physically
enforceable. That is the whole design.

## Design: manufacture a device boundary

A discrete card is safe because it *has a boundary*: fixed VRAM turns runaway
growth into a clean per-allocation failure. GB10 has none. We add one.

### Layer 0 — verify (nothing below is trusted without this)

`tools/gpu_mem_guard.sh verify` — ~60 s. Starts MPS with a small cap, confirms an
over-allocation is refused, stops MPS. **Run after every driver, kernel or
firmware change.** MPS pinned-limits are reported silently non-enforcing on some
driver builds (`NVIDIA/k8s-device-plugin` #467, #764), so enforcement is a
property to be re-established, never assumed.

### Layer 1 — MPS per-client cap (the hard ceiling)

`nvidia-cuda-mps-control` with `set_default_device_pinned_mem_limit`, plus
per-engine `CUDA_MPS_PINNED_DEVICE_MEM_LIMIT`. Verified enforcing here.
Provisional budget on the 121.7 GiB pool, pending Step 1 measurement:

| engine | provisional cap | basis |
|---|---|---|
| AF3 | 16 GiB | 3.6x its measured 4.4 GB |
| Boltz-2 | 32 GiB | provisional — demand unmeasured; > anything a 24 GB card ran |
| ESMFold2 | 16 GiB | provisional — PyTorch, grows on demand |
| **reserved for OS + page cache** | **>= 30 GiB** | never allocatable |

Sum 64 GiB of 121.7, leaving ~57 GiB headroom. All three engines can run at once.

### Layer 2 — correct absolute-GB fractions (defense in depth)

MPS is a daemon. If it is not running, every client silently reverts to uncapped
direct mode. So each engine still computes its own fraction **from an absolute GB
target and the real pool**, with a unified-memory OS floor.

Confirmed by research: **no absolute-bytes cap exists in JAX or PyTorch.** XLA has
the capability internally (`gpu_system_memory_size` in `CreateBFCAllocator`) but
exposes no env var or config reaching it; `jax-ml/jax#4310` asked for exactly this
in 2020 and it never shipped. PyTorch's `set_per_process_memory_fraction()` is the
same fraction-of-`totalGlobalMem` math. Computing the fraction ourselves is not a
workaround — it is the only road.

### Layer 3 — MemAvailable watchdog (backstop)

Covers what MPS does not: host-side RSS, non-CUDA memory, and MPS being down.

**Critical detail:** the kernel OOM killer and `earlyoom` both select victims from
RSS-derived `oom_score`, and GPU pages do not inflate RSS. They fire at the right
*time* and may aim at the wrong *process*. Our watchdog must pick the victim from
`nvidia-smi --query-compute-apps` — NVML sees the allocation even though the
kernel does not.

### Layer 4 — OS hardening (needs sudo; David runs these)

- `earlyoom` — NVIDIA folded it into their own `sparkrun` tooling; triggers on
  `/proc/meminfo`, the signal that *did* move in our measurement.
- Protect sshd: `OOMScoreAdjust=-1000`, `MemoryMin=512M` drop-in.
- Consider `swapoff -a` — the most-repeated community advice; converts a hang into
  a clean crash. Our 16 GB swap cannot help anyway: GPU pages are pinned.

## Steps

| # | step | needs | status |
|---|---|---|---|
| 0 | Cancel the ceiling bisection | — | **done** |
| 1 | Measure true demand per engine (`PREALLOCATE=false` under an MPS cap, one short run each) | GPU, ~1 h | **tomorrow** |
| 2 | Set real caps from Step 1; replace the provisional table | — | after 1 |
| 3 | Validate numerics under MPS — AF3 / Boltz-2 / ESMFold2 must produce identical results, and measure throughput | GPU, ~2 h | **tomorrow** |
| 4 | MPS lifecycle as a systemd **user** unit (no root needed) | — | after 3 |
| 5 | OS hardening (earlyoom, sshd protection, swap decision) | **sudo — David** | after 3 |
| 6 | **SoC firmware only** (see below), then re-run `verify` | **sudo — David** | after 4 |
| 7 | Test whether GB10 unified memory registers a `dmem` region on driver 610.x | GPU + sudo | **parked — see below** |

## Firmware and driver: take the firmware, refuse the driver

Researched 2026-08-19. **This reverses an earlier reading in this session that
said "firmware + driver + kernel in one window".**

**DO — SoC firmware, via NVIDIA's own channel.** `fwupd` offers UEFI/SoC
`0x0200980f -> 0x02009b0b`, urgency High, vendor-tested 2026-06-29. It is the
2026-07-15 LVFS push ("improves the performance and stability of the
System-on-Chip Firmware including UEFI and GPU"). Nothing newer exists.
```
sudo fwupdmgr refresh && sudo fwupdmgr upgrade && sudo reboot
```
The DMI BIOS string (`5.36_0ACUM018`) is cosmetic — NVIDIA support states it is
"a little stale, but only updated as part of the SoC FW". Do not chase it.

**DO NOT — driver 580.173.02, which `apt` is offering.** Two open regression
reports, and the second is a direct hit:
- 2026-07-26: a routine `apt upgrade` to 580.173.02 **broke GPU detection** on
  multiple units — `Timeout after 6s of waiting for RPC response from GPU0 GSP!`,
  `nvidia-smi` -> "No devices were found". Recovery was pinning back.
- 2026-08-05/08: an **open, unresolved hard-freeze** under sustained inference on
  DGX OS 7.5.0 / kernel **6.17.0-1029-nvidia** / driver **580.173.02** — i.e.
  *exactly* the kernel+driver pair `apt` wants to give us.

NVIDIA's own DGX Spark release notes still badge **580.159.03** as current;
580.173.02 arrives from Ubuntu's generic `noble-updates` pocket, not NVIDIA's
curated Spark train. Hold both:
```
sudo apt-mark hold nvidia-driver-580-open linux-nvidia-hwe-24.04
```
Before any future kernel bump, confirm `linux-modules-nvidia-580-open-$(uname -r)`
exists **before rebooting** — NVIDIA's update guide does not check this, and it is
how this box lost its GPU once already.

**Also note: the OOM fix we were hoping for is already in our driver.** The
"improved unified memory handling" announcement *is* 580.159.03 (2026-06-11), and
it is worded as *"adds user feedback when the system encounters memory pressure"* —
not "prevents hangs". `NV_ERR_NO_MEMORY`, `_memdescAllocInternal` and
`cudaMemGetInfo` appear in **no** NVIDIA changelog, only in forum diagnostics that
match our signature exactly. There is no driver waiting to save us.

**Step 7 parked.** The `dmem` route needs driver 610.x, and NVIDIA staff state
plainly that 590 and 595 are "not yet supported on the Spark"; 610 on GB10 is a
community self-install requiring Secure Boot disabled, with the GPU observed
throttled to 2000 MHz. Revisit only if NVIDIA ships a supported branch with dmem,
and note the region naming (`nvidia/<pci>/vidmem`) suggests it may only cover
discrete VRAM anyway.

## Do NOT

- **Do not run `PLAN_af3_spark_runbook.md` Step C as written.**
  `TF_FORCE_UNIFIED_MEMORY=true` + `XLA_CLIENT_MEM_FRACTION=3.2` switches XLA's
  arena formula to `total x fmax(1.0, fraction)`. On GB10 that is 3.2 x 121.7 GiB
  = **389 GiB on a 128 GB machine** — i.e. no ceiling below the machine's own
  capacity. Safe only under an MPS cap. Warning added to that file.
- **Do not trust cgroups / Docker `--memory`** to contain GPU allocations on this
  driver. Measured false here; independently reproduced by another Spark owner
  (10.7 GB allocation -> +377 MB `memory.current`).
- **Do not rely on `systemd-oomd`.** Its primary trigger is per-cgroup PSI; the
  offending cgroup is the one *succeeding*, so pressure accumulates in innocent
  cgroups and it is liable to kill the wrong process.
- **Do not cap below ~2.5x a measured working set.**

## Prior art

There is none. AF3 issue #434 ("Using AF3 on an NVIDIA DGX Spark") closed with no
answer. NVIDIA's own DGX Spark JAX playbook names the UMA problem and offers only
`drop_caches`. No JAX, NVIDIA or AlphaFold3 document states a safe setting for
GB10. **No source found anywhere reports `CUDA_MPS_PINNED_DEVICE_MEM_LIMIT`
verified working on GB10 — the Layer 1 measurement above appears to be new.**
