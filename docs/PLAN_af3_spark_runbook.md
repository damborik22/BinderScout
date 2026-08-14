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
