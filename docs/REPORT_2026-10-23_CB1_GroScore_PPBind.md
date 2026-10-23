# Report: CB1, GroScore and PPBind (2026-10-13 to 2026-10-23)

One page of verdicts, with the denominator beside every number. Raw output and scripts are archived on the MUNI share (section 6). Every result below is a single-pool result and should be read as a hypothesis until it replicates.

## 1. Bottom line

| question | answer |
|---|---|
| Does the 3-engine ranking carry signal on the independent Claude-binder pool (CB1)? | Yes, modestly: macro AUC 0.671 for `consensus_iptm_mean` (best published ipSAE about 0.72, binder length alone 0.428). |
| Does the 3-engine mean beat the best single engine there? | No. mean3 minus best single engine is -0.015 [-0.05, +0.02]. Same finding as AK1. |
| Can GroScore (steered MD) pick the best of our top 50? | No. It did not beat the engine mean on PD-L1 or CALCA. |
| Does PPBind-1D or PPBind-3D identify binders among de novo designs? | No. Macro AUC 0.43 (1D) and 0.48 (3D) on Adaptyv, against 0.70 for the engine mean. |
| Anything worth following up? | One weak hint: PPBind-3D ranks CALCA hits by Kd (Spearman +0.27, p = 0.007). One target, no replication anywhere else. |

## 2. CB1: the Claude binder-design dataset (900 monomer designs, 10 targets, 263 binders)

Run through the unchanged Evaluator at `v2.0.0` (30 chunks, six Clara H200 workers). Analysis was pre-registered in `docs/PLAN_CB1_claude_binders.md`; the decision rule was not to search for a better metric on this pool.

| metric | macro AUC |
|---|---|
| Boltz-2 | 0.616 |
| AF3 | 0.617 |
| ESMFold2 | 0.687 |
| `consensus_iptm_mean` | 0.671 |
| best published ipSAE column | about 0.72 |
| binder length alone | 0.428 |

AK1 contrasts (bootstrap within target): mean3 minus best single engine -0.015 [-0.05, +0.02]; minus AF3 +0.054; minus Boltz-2 +0.055; minus ESMFold2 -0.015. Per target the ranking is strong on PD-L1 (0.90) and TREM2 (0.92) and at chance on BBF-14, BHRF1 (0.50) and Nipah-G (0.55). ESMFold2 alone is as good as the mean (difference within the interval) and the mean beats AF3 and Boltz-2 by about 0.055 each. That replicates AK1: the mean is never the worst and is not better than the best single engine.

## 3. CC1: CALCA / CBG refold

CALCA: 114 designs scored, 99 hits (54 strong, Kd <= 10 nM), 15 misses. Engine-mean hit/miss AUC 0.695; Spearman with log Kd among the hits -0.36. CBG outcomes are in the CC1 archive tables and are not re-summarised here. Protein-Hunter ids contain a space; this produced the Evaluator naming collision fixed in v2.0.1 (section 5).

## 4. GroScore (steered MD, score = pulling work, more negative is better)

| set | designs | cost | result |
|---|---|---|---|
| PD-L1 pilot, 2 cycles | 66 (32 binders) | about 10 GPU-h | AUC 0.764 [0.64, 0.87] vs engine mean 0.778, Boltz-2 0.820 |
| CALCA, 3 cycles | 114 | 7 jobs x 2 H200, 6.3 to 7.2 h | hit/miss AUC 0.60 vs 0.70; Spearman with log Kd 0.25 (p = 0.012), 0.16 after removing length; re-ranking the top 50 gained one design (noise) |

Confidence intervals are wide (median +-155 kJ/mol at 2 cycles, +-84 at 3). Verdict: at best a second opinion on a shortlist; not worth running on every design.

## 5. v2.0.1

`binder_id` is the first whitespace token of a FASTA header, so ids containing a space collided on disk (`__2`, `__3`) and mis-named structures. v2.0.1 refuses such headers with a message naming the fix and sanitises ids in `write_fasta`. Commit 679e6b3 on `v2.0.x`, tag `v2.0.1`; BM1/BM2/BM4/BM5 and Clara re-pinned. The CBG Protein-Hunter structures keep the collided names; their CSVs are fine, so map by sequence.

## 6. PPBind-3D / PPBind-1D (Antibody Therapeutics 2026, DOI 10.1093/abt/tbag053)

Monotonic multi-task affinity predictor; output dG in kcal/mol, more negative is stronger. The released repo has no inference script, so we wrote one (`infer.py`, `infer3d.py`) and patched four import / constants issues (see the archive's `repo_patches.diff`). 3D uses real DSSP; 1D stubs DSSP (its network does not use it). Both load the released checkpoints with `strict=True`. An early run used `strict=False` and produced near-zero predictions; that was caught and fixed, and all reported numbers are from the strict load. Sanity check on the paper's 9 example complexes: Spearman 0.996 (3D), 0.93 (1D), likely training data, so this checks the plumbing and not generalisation.

**Adaptyv benchmark, 2,033 designs, 332 binders** (AUC of -dG vs binder label):

| target | designs | binders | 3D | 1D | engine mean | length alone |
|---|---|---|---|---|---|---|
| EGFR | 826 | 128 | 0.559 | 0.329 | 0.630 | 0.562 |
| IL-7Ra | 96 | 61 | 0.460 | 0.380 | 0.749 | 0.297 |
| Nipah | 1,045 | 111 | 0.438 | 0.526 | 0.636 | 0.536 |
| PD-L1 | 66 | 32 | 0.463 | 0.496 | 0.778 | 0.520 |
| macro | 2,033 | 332 | 0.480 | 0.433 | 0.698 | 0.479 |

Expressed designs only (1,803): macro 3D 0.477, 1D 0.432, engine mean 0.693. Spearman with the engine mean: 3D -0.157, 1D 0.064.

**CALCA (114; 99 hits):** hit/miss AUC 3D 0.562, 1D 0.512, engine mean 0.695. Spearman with log Kd among hits: 3D +0.271 (p = 0.007, right direction, length-independent, rho -0.09), 1D -0.073 (p = 0.47). Combining engine mean and 3D (z-score sum) gives Spearman -0.41 against -0.362 for the engine mean alone. Top-50 re-ranking: no meaningful gain.

**Verdict:** do not use PPBind to rank our binders. The only unexplained positive (3D vs Kd on CALCA) needs a second target with Kd values before anyone relies on it.

## 7. Caveats

- Each label set has its own denominator convention (Part AK rule for CALCA/CBG; AK1 labels unexpressed designs non-binders). Numbers are not comparable across pools without that.
- The CB1 vendors disagree on 136 designs; assay formats differ (avidity).
- Archive read-back verifies copies on the mounted share against the local sha256, not an independent download.
- `work3d/` (8 GB of PPBind intermediate features) and the PPBind conda env are not archived; both regenerate from the archived inputs and `build_env.sh`.
