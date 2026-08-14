# AlphaFold 3 v3.0.4 — what it changes for BindMaster

Analysis of <https://github.com/google-deepmind/alphafold3/releases/tag/v3.0.4>
against our current AF3 integration (Part K). Written 2026-08-11.

**Status: analysis only. Nothing here is implemented.** Everything below is
either a *verified fact* (checked against the AF3 source at the two commits) or
an explicitly-labelled *hypothesis to test*. The two are kept separate on
purpose — the interesting items are mostly hypotheses, and several of them are
cheap to falsify.

---

## 1. Where we are

| | value |
|---|---|
| Pinned commit | `fd39d2c5dcaadfc7333c3466951b27563fa7d6fa` (`AF3_COMMIT`, both installers) |
| Version at that commit | `3.0.3.dev` — i.e. **after the v3.0.2 tag, before the v3.0.3 tag** |
| Deps at that commit | `jax==0.9.1`, `jax[cuda12]==0.9.1`, `tokamax==0.0.11` |
| Deps at v3.0.4 | `jax==0.10.2`, `jax[cuda12]==0.10.2`, `tokamax==0.0.12`, `+ jax-mps` (darwin), `+ etils[epath]`, `+ gcsfs` extra |
| Weights we hold | v3.0.2-era gated params |
| Our runner | `Evaluator/scripts/refold_af3.py` — one `run_alphafold.py` **subprocess per binder** |

So upgrading to v3.0.4 skips **two** releases (v3.0.3 and v3.0.4), not one.

**Weights compatibility (the gating question, and it is good news):** the v3.0.3
notes state *"The AlphaFold 3 parameter files are compatible with any 3.0.x
version. We bump the major/minor version numbers only when a new model is
released, otherwise only the patch version number is increased."* Our existing
gated weights work with v3.0.4 — **no re-request to DeepMind, no re-gating.**

**Licensing is not part of this delta.** I checked `LICENSE` at both commits:
both are Apache-2.0. The CC BY-NC-SA → Apache-2.0 relicense landed on main
*before* our pin, so we already have it. (The *model parameters* remain under
their own separate, non-commercial gated terms — unchanged by v3.0.4. Do not
conflate the two.)

---

## 2. What v3.0.4 actually contains

Verified against the release page and the source at the `v3.0.4` tag.

| change | new to *us*? | relevance |
|---|---|---|
| **JAX 0.9.1 → 0.10.2, Tokamax 0.0.11 → 0.0.12** — "significant inference speedup and **Blackwell GPU unified memory support fixes**" | yes | **highest — see §3.1** |
| **Reduced memory for outer-product-mean** (algebraic reassociation) | yes | high — see §3.2 |
| **Chain IDs added to summary confidence JSON** | yes | medium — see §3.3 |
| **CPU-only backend + new `--jax_backend` flag** (`CPU`/`GPU`/`MPS`) | yes (flag absent at our pin) | medium — see §3.4 |
| Apple Silicon / `jax-mps` | yes | **none — see §6** |
| `gs://` paths via `etils.epath` + `gcsfs` extra | yes | none |
| RNG seeds validated as uint32 up-front | yes | none (we pass `1..N`; already valid) |
| Docs clarification on user-provided CCD | yes | none |
| *(v3.0.3)* JSON serialization up to 30× faster on large inputs | yes | negligible — our inputs are two chains |
| *(v3.0.3)* Python 3.14 support | yes | none (we pin 3.12) |

---

## 3. Opportunities, ranked

### 3.1 The Spark unified-memory workaround may be a bug we can now delete

This is the one that matters.

`refold_af3.py:291-302` carries a workaround with a blunt comment:

```python
# On unified-memory hosts (DGX Spark, 96 GB shared CPU+GPU) JAX otherwise grabs
# ~97% of the pool (~93.7 GB observed), starving the OS/NVRM driver →
# out-of-memory cascade → whole-box reboot.
# Keep PREALLOCATE=true (=false fragments and hangs). Default 0.8
```

We force `XLA_PYTHON_CLIENT_PREALLOCATE=true` and cap the fraction at 0.8,
explicitly noting that `PREALLOCATE=false` "fragments and hangs".

AF3's own `docs/performance.md` recommends the **exact opposite** for unified
memory:

```
XLA_PYTHON_CLIENT_PREALLOCATE=false
TF_FORCE_UNIFIED_MEMORY=true
XLA_CLIENT_MEM_FRACTION=3.2
```

Upstream issue [#596](https://github.com/google-deepmind/alphafold3/issues/596)
reports those three flags **silently ceasing to work after the Tokamax change**,
on a Blackwell 96 GB card with CUDA 13 — hardware and driver stack very close to
DGX Spark (GB10 Blackwell, unified memory, CUDA 13.0).

**Hypothesis:** our workaround is not a property of Spark. It is us having
independently rediscovered the Blackwell/Tokamax unified-memory bug, and
v3.0.4's "Blackwell GPU unified memory support fixes" is plausibly its fix.

If that holds, upgrading lets us drop the 0.8 cap and adopt the documented
unified-memory path — which is what actually unlocks complexes above the
5,120-token bucket on Spark.

*Confidence: moderate.* The link between #596 and the v3.0.4 fix is inferred
from the release note wording, not stated by a maintainer; the issue is closed
with no documented resolution. It is directly testable on Spark.

⚠️ **This section originally flagged an unverified naming risk. It has since
been resolved, and the answer inverted the obvious fix — see below.** The
remaining hardware steps live in `docs/PLAN_af3_spark_runbook.md`.

We set `XLA_PYTHON_CLIENT_MEM_FRACTION`; AF3's docs and issue #596 use
`XLA_CLIENT_MEM_FRACTION` (no `PYTHON_`). Checking jaxlib settled it:

```python
memory_fraction = os.getenv("XLA_CLIENT_MEM_FRACTION", "")
deprecated_memory_fraction = os.getenv("XLA_PYTHON_CLIENT_MEM_FRACTION", "")
if deprecated_memory_fraction:
    if memory_fraction:
        raise ValueError(
            "XLA_CLIENT_MEM_FRACTION is specified together "
            "with XLA_PYTHON_CLIENT_MEM_FRACTION. "
            "Remove the latter one, it is deprecated."
        )
```

So the legacy name is **still read** — the guard was never at risk of silently
no-opping on 0.10.2 — but setting **both** names is a hard `ValueError`. The
"consider setting both names" suggestion above would therefore have broken
every AF3 run.

That turned a hypothetical into a **live bug at the current pin**: we built the
child env as `{**os.environ, "XLA_PYTHON_CLIENT_MEM_FRACTION": ...}`, so any
operator who exported `XLA_CLIENT_MEM_FRACTION` — which is exactly what AF3's
`docs/performance.md` tells unified-memory hosts to do — got both names in the
child and lost every design to that ValueError, near-silently (empty rows, then
a blanket ≥3-engine gate failure).

**Fixed** in `_build_af3_env` (`Evaluator/scripts/refold_af3.py`), covered by
`tests/binder_comparison/test_af3_env.py`: exactly one name reaches the child,
an inherited `XLA_CLIENT_MEM_FRACTION` is forwarded rather than discarded, and
the legacy name is the one we emit (honoured by both 0.9.x and 0.10.x, whereas
older jaxlib ignores the newer name). Step B of the runbook re-checks this on
Spark after the upgrade.

### 3.2 The ">100 GB VRAM" requirement is probably wrong, and it costs us the fleet

Standing claim across `CLAUDE.md`, both installers and the env YAML: AF3
"requires >=100 GB GPU memory", "will OOM on consumer 24 GB GPUs", so it runs
only on Spark / H200. That constraint is why the 3-engine gate is expensive —
BM1/BM2/BM4 (24 GB Ampere) cannot contribute AF3 scores.

Two facts sit badly with it:

1. AF3's docs state **5,120 tokens fits a single 80 GB A100/H100**. Our
   refold complexes are a target (~100–250 aa) plus a binder (~60 aa) —
   roughly **200–350 tokens**, an order of magnitude smaller, and pair-wise
   activations scale super-linearly in token count.
2. The ~93.7 GB we *observed* on Spark was measured with
   `XLA_PYTHON_CLIENT_PREALLOCATE=true`. Preallocation grabs a fraction of the
   pool **by design, regardless of what the model needs.** That number is
   evidence about our env vars, not about AF3's working set.

**Hypothesis:** a 350-token binder-target complex fits comfortably in 24 GB, and
the ">100 GB" figure is an artifact of preallocation on a large unified pool
that got written down as a hardware requirement.

If true, this is worth more than everything else in this document combined: AF3
becomes available on BM1/BM2/BM4, the ≥3-engine gate stops being Spark-bound,
and `--min-engines 3` becomes cheap to satisfy fleet-wide.

*Note this is mostly independent of v3.0.4* — if the claim is wrong, it is
wrong at our current pin too. v3.0.4's outer-product-mean memory reduction only
widens the margin. **Testable in about an hour on any 24 GB box that has the
weights**, and it is the single cheapest high-value experiment here.

### 3.3 Chain IDs in the summary JSON let us verify what we currently assume

`refold_af3.py` derives the target/binder split **positionally**: `_split_pae()`
slices at `target_len`, `_extract_ca_plddt()` slices `plddt_per_res[:target_len]`
/ `[target_len:]`, both on the assumption that AF3 preserves input chain order
(target = A first, binder = B second).

That assumption is currently unverifiable from AF3's output, and it is load-
bearing: if it ever silently inverted, `pae_bt_mean`/`pae_tb_mean` swap and
every downstream ipSAE and `consensus_iptm_mean` for AF3 is quietly wrong —
with no error and no obviously implausible numbers.

v3.0.4 adds chain IDs to the summary confidence JSON, which turns the
assumption into a cheap assertion. Given the repo's history of ordering bugs
(the Boltz-2 vs AF3 PAE transpose is documented in `CLAUDE.md` precisely
because it bit before), an assert here is cheap insurance.

Secondary: AF3 emits `chain_pair_iptm`, and with chain IDs attached we could
read the interface iPTM per chain pair directly rather than the global `iptm` —
the AF3 analogue of the ESMFold2 `chain_iptm_interface` gate the autosize loop
already uses.

### 3.4 CPU backend — narrow, but it unblocks CI

`--jax_backend` (`CPU`/`GPU`/`MPS`) is genuinely new; it does not exist at our
pin. CPU inference is ~100× slower, so it is **useless for production refolds**.

Its one real use: CI has no GPU, so today `refold-af3` is only ever smoke-tested
as `--help` plus an `import alphafold3, jax`. A CPU backend makes a true
end-to-end test possible — one tiny complex, asserting the CSV contract
(columns, pLDDT landing in 0–1 after rescale, PAE `.npy` shape, chain order per
§3.3). That would catch schema and ordering regressions that `--help` cannot.

Whether even a toy complex is fast enough for CI is unmeasured — the 100×
figure is against the 1,024-token benchmark, not a ~50-token toy. Measure
before committing to it, and keep it out of the default job if it is slow.

### 3.5 Two wins we can take **today**, unrelated to v3.0.4

Found while reading our runner for this analysis. Both are pre-existing misses,
not v3.0.4 features — flagged here rather than fixed, per the "mention, don't
silently expand scope" rule.

- **Every binder pays a full XLA compile.** `_run_single()` spawns a fresh
  `run_alphafold.py` subprocess per binder, and we never pass
  `--jax_compilation_cache_dir` (confirmed: no occurrence anywhere in
  `Evaluator/` or `install/`). Each design therefore recompiles from cold. AF3
  has exposed that flag since before our pin. On a several-hundred-design pool
  this is likely the dominant per-design overhead after inference itself.
- **We never set `--buckets`.** The default ladder starts at 256 and jumps to
  512, so a ~310-token complex pads to 512 — roughly 65% wasted tokens. Worse,
  binders of differing length can straddle a bucket boundary and trigger a
  *second* compile. Pinning a single tight bucket sized to the actual complex
  makes every design in a pool share one shape, which is also what makes the
  compilation cache above hit.

These compose: fixed bucket → identical shapes → cache hits → one compile per
pool instead of one per design.

---

## 4. Risks of upgrading

| risk | severity | mitigation |
|---|---|---|
| ~~`XLA_PYTHON_CLIENT_MEM_FRACTION` ignored by JAX 0.10.2 → OOM guard is a no-op~~ — **resolved**: the legacy name is still read; the real bug was that setting *both* names raises `ValueError` | was high | **fixed** in `_build_af3_env` (§3.1). Re-confirm on 0.10.2 via runbook step B before the first Spark pool |
| JAX 0.9.1 → 0.10.2 is a major dep jump; `jax[cuda12]` plugin must resolve on **linux-aarch64** for Spark | medium | build the env on Spark before touching x86 hosts; do not re-pin `AF3_COMMIT` until it does |
| Tokamax 0.0.12 Triton kernels on sm_121 | medium | `--flash_attention_implementation` (`triton`/`cudnn`/`xla`) already exists at our pin — `xla` is the fallback |
| Numerical drift vs already-published `af3_*` scores | medium | **do not mix engine versions inside one pool.** Re-refold a completed pool on both pins and compare `af3_iptm` before adopting; if it moves, note the version in the run's `settings.json` |
| Env rebuild churn (`build_data`, editable `binder-compare` re-install) | low | installer already handles re-pin + rebuild |

The numerical-drift item deserves emphasis: `consensus_iptm_mean` averages
across engines, so a systematic shift in AF3's iPTM shifts the ranking for
every design scored after the upgrade. Pools must not straddle the change.

---

## 5. Suggested verification order

Cheapest-and-most-informative first. Each step has a pass/fail check, so it can
run unattended.

1. **24 GB feasibility at the *current* pin** (§3.2) — run one ~300-token
   binder-target refold on a 24 GB Ampere box with
   `XLA_PYTHON_CLIENT_PREALLOCATE=false`.
   *Verify:* completes and produces a sane `iptm`. → If it passes, the ">100 GB"
   docs are wrong and AF3 goes fleet-wide. Biggest payoff, no upgrade needed.
2. **Env var name** (§3.1 ⚠️) — build `binder-eval-af3` at v3.0.4, set an
   absurdly low fraction under each name in turn.
   *Verify:* the run OOMs under the name JAX honours. → Tells us which name to
   set before any Spark run.
3. **Spark unified memory at v3.0.4** (§3.1) — the documented
   `PREALLOCATE=false` + `TF_FORCE_UNIFIED_MEMORY=true` recipe.
   *Verify:* completes without the fragment-and-hang; box stays up. → If it
   passes, delete the workaround.
4. **Score parity** (§4) — re-refold one completed pool on both pins.
   *Verify:* per-design `af3_iptm` delta and its effect on `rank`.
5. **Compile cache + fixed bucket** (§3.5) — independent of the upgrade.
   *Verify:* wall-clock per design across a ≥20-design pool, before vs after.
6. **Chain-ID assert** (§3.3), then **CPU CI smoke test** (§3.4) — only after
   the above land.

Steps 1 and 5 do not depend on the upgrade at all and can start immediately.

---

## 6. Explicitly *not* opportunities

Recorded so they are not re-litigated later:

- **Apple Silicon / `jax-mps`.** The headline feature of the release and worth
  nothing to us — the fleet is Linux x86_64 + aarch64, and AF3 still documents
  Linux as the only supported OS. Ignore.
- **CPU-only for production refolding.** ~100× slower. The 3-engine gate on a
  real pool is already the expensive step; CPU refolding is not a capacity
  strategy. CI only (§3.4).
- **`gs://` / `gcsfs`.** No cloud storage in the pipeline.
- **Relicensing.** Already Apache-2.0 at our pin (§1). Not a v3.0.4 delta, and
  it does **not** loosen the model-parameter terms.
- **Python 3.14.** We pin 3.12; no reason to move.

---

## 7. Recommendation

**Do not re-pin `AF3_COMMIT` yet.** Run verification steps 1 and 5 first — both
are independent of the upgrade, and step 1 may be worth more than the upgrade
itself. Re-pin only once steps 2–4 pass on Spark, since the upgrade's headline
benefit (§3.1) and its worst risk (the env-var no-op, §4) live on the same
machine and the failure mode there is a box reboot rather than a clean error.
