# AF3-replacement benchmark: results

Status: **Part 1 result (2026-11-05), followed by the owner's decision (2026-11-07; see "Outcome" below).** The
tables below are the Part 1 result as it stood; the outcome section records what was decided and one correction
to this report's text. Aggregate numbers only; no per-design labels or scores are reproduced here. Licence terms per candidate are in
`second_engine_licences.md`; how every run was made is in `second_engine_benchmark_runbook.md`.

## Question

Can a commercially usable engine take the slot AF3 holds in the 3-engine refold panel
(Boltz-2 + AF3 + ESMFold2) and give a similar ROC AUC of `consensus_iptm_mean` on the curated Adaptyv
benchmark? Boltz-2 and ESMFold2 stay in every panel.

## Method (fixed before any run)

- Pool: 563 designs, 4 targets (EGFR 190 designs / 86 binders, IL7R 96 / 60, Nipah 211 / 80, PD-L1 66 / 32).
- Score: mean of the three engines' `*_pae_iptm` (point-PAE re-derivation by the shared kernel, per-design d0)
  per design; AUC of binder versus non-binder per target; macro = mean over the 4 targets.
- Panels: P0 = {Boltz-2, AF3, ESMFold2}; candidate k = {Boltz-2, k, ESMFold2}; floor = {Boltz-2, ESMFold2}.
  P0 and floor are read from the existing merged table; both reproduce the recorded figures exactly
  (macro AUC 0.7231 and 0.7279). Only the candidate column is new.
- Paired bootstrap (2,000 resamples, seed 0, designs resampled within target) of macro AUC(k) minus macro AUC(P0).
- Pass rule: (a) the 95% interval of the macro difference is not wholly below 0; (b) the point difference is
  not below -0.02; (c) no target is worse than P0 by more than 0.05; (d) every design has a score
  (all 563 had one in every run).
- Every candidate ran at **1 sample, 1 seed**, on the same cached target MSA, one design at a time.

## Result

Macro / median AUC and per-target AUC, with the difference to P0 (point estimate and paired 95% interval) and the pass rule:

| Panel | EGFR | IL7R | Nipah | PD-L1 | Macro | Median | Macro diff vs P0 [95% CI] | Verdict |
|---|---|---|---|---|---|---|---|---|
| P0: Boltz-2 + AF3 + ESMFold2 | 0.661 | 0.728 | 0.736 | 0.767 | 0.7231 | 0.7323 | reference | reference |
| Floor: Boltz-2 + ESMFold2 | 0.732 | 0.723 | 0.762 | 0.695 | 0.7279 | 0.7277 | +0.0048 [-0.021, +0.030] | fails (c): PD-L1 -0.072 |
| + Chai-1 0.6.1 | 0.762 | 0.743 | 0.766 | 0.646 | 0.7293 | 0.7523 | +0.0062 [-0.024, +0.036] | fails (c): PD-L1 -0.120 |
| + RF3 (rc-foundry 0.2.0) | 0.680 | 0.733 | 0.728 | 0.719 | 0.7147 | 0.7232 | -0.0084 [-0.031, +0.015] | **passes** |
| + Protenix v1 (base default) | 0.643 | 0.725 | 0.718 | 0.733 | 0.7044 | 0.7213 | -0.0186 [-0.038, +0.001] | **passes** (point estimate -0.0186, 0.0014 inside limit b) |
| + OpenFold3 0.5.1 (OpenBind-0) | 0.666 | 0.695 | 0.755 | 0.699 | 0.7039 | 0.6969 | -0.0192 [-0.047, +0.008] | fails (c): PD-L1 -0.068 |

Per-target difference to P0 (the quantity clause c reads):

| Panel | EGFR | IL7R | Nipah | PD-L1 |
|---|---|---|---|---|
| Floor | +0.071 | -0.005 | +0.025 | -0.072 |
| Chai-1 | +0.101 | +0.014 | +0.030 | -0.120 |
| RF3 | +0.018 | +0.005 | -0.009 | -0.048 |
| Protenix | -0.019 | -0.004 | -0.018 | -0.034 |
| OpenFold3 | +0.005 | -0.033 | +0.019 | -0.068 |

Each candidate against the **floor** (candidate minus floor, macro AUC, paired 95% interval):

| Candidate | Difference [95% CI] | Reading |
|---|---|---|
| Chai-1 | +0.0014 [-0.019, +0.022] | indistinguishable from the floor |
| RF3 | -0.0132 [-0.035, +0.009] | indistinguishable from the floor |
| Protenix | -0.0235 [-0.047, +0.0003] | indistinguishable from the floor, barely (upper end just above 0) |
| OpenFold3 | -0.0240 [-0.048, -0.002] | **below the floor** (interval wholly below 0) |

Single-engine AUC on the same designs (macro, then EGFR / IL7R / Nipah / PD-L1), for context:
Boltz-2 0.720 (0.765 / 0.676 / 0.708 / 0.733); ESMFold2 0.693 (0.675 / 0.699 / 0.744 / 0.655);
Chai-1 0.695 (0.781 / 0.714 / 0.727 / 0.556); AF3 0.613 (0.394 / 0.719 / 0.551 / 0.790);
RF3 0.635 (0.592 / 0.681 / 0.516 / 0.749); Protenix 0.574 (0.413 / 0.652 / 0.505 / 0.724);
OpenFold3 0.557 (0.518 / 0.581 / 0.452 / 0.676).

Diagnostics (mean over targets): Spearman of the panel score against P0 and overlap of the top 20% with P0.
Floor 0.914 / 0.70; Chai-1 0.870 / 0.62; RF3 0.931 / 0.82; Protenix 0.936 / 0.85; OpenFold3 0.891 / 0.76.

## What this does and does not say

1. **The three-engine panel has little to gain from its third engine on this pool, and that is what most of the passes mean.**
   AF3 alone ranks worst of the three incumbents (macro 0.613; EGFR 0.394, below chance), and the floor
   without it already scores 0.7279. A candidate that passes therefore shows that swapping the third engine
   costs little, not that it matches AF3. Of the candidates only Chai-1 is a good predictor on its own
   (macro 0.695, on a level with ESMFold2), and it is the weakest single engine on PD-L1 (0.556).
2. **Sentence required by the design:** RF3 and Protenix pass but are indistinguishable from the two-engine floor. Such an
   engine is still worth shipping, because the slot exists to keep the 3-engine gate satisfied without AF3, not to raise AUC.
3. **Clause (c) is too noisy to carry the verdict on this pool.** PD-L1 has 66 designs (32 binders) and the
   clause reads a single point estimate with no interval. The two-engine floor, which is P0 minus one engine, fails
   the same clause on the same target (-0.072), and Chai-1, whose macro AUC is the highest in the table, fails it only
   through PD-L1. On the pass rule as written the result is **RF3 and Protenix pass; Chai-1 and OpenFold3 fail on clause (c) alone**.
   *(Superseded 2026-11-07: the per-target intervals were computed afterwards and are in the Outcome section below.)*
   Whether to keep clause (c) was the owner's decision (see below), not something this report changed.
4. **OpenFold3 is the one clear negative:** its macro difference to the floor has an interval wholly below zero and it is the weakest
   single engine here (0.557).
5. **Hypothesis, not a result.** Four targets, 563 designs, one pool; Adaptyv and ProteinBase are one dataset. Earlier single-pool
   effects in this project were retracted. Differences of about 0.02 macro AUC are inside the paired interval for every candidate
   except the OpenFold3-versus-floor gap. Read the table as ordering plausible options, not as proof of equivalence.

## Training cutoffs (primary sources, read 2026-11-05)

The Adaptyv targets, or close homologues, may be in a candidate's training set, as they may be for AF3; a later cutoff means more
exposure. A cutoff date says nothing about homology filtering.

| Engine / checkpoint | PDB training cutoff | Source |
|---|---|---|
| AF3 (baseline) | September 2021 | OpenBind-0 announcement table of other models' cutoffs |
| Protenix `protenix_base_default_v1.0.0` | 2021-09-30 | Protenix `docs/supported_models.md` and the Protenix-v1 technical report (a separate `protenix_base_20250630_v1.0.0` exists with cutoff 2025-06-30; it was **not** run) |
| Chai-1 0.6.1 | 2021-01-12 | Chai-1 technical report, section 5.2 (the README states none; that the 0.6.1 weights equal the report's was not verified) |
| RF3 `rf3_foundry_01_24_latest_remapped.ckpt` | "01/24", January 2024 (day not stated; the paper says both "released" and "deposited") | foundry checkpoint registry at v0.2.0, RF3 README, RF3 preprint appendix |
| OpenFold3 0.5.1 OpenBind-0 | 30 June 2025 | OpenFold3 README, OpenBind-0 announcement |

Distillation data differs by engine (AFDB only for Chai-1; MGnify monomers and disorder sets for Protenix; AFDB domain pairs and
nucleic-acid sets for RF3; not stated for OpenBind-0). RF3 and OpenFold3 have the latest cutoffs, so the longest exposure to PDB entries.

## Settings and caveats that bear on the numbers

- **Sample count.** Every candidate ran at 1 sample and 1 seed. The sample count used for the AF3 numbers in P0 is not recorded in the
  merged table, and the AF3 script's own default is 5. Sample-to-sample spread was tiny in the smokes (RF3 none measurable, Protenix 0.004
  in ipTM), but a 5-sample rerun was not done for any candidate.
- **RF3 diffusion steps** were 200 (parity with the Chai-1 and Protenix settings), not the 50 RF3 ships with; recycles 10, cuEquivariance disabled.
- **Protenix** ran with torch kernels and torch layer norm (the default kernels need NVIDIA-proprietary wheels, unused here).
  Default and torch kernels differed by at most 0.004 ipTM in the smoke.
- **Chai-1** 0.6.1 at the adapter defaults (3 recycles, 200 diffusion steps, ESM2 on, no templates). Its own ipTM uses a different d0
  convention, so the re-derived value reads *higher* than its own ipTM (median offset -0.087), unlike the other engines (lower);
  within a target the two rank together (Spearman 0.83 to 0.98, lowest on IL7R). The consensus averages levels across engines, so a
  level difference moves the mean but this was not isolated as a cause of any result here.
- **Nipah** has a very shallow target MSA (26 sequences in the cached target MSA, recorded in the Chai-1 run sidecars); Nipah scores are
  low for every engine (median re-derived ipTM 0.11 to 0.34).
- **Re-derived versus engine ipTM:** rank-equivalent within each target (Spearman 0.98 to 0.9995) apart from Chai-1 on IL7R (0.83),
  with level offsets (engine minus re-derived) from about 0 to +0.10 for OpenFold3, Protenix and RF3, larger on the low-scoring EGFR and Nipah pools.
- Diffusion and recycling settings are not recorded in the OpenFold3, Chai-1 and Protenix run sidecars; they are the adapter defaults at
  the tested commit. RF3's are recorded.
- Hardware: RTX 3090, L40S and H200 cards. RF3 with cuEquivariance disabled needs a card of at least 40 GB
  for the roughly 770-token EGFR and Nipah complexes (peak 33.5 to 36.8 GiB card-wide in the runs).
- The RF3 and Protenix environments still carry NVIDIA-proprietary wheels as install dependencies that the runs do not execute
  (see the licence record).

## Decisions asked of the owner (answered 2026-11-07; the answers are in "Outcome" below)

1. Clause (c): keep as written (RF3 and Protenix pass), or relax it for small targets (for example by requiring the per-target
   interval, not the point estimate, to exclude -0.05), which would leave Chai-1 eligible.
2. Which engines to register in Part 2: the pass rule gives RF3 and Protenix; Chai-1 has the best macro AUC and the best single-engine
   AUC of the candidates but fails clause (c) on PD-L1 (n = 66).
3. Whether to spend a 5-sample rerun on PD-L1 for the chosen engines before registering them.
4. Position on the unused proprietary dependency wheels in the RF3 and Protenix environments.

## Outcome (2026-11-07)

### Owner decisions

- **Criteria.** Success is a similar ROC AUC of `consensus_iptm_mean` on this benchmark, and **no increase in GPU demand**:
  the ceiling is a 24 GB card, which AF3 and ESMFold2 already need. The replacement is **opt-in; AF3 stays the default.**
- **Answers to the four questions above.**
  1. **No relaxation of clause (c) was applied**: the verdicts in the table above stand. The per-target intervals below show that the
     alternative reading (fail only if the interval is wholly below 0) gives the same split for the engines that matter here.
  2. **Only Protenix is registered.** RF3 passes the rule but is out on GPU demand: 33.5 to 36.8 GiB card-wide with
     cuEquivariance disabled; with it enabled RF3 fits a 24 GB card but needs NVIDIA's proprietary wheels at run time.
     Chai-1 fails target PD-L1 on either reading (below). OpenFold3 is below the Boltz-2 + ESMFold2 floor.
  3. The 5-sample PD-L1 rerun was **not done**; Protenix is registered at the 1 sample and 1 seed it was benchmarked at.
  4. Protenix is always run with torch kernels and torch layer norm, so the proprietary cuEquivariance wheels that `pip install
     protenix` pulls are installed but not used at run time; the installer's licence text says so and asks before downloading.

### Per-target paired differences to P0, with 95% intervals

**This is the first time per-target intervals were computed.** Same paired bootstrap as above (2,000 resamples, seed 0, designs
resampled within each target); each cell is the AUC difference to the AF3 panel with its interval. The sentence in the
"What this does and does not say" section that they were not computed is superseded by this table.

| Panel | EGFR | IL7R | Nipah | PD-L1 | Macro |
|---|---|---|---|---|---|
| Floor (Boltz-2 + ESMFold2) | +0.071 [+0.037, +0.110] | -0.005 [-0.041, +0.032] | +0.025 [-0.015, +0.065] | -0.072 [-0.157, +0.002] | +0.0048 [-0.0214, +0.0299] |
| Chai-1 | +0.101 [+0.055, +0.155] | +0.014 [-0.029, +0.062] | +0.030 [-0.017, +0.075] | **-0.120 [-0.218, -0.035]** | +0.0062 [-0.0244, +0.0361] |
| RF3 | +0.018 [-0.010, +0.047] | +0.005 [-0.041, +0.054] | -0.009 [-0.042, +0.019] | -0.048 [-0.113, +0.006] | -0.0084 [-0.0313, +0.0147] |
| Protenix | -0.019 [-0.046, +0.005] | -0.004 [-0.045, +0.040] | -0.018 [-0.058, +0.016] | -0.034 [-0.085, +0.009] | -0.0186 [-0.0384, +0.0008] |
| OpenFold3 | +0.005 [-0.018, +0.029] | -0.033 [-0.101, +0.034] | +0.019 [-0.023, +0.063] | **-0.068 [-0.141, -0.006]** | -0.0192 [-0.0469, +0.0078] |

### Readings of clause (c)

- **As written** (point difference no worse than -0.05 on every target): floor, RF3 and Protenix pass; Chai-1 (-0.120) and
  OpenFold3 (-0.068) fail on PD-L1 (the floor's -0.072 would also fail it, as the report noted).
- **Fail only if the interval is wholly below 0:** the same split. Chai-1 and OpenFold3 have an interval wholly below 0 on PD-L1;
  the floor, RF3 and Protenix do not.
- **Fail only if the interval is wholly below -0.05** (the relaxation asked about in question 1): Chai-1 and OpenFold3 would pass.
  That reading is too loose to use, because it lets through OpenFold3, which sits below the floor.
- Chai-1's macro gain is almost all EGFR (+0.101), where AF3 is weakest in this pool (single-engine AUC 0.394).

### Decision

Register **Protenix v1.x only** (`protenix_base_default_v1.0.0`, torch kernels, 1 seed, 1 sample), as an opt-in second-slot engine.
Macro AUC 0.7044 against 0.7231 for the AF3 panel and 0.7279 for the floor; paired macro difference -0.0186 [-0.0384, +0.0008].
**It is the thinnest of the passes** (the point estimate is 0.0014 inside the -0.02 limit), it is a **hypothesis from four targets and
one pool, not a result**, and nothing here says it matches AF3: the passes show that swapping the third engine costs little on
this pool.

Memory against the owner's constraint: with torch kernels Protenix peaked at 21,282 MiB (20.8 GiB) card-wide on a 24,576 MiB RTX 3090
(headless) for the longest design (Nipah target 602 aa + 177 aa binder, 779 tokens, 1 sample; ipTM 0.895), and at 20,939 MiB (20.4 GiB)
on a 46 GiB L40S (EGFR, about 772 tokens). That fits a 24 GB card with about 3 GiB to spare, less if the card also drives a display;
the 3090 figure is one design. Part 2 (opt-in `--second-engine protenix`, panel recorded in `metrics.csv`) is described in the
CHANGELOG.
