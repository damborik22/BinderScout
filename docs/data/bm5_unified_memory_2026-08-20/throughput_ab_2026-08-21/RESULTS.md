# Sequential vs staggered-concurrent refolding — BM5, 2026-08-21

Pool: 6 PD-L1 binders, 80-120 aa vs a 220 aa target = 300-340 tokens. Target MSA warm.
Caps 24 / 12 / 24 GiB (Boltz-2 / AF3 / ESMFold2), stagger 30 s.
**Concurrent arm ran FIRST (cold caches); sequential ran second (warm).** The handicap
is deliberately against concurrency, so the measured gain is a LOWER bound.

Run on commit a91f595 — i.e. AFTER the JAX_PLATFORMS=cpu fix. The 2026-08-20 attempt
is void: AF3 contributed 0/6 rows and both JAX engines ran on CPU.

| arm | wall | min MemAvailable | peak GPU | NVRM | engines |
|---|---|---|---|---|---|
| staggered-concurrent | **855 s** | 39.9 GiB | 56,067 MiB | 0 | boltz2 254/254, af3 6/6, esmfold2 6/6 |
| sequential | **1066 s** | 86.3 GiB | 24,864 MiB | 0 | boltz2 260/260, af3 6/6, esmfold2 6/6 |

**Concurrency is worth 1.25x — a 19.8% wall-clock saving.**

## Where the time goes (sequential arm, GPU-busy blocks)

| engine | wall | shape |
|---|---|---|
| Boltz-2 | 505 s | one continuous block — dominates |
| AF3 | 379 s | six ~59 s blocks with ~4 s gaps: one fresh run_alphafold.py per binder |
| ESMFold2 | 143 s | one block |
| sum | 1027 s | + ~39 s orchestration = 1066 s |

GPU utilisation: **97%** concurrent, **94%** sequential. Both arms are now genuinely
GPU-bound — the "engines are CPU-bound" reading from 2026-08-20 was entirely an
artifact of JAX_PLATFORMS=cpu.

## Why not faster?

Perfect parallelism would be max(engine) + stagger = 505 + 60 = 565 s, i.e. 1.9x.
We got 1.25x, so contention absorbs most of the theoretical gain — the engines share
one GPU and 20 cores. The ceiling is set by Boltz-2, which alone is 47% of the
sequential total: even infinitely fast AF3 and ESMFold2 could not beat 505 s.

## Verdict

`--concurrent` is a real but modest win, and it is not free:

  wall clock   1066 s -> 855 s      (-20%)
  OS headroom  86.3 GiB -> 39.9 GiB (-54%)

Use it when BM5 is dedicated to the refold. Do NOT use it when anything else needs
the box — halving the headroom to save 3.5 minutes on a 6-binder pool is a bad trade,
and 39.9 GiB is the tightest floor measured with the caps as configured.

Zero NVRM errors in both arms. The unstaggered run on 2026-08-20 hit a near-identical
56,241 MiB peak and logged one, so the 30 s stagger is doing real work.
