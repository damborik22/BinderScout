# GPU benchmark, 2026-09-18 → 22

Peak GPU memory and wall-clock for the three refold engines across every GPU we
have. Single-sequence (no MSA) so token count is the only variable; absolute
numbers are therefore a floor against MSA-enabled production.

Harness: `tools/gpu_bench.py`. All GB10 runs go through `tools/gpurun` (capped
AND registered in `/run/gb10-guard/jobs`).

## Headline

**Boltz-2 is the memory-dominant engine, not AF3.** At 900 tokens on an H200:
AF3 5,224 MiB, ESMFold2 28,770 MiB, **Boltz-2 139,636 MiB (97% of the card)**.
The ">=100 GB GPU" requirement that sat in our docs was real but attached to the
wrong engine; AF3 is the cheapest we have and never exceeded 5.3 GB anywhere.

## GB10 needs ~1.5x the memory of a discrete card for the same work

Boltz-2, 600 tokens: L40S 43,494 MiB, H200 44,974 MiB, **GB10 66,696 MiB**.
Measured by handing it successively larger caps -- it FAILS at 24 and 48 GiB and
succeeds at 72. The earlier "GB10 fails at 600 tok" reading was a cap I sized
from the L40S's number; predicting one card's requirement from another's is what
this file exists to stop.

900 tokens is out of reach on GB10 regardless: ~136 GiB on an H200, against the
~86 GiB `gpurun` will admit (111.9 usable - 13 host - 12 floor).

## GB10 is the slowest card here

AF3 @900 tok: 446.8 s vs 147.1 (RTX 3090), 112.3 (L40S), 52.6 (H200).
ESMFold2 @900 tok: 939.6 s vs 152.0 (L40S), 62.5 (H200).
Boltz-2 @600 tok: 338.8 s vs 114.3 (L40S), 59.0 (H200).
Bandwidth-bound; the 121 GB pool buys capacity, not speed.

## AF3 concurrency saturates early

One H200, 600 tok, shared compile cache: 15 workers all succeed but yield only
**2.77x** throughput (18% efficiency), per-fold latency 38 s -> 206 s. Knee at
**4 workers** (2.01x, 50%). Compute binds long before VRAM -- do not size
parallelism from AF3's 5 GB footprint.

## Caveats on specific cells

- GB10 AF3 and the 24/48 GiB Boltz-2 rows in `gb10_sweep_gpurun.jsonl` record the
  preallocated RESERVATION, not demand: `refold_af3.py` hardcodes
  PREALLOCATE=true for its child, which no env var reaches.
- GB10 ESMFold2 IS real demand (13,781 -> 27,187 MiB, tracks the other cards).
- ESMFold2 writes an EMPTY row and exits 0 on CUDA OOM, so a design can be
  demoted for a hardware reason and look like a quality judgement.
- H200 timings share a node with other jobs; if anything they are pessimistic.
