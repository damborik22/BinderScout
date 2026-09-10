# AF3 runbook — 24 GB feasibility, Spark unified memory, v3.0.4

Execution plan for the open questions in `docs/PLAN_af3_v304_upgrade.md`.
Written 2026-08-11. Everything here needs real hardware — none of it was run
in the authoring session (no GPU, no weights).

**The mem-fraction collision bug is already fixed** (`_build_af3_env` in
`Evaluator/scripts/refold_af3.py`, covered by `tests/binder_comparison/test_af3_env.py`).
Step 0 just confirms the fix is present on the box you're about to use.

Steps A and E run at the **current pin** and need no upgrade. Do them first —
step A is the highest-value experiment we have and does not touch Spark.

---

## ⚠️ Before touching Spark

The failure mode this guard exists to prevent is a **whole-box reboot**, not a
clean crash (`docs/LAB_DIARY.md`, 2026-06-24). So:

- Never run a first-of-its-kind AF3 config on Spark while another job is live.
- Run under `tmux`, and watch memory in a second pane:
  `watch -n2 'nvidia-smi --query-gpu=memory.used,memory.total --format=csv; free -g'`
- Start with **one** binder (`head -2` your FASTA), not a pool.
- If the box reboots, that IS the result — record the config in the diary and
  do not retry it with a larger input.

---

## Step 0 — confirm the fix is on the box (2 min, any machine)

```bash
cd ~/BindMaster && git log --oneline -1 -- Evaluator/scripts/refold_af3.py
python3 -m pytest tests/binder_comparison/test_af3_env.py -q
```

*Pass:* 6 passed. If it reports `6 skipped`, numpy/gemmi are missing from the
interpreter — run it inside `binder-eval-af3` instead:
`conda run -n binder-eval-af3 python -m pytest tests/binder_comparison/test_af3_env.py -q`

Then confirm the operator shell is not carrying a stale variable:

```bash
env | grep -E 'XLA_|TF_FORCE_UNIFIED|AF3_' || echo "clean"
```

---

## Step A — does a ~300-token complex fit in 24 GB? (BM1/BM2/BM4, current pin)

> ### ✅ RAN 2026-08-14 on BM2 (RTX 3090, 24 GB) — **PASS.** The ≥100 GB claim is wrong.
>
> | probe | tokens | peak GPU | wall | result |
> |---|---|---|---|---|
> | ApoE4 NTD (141 aa) + PH-v2 binder (117 aa) | 258 | **4,430 MiB** | 91 s (incl. cold compile) | `iptm 0.88`, `plddt_binder 0.952`, `pae_bt 4.84` |
> | 274 aa target + same binder | 391 | **4,430 MiB** | 93 s | `iptm 0.50` (unrelated target — behaves as a negative control) |
> | 20-design pool (241–286 tokens) | — | — | 70 s / 91 s per design | **20/20, zero empty rows** |
>
> Peak measured with `XLA_PYTHON_CLIENT_PREALLOCATE=false` via a patched runner copy
> (`--scripts-path`), since `_build_af3_env` otherwise forces `true` — **the Step A
> command as written above cannot measure a true peak without that patch.**
> Corroboration of the mechanism: the same box under the shipped default
> (`PREALLOCATE=true`, fraction 0.9) sits at **21,996 MiB for a 4.4 GB working set**.
> Docs corrected across 15 sites (CLAUDE.md, both installers, env YAML, CLI help,
> `main.py`, `schema.py`, `evaluate.sh`, both READMEs, `pipeline_reference.md`, and the
> orchestrator/evaluator skills) — `install_aarch.sh` had the claim too but as `<100 GiB`,
> and several files outside this doc's list carried it as well.
>
> **Prerequisite that was not anticipated:** no fleet box could run AF3 at all. BM4 had a
> broken env (the *PyPI* `alphafold3` stub, no jax); BM1/BM2 had none. Two build failures,
> both fixed without sudo — BM1/BM2 needed conda-forge `zlib` (cifpp's `find_package(ZLIB)`),
> BM4 needed `cxx-compiler` + `binutils` plus unprefixed `ar`/`ranlib` symlinks
> (conda ships only `x86_64-conda-linux-gnu-ar`, so CMake's unprefixed probe fails).

**The question:** our docs claim AF3 needs ≥100 GB and will OOM on 24 GB. That
number was measured *with preallocation on*, which grabs a fixed fraction of
the pool regardless of need. AF3's own docs say 5,120 tokens fits an 80 GB
A100; our complexes are ~200–350 tokens.

**Why it matters more than the upgrade:** if it fits, AF3 runs on the 24 GB
fleet, and the ≥3-engine gate stops being Spark-bound.

Needs `binder-eval-af3` + the gated weights present on a 24 GB Ampere box.

```bash
cd ~/BindMaster
TARGET=<~250 aa target sequence>          # target + binder ≈ 300 tokens
printf '>probe\n<~60 aa binder sequence>\n' > /tmp/af3_probe.fasta

# Preallocation OFF: allocate on demand, so peak reflects the real working set.
AF3_XLA_MEM_FRACTION=0.9 \
XLA_PYTHON_CLIENT_PREALLOCATE=false \
conda run -n binder-eval-af3 binder-compare refold-af3 \
    --sequences /tmp/af3_probe.fasta \
    --target-seq "$TARGET" \
    --num-samples 1 \
    --output /tmp/af3_probe.csv \
    --output-dir /tmp/af3_probe_out
```

Note `PREALLOCATE=false` is deliberate here and contradicts the Spark default —
on a **discrete** 24 GB card we want the true high-water mark, and the
fragment-and-hang behaviour was only ever observed on Spark's unified pool.
Capture peak usage from a parallel `nvidia-smi` poll.

*Pass:* the run completes and `/tmp/af3_probe.csv` has a non-empty, plausible
`iptm`. → the ≥100 GB claim is wrong; record peak VRAM and open the follow-up
to correct `CLAUDE.md`, both installers and `Evaluator/envs/binder-eval-af3.yml`.

*Fail (clean JAX OOM):* record the token count and peak. Retry once with
`--num-samples 1` already set and `--buckets` pinned (step E) before concluding.

Then scale: 5 designs, then ~20, checking wall-clock per design is stable.

---

## Step B — which mem-fraction name does the installed jax honour? (Spark)

Only meaningful **after** upgrading to v3.0.4 (jax 0.10.2). At the current pin
(jax 0.9.1) the legacy name is known-good.

The fix deliberately sets the **legacy** name only. This step confirms that
choice still holds on 0.10.2, i.e. that the cap is not silently a no-op.

```bash
# Absurdly low cap: if the name is honoured, this MUST fail with a JAX OOM.
AF3_XLA_MEM_FRACTION=0.02 \
conda run -n binder-eval-af3 binder-compare refold-af3 \
    --sequences /tmp/af3_probe.fasta --target-seq "$TARGET" \
    --num-samples 1 --output /tmp/af3_name.csv --output-dir /tmp/af3_name_out
```

*Pass:* the run **fails** with a JAX out-of-memory error → the legacy name is
honoured, guard intact, nothing to change.

*Fail:* the run **succeeds** → the legacy name is being ignored on 0.10.2 and
the guard is a no-op. **Stop. Do not run a pool on Spark.** Switch
`_build_af3_env` to emit `XLA_CLIENT_MEM_FRACTION` instead (and pop the legacy
name), then re-run this step. The tests in `test_af3_env.py` encode the
"exactly one name" invariant and should be updated, not deleted.

This step is cheap and it is the gate on everything below it.

---

## Step C — can we delete the Spark workaround? (Spark, v3.0.4)

> ## ⛔ DO NOT RUN THIS STEP AS WRITTEN ON BM5 (added 2026-08-19)
>
> The recipe below is **AF3's guidance for a discrete GPU**, where device VRAM
> oversubscribes into *separate* host RAM. **GB10 has no separate host RAM** —
> `cudaMemGetInfo` total is 121.69 GiB, which is exactly `SC_PHYS_PAGES`.
>
> `TF_FORCE_UNIFIED_MEMORY=true` switches XLA's arena formula (verified in
> `xla/pjrt/gpu/gpu_helpers.cc`) from `total * fraction` to
> **`total * fmax(1.0, fraction)`**. With `XLA_CLIENT_MEM_FRACTION=3.2` that
> targets **3.2 x 121.7 GiB = 389 GiB on a 128 GB machine**.
>
> Combined with `PREALLOCATE=false` it does not grab 389 GiB at once — it is
> worse: it leaves **no ceiling below the machine's own capacity**, so the job
> grows until the OS starves. That is the exact mechanism that hard-rebooted
> this box on 2026-08-18 (`NV_ERR_NO_MEMORY` / `_memdescAllocInternal`), and the
> failure mode of `pytorch/pytorch#174358`, filed against this same hardware.
>
> The step's own "*Fail (hang / fragment / reboot)*" branch is therefore not a
> risk — it is close to the expected outcome.
>
> **Run it only under a CUDA MPS device-memory cap**, which makes the failure a
> clean per-process `RESOURCE_EXHAUSTED` instead of a power cycle:
> `tools/gpu_mem_guard.sh verify` first, then run the step inside
> `tools/gpu_mem_guard.sh run 16G -- <command>`.
> See `docs/PLAN_bm5_unified_memory.md`.


Tests whether v3.0.4's "Blackwell GPU unified memory support fixes" resolve
what we worked around in `refold_af3.py`, and what upstream
[#596](https://github.com/google-deepmind/alphafold3/issues/596) reports on a
Blackwell 96 GB / CUDA 13 host.

Our current config forces `PREALLOCATE=true` at a 0.8 cap and notes that
`false` "fragments and hangs". AF3's `docs/performance.md` recommends the
opposite for unified memory:

```
XLA_PYTHON_CLIENT_PREALLOCATE=false
TF_FORCE_UNIFIED_MEMORY=true
XLA_CLIENT_MEM_FRACTION=3.2
```

`TF_FORCE_UNIFIED_MEMORY` is read by XLA (confirmed in
`xla/pjrt/gpu/gpu_helpers.cc`); the fraction >1 is intentional — it lets the
allocator oversubscribe into host memory.

**One binder. tmux. Memory watch. Nothing else running.**

```bash
XLA_PYTHON_CLIENT_PREALLOCATE=false \
TF_FORCE_UNIFIED_MEMORY=true \
XLA_CLIENT_MEM_FRACTION=3.2 \
conda run -n binder-eval-af3 binder-compare refold-af3 \
    --sequences /tmp/af3_probe.fasta --target-seq "$TARGET" \
    --num-samples 1 --output /tmp/af3_um.csv --output-dir /tmp/af3_um_out
```

The fix forwards that inherited `XLA_CLIENT_MEM_FRACTION=3.2` to the child as
the legacy name and drops the new one — you should see the
`[af3] NOTE: inherited XLA_CLIENT_MEM_FRACTION=3.2` line. Note this run leaves
`PREALLOCATE=false`, which our code otherwise forces to `true`; to test the
documented recipe faithfully you must override that in `_build_af3_env` for the
experiment (a one-line local edit — do not commit it until this step passes).

*Pass:* completes, no hang, box stays up → retest with a >5,120-token complex
to confirm the headroom is real, then propose deleting the workaround.

*Fail (hang / fragment / reboot):* v3.0.4 does not fix our case. Keep the
workaround, and add a note to #596 with our Spark data — a second Blackwell
data point is useful upstream.

---

## Step D — score parity across the version change

`consensus_iptm_mean` averages across engines, so a systematic AF3 shift moves
the ranking of every design scored after the upgrade. **Pools must not straddle
the upgrade.**

Re-refold one already-completed pool on both pins, then compare:

```bash
# same FASTA + target as the archived run, into a fresh CSV
conda run -n binder-eval-af3 binder-compare refold-af3 \
    --sequences <archived seqs.fasta> --target-seq "$TARGET" \
    --output /tmp/af3_v304.csv --output-dir /tmp/af3_v304_out
```

*Check:* per-design `iptm` delta (median, max) and whether the top-10 by
`consensus_iptm_mean` reorders.

*Pass:* deltas within run-to-run seed noise → adopt.
*Fail:* record the shift, stamp the AF3 version into each run's
`settings.json`, and re-refold any pool that must stay comparable.

---

## Step E — compile cache + fixed buckets (current pin, no upgrade)

Independent of v3.0.4. `_run_single` spawns a fresh `run_alphafold.py`
subprocess per binder and we never pass `--jax_compilation_cache_dir`, so every
design recompiles from cold. We also never pin `--buckets`, so a ~310-token
complex pads to the 512 bucket and binders of differing length can trigger a
second compile.

These compose: one fixed bucket → identical shapes across the pool → cache hits.

Prototype by adding to the `cmd` list in `_run_single`:

```python
cmd += [
    f"--jax_compilation_cache_dir={cache_dir}",
    f"--buckets={target_len + binder_len}",
]
```

*Measure:* wall-clock per design over a ≥20-design pool, before vs after.
*Pass:* per-design time drops after the first design and stays flat.

> ### ⚠ RAN 2026-08-14 on BM2 — **2.31× faster, but it MOVES THE SCORES.**
>
> 20 designs (binder 100–145 aa, target ApoE4 NTD 141 aa), same pool both arms,
> back to back on one RTX 3090. Implemented as pool-max bucket (286) + persistent
> `--jax_compilation_cache_dir`.
>
> | arm | bucket | per-design | pool wall |
> |---|---|---|---|
> | before | default ladder | **70 s** (≤256 tok) / **91 s** (>256 tok) | 27.6 min |
> | after | pinned 286, warm cache | **33–34 s, flat** | 11.9 min |
>
> The default ladder's straddle is real and costly: 8 tokens over the 256 boundary
> costs +30%. Compile dominates — every design is a fresh subprocess, so all 20 paid
> a cold compile in the before arm; the after arm compiled twice total (3.8 MB cache).
>
> The scores differ between arms (mean `iptm` 0.615 → 0.584, max |Δ| 0.18). **An initial
> read blamed the bucket. The determinism control refuted that — see below.**
>
> ### Determinism control (ran 2026-08-14 18:36–18:47, same box, 8 designs)
>
> Reran the **before config, unchanged** (unpatched runner, default ladder, no cache) on
> 8 of the same designs — 5 that moved and 3 that were bit-identical.
>
> **AF3 does not reproduce its own numbers.** 0/8 designs matched on `iptm`+`plddt`:
>
> | | mean \|Δ iptm\| vs the original before arm |
> |---|---|
> | **before vs before** (identical config, rerun) | **0.0513** |
> | before vs after (Step E) | 0.0688 |
>
> The Step E "effect" is the same order as pure rerun noise. The decisive detail is the
> 122 aa design: **before 0.77 → control 0.59 → after 0.59.** The two runs that *agree*
> used **different** buckets (512 vs 286), and the two that *disagree* used the **same**
> bucket (512 vs 512). Bucket therefore cannot be the driver.
>
> **Conclusion: Step E does NOT move the scores.** It is a 2.31× speedup with no
> demonstrated score bias, and there is no "must not straddle" constraint from it.
>
> **The real finding is bigger than Step E:** *our AF3 refolds are not reproducible
> run-to-run.* 5/8 held to 2 dp on `iptm` (0.86, 0.84, 0.82, 0.48, and 0.77 → 0.76);
> 3/8 swung hard (0.27 → 0.19, 0.52 → 0.38, 0.77 → 0.59). **Stability does not track
> confidence cleanly** — one design at 0.77 barely moved while another at the same 0.77
> fell to 0.59, so "the top of the pool is safe from this" is not supported. The seed is
> fixed (`modelSeeds: [1]`), so this is GPU/XLA-level nondeterminism, not a different seed.
>
> ### Production check at `--num-samples 5` (ran 2026-08-14 18:56–19:24, 3 arms × 8 designs)
>
> The 1-sample runs above were expected to be an *upper bound* on production noise,
> on the reasoning that 5 samples would average the variance away. **Both parts of
> that expectation were wrong.**
>
> **(a) 5 samples does NOT reduce the noise.**
>
> | | mean \|Δ iptm\| between two identical runs | max |
> |---|---|---|
> | `--num-samples 1` | 0.0513 | 0.180 |
> | `--num-samples 5` (production) | **0.0563** | **0.200** |
>
> No improvement — marginally worse, and the worst excursion grows. The mechanism is
> that AF3 does not *average* the samples: `_load_top_sample` keeps the **top-ranked**
> one. That is an order statistic over 5 stochastic draws, so which sample wins varies
> between runs and the reported value hops between different samples' scores. More
> samples buys more chances to hop, not less variance.
>
> Note also that *which* designs are unstable changed with the config: at 1 sample the
> movers were 105/112/122 aa; at 5 samples they are 122/140/142 aa, and the 140 aa and
> 142 aa designs were **perfectly stable** at 1 sample (Δ 0.000) before swinging 0.20
> and 0.18. Instability is not a fixed property of a design — consistent with a
> selection effect rather than a per-design "this one is marginal" story.
>
> **(b) The Step E speedup HOLDS at production settings — 2.15×, not the 1.24× projected.**
>
> | arm (5 samples, 8 designs) | per design |
> |---|---|
> | default ladder (pre-Step-E) | 105 s |
> | Step E (pinned bucket + cache) | **48.9 s** |
>
> The 1.24× projection assumed diffusion sampling scales linearly with `num_samples`.
> It does not — 5 samples costs only ~1.5× one sample (33.5 s → 48.9 s), because the
> trunk runs once and extra samples are cheap. So the fixed ~40 s compile stays the
> dominant per-design cost at production settings and the cache keeps paying.
>
> **Step E vs before at 5 samples:** mean |Δ iptm| 0.0825 against a 0.0563 run-to-run
> noise floor — same order, n=8, so still no evidence of systematic bias.
>
> **What this means beyond Step E:** `af3_iptm` carries a **~0.06 mean / 0.20 worst-case
> run-to-run uncertainty that the production config does not remove.** Two designs whose
> `consensus_iptm_mean` differ by less than that are not distinguished by the metric —
> AF3 is 1 of 3 engines, so the effect on the consensus is roughly a third of it, *if*
> the other two engines are stable. **Nobody has measured Boltz-2 or ESMFold2
> reproducibility.** That is the next experiment, and it is a ranking-integrity question,
> not an AF3 question.

Watch for: a per-binder bucket defeats the cache (lengths vary), so bucket on
the **pool maximum**, not the per-design length. That is the detail to get right
before this is worth committing.

---

## Order and dependencies

```
Step 0 ─┬─> Step A  (24 GB, current pin)      ── independent, highest value
        └─> Step E  (compile cache, any host) ── independent

  upgrade to v3.0.4
        └─> Step B  (name check, Spark) ──> Step C (unified memory, Spark)
                                       └──> Step D (score parity)
```

Do not re-pin `AF3_COMMIT` until A and E are done and B passes.

## Recording results

Append to `docs/LAB_DIARY.md` with the date, host, exact env vars, token count,
peak memory and outcome — including failures. The 2026-06-24 entry is the
template. If step A passes, the follow-up is a docs correction across
`CLAUDE.md`, `install/install.sh`, `install/install_aarch.sh` and
`Evaluator/envs/binder-eval-af3.yml`, all of which currently assert ≥100 GB.
