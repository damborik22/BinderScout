# Part T — Promera as a 5th refold engine + iCS metric: **NEGATIVE RESULT**

> **Verdict (2026-07-25):** Promera does **not** beat our incumbent engines and is **not**
> wired into `evaluate.sh`. Its binder-catch rate is statistically indistinguishable from
> random, and as a 4th consensus voter it is *worse* than adding a random selector.
> The env and weights stay installed (cheap) in case a future use appears.
>
> **Side finding, and its fate:** the benchmark also produced a per-engine advantage map
> showing no engine dominates and each catches binders the others miss (§5) — this **holds**.
> It further suggested a *length-dependent* Boltz-2/AF3 crossover that looked like a free
> accuracy win; that was tested on an independent set and **REFUTED** (§5.1). Do not
> implement length-conditioned weighting.

---

## 1. What Promera is

MIT-licensed open-source all-atom diffusion cofolder (built on boltz + alphafold3-pytorch +
openfold) from the MIT group — bioRxiv `2026.06.07.729267`, repo
[`bjing2016/promera`](https://github.com/bjing2016/promera), weights on HuggingFace
(`bjing-mit/promera/promera_2606.ckpt`, 1.89 GB, ungated). Dual-purpose: structure
prediction **and** binder design (minibinder + VHH nanobody, via a LigandMPNN/AbMPNN fork).

It emits three interface metrics per complex: **ipTM**, **ipSAE**, and
**iCS** (interface Contact Score = `{n_pred_contacts, avg_contact_prob}`).

The published claim that motivated Part T: iCS achieves "up to 20-fold enrichment of
binding pairs at 10% recall" and Promera-ipSAE reaches AUROC 0.70 on minibinders.

---

## 2. T1 — desk assessment (feasibility: all green, but premise already shaky)

| Question | Finding |
|---|---|
| License | **MIT** — commercial use OK |
| Weights | Public, 1.89 GB, no gating |
| Install | `pip install git+…/promera.git`; CLI `python -m promera input=schemas/ output=out/` |
| Inputs | Per-chain JSON schema `{type, sequence, entity_id, use_msa}`; MSAs via `tinyprot.mmseqs2` (ColabFold) |
| GPU | Boltz-class; ~5 s for a 64-token complex, ~92 s for 741 tokens on GB10 |

**The T1 red flag, which the benchmark went on to confirm:** Promera's own framing is
binder-vs-non-binder *discrimination/enrichment* — the authors do **not** claim iCS or
ipSAE rank *affinity among binders*. That is the same regime our metrics already cover,
not the affinity-ranking gap the ApoE4 campaign exposed.

---

## 3. T2 — the folds

| Set | Designs | Where | Notes |
|---|---|---|---|
| nipah pilot | 87 / 90 | Spark GB10 | 3 skipped >800 tokens (unified-memory hang risk) |
| **Adaptyv labelled** | **2515 / 2517** | **Clara H200** | 6-way sbatch array, ~1 h per 420-design chunk |

**2 designs are unfoldable:** `scarlet-raven-snow` and `radiant-shark-iron` (both fgf-r1)
contain a `:` in the sequence, which raises `KeyError: ':'` inside the tinyprot DataLoader
and **kills the whole worker**, silently truncating the tail of its chunk. On the first
pass this cost 222 designs; a targeted re-fold of the 220 innocent ones recovered them.
*Lesson: validate sequences for non-standard characters before a batch fold.*

---

## 4. T3 — results

### 4.1 Per-target screen AUC (same designs, 1963 with all 4 engines)

| Target | binders | Boltz-2 | AF3 | ESMFold2 | Promera |
|---|---|---|---|---|---|
| egfr | 130 | **0.76** | 0.51 | 0.66 | 0.52 |
| il7r | 36 | 0.65 | 0.65 | **0.68** | 0.50 |
| pd-l1 | 22 | 0.71 | **0.72** | 0.66 | 0.61 |
| nipah | 1 | — | — | — | — (n=1, ignore) |

**Target wins: ESMFold2 ×2, Boltz-2 ×1, AF3 ×1, Promera ×0.**
Promera is at chance (0.50–0.52) on the two targets with the most binders.

nipah pilot agreed: Promera ipSAE **0.641** vs incumbent Boltz-2 ipSAE_min **0.686**.

### 4.2 The pLDDT trap (a metric that looks like a win and isn't)

Pooled across all targets, `promera_plddt` scores **0.826** — higher than any incumbent
metric. It is **not** a usable screen: it is a Simpson's-paradox artifact. Complex-pLDDT
separates *well-folded designs* and *which target a design belongs to* across a mix with
wildly different binder rates (nipah 1/927 vs egfr 130/826). **Within** a single target it
collapses to ~0.60. Do not report pooled AUC across heterogeneous targets without the
within-target check.

### 4.3 The decisive test: is Promera better than a *random* 4th voter?

The naive complementarity argument ("Promera catches 4 binders the others miss, same as
Boltz-2") fails its null test. Any additional selector catches some binders uniquely simply
by widening the net.

Top-25% per target, 222 binders, 200 random-voter simulations:

| | catch rate | vs chance (0.25) |
|---|---|---|
| ESMFold2 | 0.671 | far above |
| AF3 | 0.617 | far above |
| Boltz-2 | 0.586 | far above |
| **Promera** | **0.293** | **at chance** |

- 3 incumbent engines, union recall: **184/222 = 0.829**
- \+ Promera (4th): 188/222 = 0.847 — gain **+4**
- \+ **random** 4th voter: mean gain **+9.2**, 95th pct +13

**A random voter beats Promera's contribution in 100% of 200 simulations.** Promera is not
merely "no better than random" — it is slightly *worse*, because its picks correlate with
design foldedness rather than binding, so they pile onto designs the other engines already
caught.

Script: `runs/adaptyv_promera_bench/random_voter_test.py`.

### 4.4 Affinity ranking — unchanged, unsolved

Spearman(metric, −log₁₀Kd) among binders is ~0 or negative for **every** metric including
all of Promera's. Consistent with Part N, SKEMPI, OpenBind and Adaptyv. Promera does not
touch this gap.

---

## 5. The real payoff — per-engine advantage map

Each incumbent engine earns its slot; **no engine dominates**, reproducing ProtDBench's
"substantial verifier-dependent bias" result on our own stack. Dropping any one engine
loses uniquely-caught true binders (AF3 −7, Boltz-2 −4, ESMFold2 −3).

**AUC by binder-length tercile (1963 designs):**

| tercile | Boltz-2 | AF3 | ESMFold2 | Promera |
|---|---|---|---|---|
| short (10–82 aa) | 0.80 | **0.44** | 0.83 | 0.69 |
| mid (83–127 aa) | 0.66 | 0.64 | 0.66 | 0.61 |
| long (128–259 aa) | **0.51** | 0.78 | 0.69 | 0.45 |

**Boltz-2 and AF3 are near-perfectly anti-correlated by binder length.** AF3 is
*anti-predictive* on short binders (0.44 pooled; **0.33 within egfr**) — precisely where
Boltz-2 is strongest (0.80 pooled; **0.85 within egfr**). The effect **survives the
within-target test** on egfr (826 designs, 130 binders, widest length range), so unlike the
pLDDT number it is not a target confound.

This *looked* like a free accuracy win: length-conditioned weighting, no new engine, no extra
GPU. It was tested on independent data and **did not survive** — see §5.1.

### 5.1 Independent validation of the length crossover — **REFUTED** (2026-07-25)

Refolded the **BindCraft Nature-2025** de-novo set through all three engines
(`runs/denovo_lengthtest/`): 110 designs / 7 targets / 45 binders, independent of Adaptyv,
balanced 15/15/15 across length terciles, length range 69–178 aa (straddles the ~100 aa
crossover). All three engines scored **the same 110 designs**.

| tercile | n | binders | Boltz-2 | AF3 | ESMFold2 |
|---|---|---|---|---|---|
| short (69–92 aa) | 39 | 15 | 0.58 | **0.74** | 0.73 |
| mid (93–111 aa) | 35 | 15 | 0.67 | 0.71 | 0.74 |
| long (113–178 aa) | 36 | 15 | 0.42 | 0.50 | 0.50 |

**The discovery predicted short → Boltz-2 0.85 ≫ AF3 0.33. The independent set gives
short → Boltz-2 0.58 < AF3 0.74 — the gap runs the opposite direction.**

Within-target check on PD1 (the only independent target with power — 53 designs, 13 binders),
mirroring the egfr check that originally validated the finding:

| PD1 | Boltz-2 | AF3 | ESMFold2 |
|---|---|---|---|
| short | 0.82 | **0.83** | 0.91 |
| long | 0.79 | 0.73 | 0.82 |

**AF3 is perfectly healthy on short binders (0.83).** Its 0.33 collapse on egfr was
**target-specific**, not a property of the engine. The point estimates are *opposite-signed*
to the prediction — evidence against, not merely an underpowered null.

**→ Do NOT implement length-conditioned engine weighting. Keep the uniform consensus.**

**What does replicate:**
1. **All engines degrade on long binders** (0.58–0.74 short → 0.42–0.50 long) — a *shared*
   effect, not a differential one. Long binders are harder to screen for everyone; this does
   not imply per-engine weighting.
2. **No engine dominates** — per-target winners vary (PD1 ESMFold2 0.88 · IFNAR2 Boltz-2 0.72 ·
   DerF7 AF3 0.79 · PD-L1 ESMFold2 0.64). The cross-engine consensus design is reconfirmed on a
   second independent dataset.
3. **ESMFold2 is the most consistent** on this set (pooled 0.643; best on 3 of 5 powered
   targets) — consistent with the earlier BindCraft screen replication (0.91).

**Methodological note.** This is the third Simpson's-paradox-family trap in one investigation:
pooled `promera_plddt` (0.826 → ~0.60 within-target), Promera's "unique catches" (beaten by a
random voter), and now the length crossover. **A per-stratum effect discovered on one target
must be reproduced on an independent target set before it is allowed to change the ranking
layer.** Two engines must also be compared on the *same designs* — mid-run, Boltz-2 and AF3
had scored almost disjoint sets and the preliminary table pointed the wrong way.

---

## 6. Decision

- ❌ **Do not wire Promera into `evaluate.sh`** — fails the Part T gate (must beat incumbent
  macro-AUC; it loses on every target with real binder counts).
- ❌ **Do not add it as a 4th consensus voter** (Part O framing) — indistinguishable from a
  random selector.
- ✅ **Keep the env + weights installed** on Spark and Clara (`binder-eval-promera`,
  `weights/promera/promera_2606.ckpt`) — cheap, and its MIT nanobody designer may still be
  worth evaluating for Part V.
- ✅ **Adopt the per-engine advantage map** as the actionable output (§5).

---

## 7. Reproduction

**Data + scripts:** `runs/adaptyv_promera_bench/`
(`promera_adaptyv_complete.csv`, `engine_advantage.py`, `random_voter_test.py`,
`length_within_target.py`, `score_all.py`, `parse_recursive.py`).

**Install — x86 / Hopper (Clara H200): vanilla.** `pip install git+…/promera.git`,
download weights, `python -m tinyprot.init --download`. No patches needed.

**Install — aarch64 / Blackwell (DGX Spark GB10, sm_121): three stacked fixes**, all
encapsulated in `Evaluator/scripts/promera_env.sh`:
1. The pinned `torch==2.9.0` installs **CPU-only** on aarch64 → reinstall from the **cu130**
   index (`--index-url https://download.pytorch.org/whl/cu130`). The cu128 build fails with
   `nvrtc: invalid value for --gpu-architecture` because CUDA-12.8's NVRTC does not know sm_121.
2. cuequivariance's cu12 kernels then cannot find `libcublas.so.12` → put every
   `site-packages/nvidia/*/lib` plus `cuequivariance_ops/lib` on `LD_LIBRARY_PATH` so the
   cu12 and cu13 runtimes coexist in one process. (Promera hard-calls cuequivariance for
   triangle-multiply; there is no pure-torch fallback.)
3. Triton 3.5 bundles a CUDA-12.8 `ptxas` (max sm_120) → `TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas`
   (the system CUDA-13 one, which supports sm_121).

**Output format:** `<out>/<id>/<id>_seed0_samp0_conf.json` with `complex_iptm`, `ipsae[pair]`,
`iCS[pair] = {n_pred_contacts, avg_contact_prob}`, `complex_plddt`, `ptm`.
