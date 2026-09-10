# BM5 unified-memory study — raw results, 2026-08-20

Box: BM5 / spark-1e3d, DGX Spark GB10, 121.7 GiB unified, driver 580.159.03,
kernel 6.17.0-1026-nvidia. Target MSAs warm (no ColabFold traffic).
Scripts: `measure.sh` (single job), `concurrent.sh` (all three), `cgroup_probe.py`.

## 1. cgroup containment — NEGATIVE
12,288 MiB of `cudaMalloc` inside a scope with `memory.max=8 GiB`,
`memory.swap.max=0`. `memory.current` rose 5 -> 92 MiB (+0.7%); `memory.events`
`max 0, oom 0`. System `MemAvailable` fell 1:1 (-12,469 MiB).
**NVIDIA allocations are charged to no memcg on driver 580.x.**

## 2. MPS containment — POSITIVE
`set_default_device_pinned_mem_limit 0 8G`: raw `cudaMalloc` refused at 8,192 MiB.
JAX under the cap computed `bytes_limit=91.27 GiB` (still wrong) but was physically
truncated to `pool_bytes=7.28 GiB`. Asking 8 GiB under a 4 GiB cap gave a clean
`RESOURCE_EXHAUSTED`. MPS rewrites `cudaMemGetInfo` **free** but NOT **total**.

## 3. Boltz-2 demand ladder (PREALLOCATE=false, 48 GiB MPS cap)
| tokens | complex | peak GPU MiB | host footprint | outcome |
|---|---|---|---|---|
| 273 | IL7R 219 + 54 | 17,187 | 22.7 GiB | folded |
| 340 | PD-L1 220 + 120 | 17,189 | 22.6 GiB | folded |
| 634 | EGFR 621 + 13 | 33,490 | 39.5 GiB | clean OOM (+22.8 GiB short) |
| 721 | EGFR 621 + 100 | 33,490 | 39.6 GiB | clean OOM (+33.5 GiB short) |
| 869 | EGFR 621 + 248 | 33,490 | 39.9 GiB | clean OOM — **the historical box-killer** |

Demand is FLAT to ~340 tokens; jumps past 56 GiB above ~600.

## 4. Per-engine demand at 340 tokens
| engine | framework | peak GPU MiB | host footprint | solo wall | cap set |
|---|---|---|---|---|---|
| AF3 | JAX | 7,759 | 14.1 GiB | 129 s | 12 GiB |
| Boltz-2 | JAX | 17,187 | 22.7 GiB | 152 s | 24 GiB |
| ESMFold2 | PyTorch | 18,369 | 30.5 GiB | 46 s | 24 GiB |

## 5. Numerics under MPS — PASSED
- AF3: identical under MPS and without, every metric (deterministic).
- Boltz-2: 3 runs at the SAME 24 GiB cap -> 3 distinct values, spread 0.00096;
  between-cap difference 0.0004 is smaller. Cap has no measurable effect.
- ESMFold2: 3 runs WITHOUT MPS -> 3 distinct values, iptm spread 0.004236;
  the MPS value falls INSIDE that range.

**Two of three engines are nondeterministic run-to-run.** iptm noise floors:
Boltz-2 ~0.001, ESMFold2 ~0.004.

## 6. All three concurrently — WORKS, with one caveat
Launched simultaneously on the same 340-token complex, caps 12/24/24 GiB.

| engine | rc | wall | vs solo |
|---|---|---|---|
| ESMFold2 | 0 | 69 s | 1.50x |
| AF3 | 0 | 106 s | 0.82x (likely warm JAX compile cache, not a real speedup) |
| Boltz-2 | 0 | 211 s | 1.39x |

- peak GPU across all clients: **56,241 MiB**
- max concurrent GPU clients: 4 (3 engines + a 508 MiB desktop client)
- **MIN MemAvailable: 39,242 MiB (38.3 GiB)** — above the 30 GiB floor
- total footprint at peak: 78,980 MiB (77.1 GiB); predicted 79 GiB

**CAVEAT — one `NVRM: NV_ERR_NO_MEMORY ... _memdescAllocInternal` at 07:19:42**,
inside the run window, during the simultaneous cold-start burst when all three
preallocate at once. It did NOT cascade (the 2026-08-18 reboot logged one every
~65 s for 17 minutes); all three jobs returned rc=0 and MemAvailable recovered
fully. But the configuration did touch the driver's failure path once.

**Recommendation: stagger engine starts, or trim caps.** The timeline shows the
peak is purely the simultaneous cold start — usage falls to 37.9 GiB within 40 s
and 25.5 GiB within 105 s as engines finish. Serialising the startup would remove
the burst entirely at no throughput cost.
