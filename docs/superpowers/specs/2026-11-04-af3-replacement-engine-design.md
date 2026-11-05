# Design: an opt-in, commercially usable replacement for AF3

Status: draft for approval, 2026-11-04. Nothing in this document is built yet.

## Why

Industry users who met BinderScout at a conference cannot legally obtain or run the AlphaFold 3
weights, so they cannot use the three-engine refold (Boltz-2 + AF3 + ESMFold2) and the
`consensus_iptm_mean` ranking built on it. We want a user to be able to ask for a different
second engine, one whose code and weights allow commercial use, without losing the ranking's
quality.

## Goals

1. An opt-in switch that fills the AF3 slot with a commercially usable engine. AF3 stays the default.
2. A benchmark that tells us, with numbers, which candidate engines can fill the slot.
3. "Good enough" means: on the curated Adaptyv benchmark (563 designs, 4 targets, experimental
   binding labels, per-engine refolds already on disk), the ROC AUC of `consensus_iptm_mean` for the
   panel with the replacement is similar to the current panel's. Boltz-2 and ESMFold2 stay in the panel.
4. The three-engine gate and the single `rank` column keep working unchanged.

## Non-goals

- Replacing Boltz-2 or ESMFold2. The owner has accepted their terms for this purpose.
- Matching AF3's ordering of designs. The target is equal skill at separating binders from
  non-binders, not agreement with AF3.
- Legal advice. We record each licence source and date; a user's counsel decides.
- Removing AF3 support, or making any replacement the default.

## Anti-goals (a technical success that would still be a failure)

- A replacement engine's scores written into `af3_*` columns, so a report claims AF3 produced them.
- A ranking from two different panels being compared as if it were one scale.
- A "pass" that rests on one target or on a metric picked after seeing the results.
- An installer that downloads weights whose terms the user was never shown.

## Constraints

- Public repository: no machine names, accounts or paths of ours in tracked files.
- Existing contracts hold: PAE is stored as `[binder|target]`; `*_pae_iptm` is our own re-derivation
  from each engine's PAE with the shared kernel; a design needs at least 3 engines to be gate-eligible.
- A candidate must emit a PAE matrix for a protein-protein complex. Without PAE it cannot feed the
  ranking, and we do not use an engine's own ipTM for ranking.
- Target sizes are about 250 to 600 tokens; the benchmark must be runnable on 24 GB cards or on the
  larger hosts we have (an aarch64 GB10 host, a cluster, x86_64 boxes).

## Candidates (licence reading as of 2026-11-04, each re-read by a second reviewer)

| Engine | Reading | What to watch |
|---|---|---|
| OpenFold3 0.5.1 | Apache-2.0 code; weights Apache-2.0 per the OpenBind-0 announcement | no licence file beside the weights; "research preview"; docs state a 32 GB floor; PAE shape unconfirmed |
| Protenix v1.x | Apache-2.0 code and weights | **v2 weights are proprietary; pin v1.x**; non-commercial until 2024-12 |
| Chai-1 0.6.1 | Apache-2.0 code and weights (relicensed 2024-11-27) | CLI does not write PAE; must call the model from Python |
| RF3 (in `rc-foundry`) | BSD-3; weights covered by a sentence added 2026-10-13 on the `production` branch only | its authors place it below AF3; already installed for RFD3 |
| IntelliFold-2 | reported Apache-2.0 code and weights | NOT yet verified: its NOTICE says it vendors an "Apache-2.0 release of AlphaFold 3"; AF3's own code is non-commercial. Must be resolved before any use |

Ruled out: HelixFold3 (non-commercial), Boltz-1 (same family as Boltz-2, adds no independence).
AtlasFold-M (MIT, 2026) was reported but is unexamined.

## Design

### Part 1: the benchmark (built first, changes no pipeline code)

- Reuse the existing Boltz-2, AF3 and ESMFold2 results for the 563 designs; only the candidate engine is
  run anew. Verified on the lab's private share (folder `3engine_binder_comparison`): `adaptyv_merged.csv` holds
  all 563 designs with `boltz_pae_iptm`, `af3_pae_iptm`, `esmfold2_pae_iptm` and `consensus_iptm_mean` filled in;
  `experimental_binding_labels.csv` holds the labels (columns `id`, `target`, `binding`, `binding_strength`,
  `kd`); `raw_refold/` holds twelve per-engine, per-target CSVs that carry the binder and target sequences
  (`sequence`, `target_sequence`) needed to run a candidate. **No PAE files were found there**, so the three
  existing engines cannot be re-derived from this folder, and do not need to be: P0 is read straight from
  the merged CSV, and its AUC must be reproduced first (step 0) before any candidate is run.
- One refold script per candidate, run outside `evaluate.sh`. Each writes a CSV with the same
  columns as `refold_af3.py`, prefixed with its own name, with PAE in `[binder|target]` order and
  `<engine>_pae_iptm` derived by the shared kernel. Per-engine ordering is pinned by a test on a
  small fixture, as AF3's is now.
- Panels compared on the same designs: P0 = {Boltz-2, AF3, ESMFold2}; one panel per candidate k =
  {Boltz-2, k, ESMFold2}; and the two-engine floor {Boltz-2, ESMFold2}.
- Metrics, fixed before any run: per-target ROC AUC of `consensus_iptm_mean` for binder versus
  non-binder, with the median and the macro average over the 4 targets; paired bootstrap confidence
  interval of the AUC difference against P0, resampling designs. Diagnostics only: Spearman versus P0
  and top-N overlap.
- Pass rule (**my call**): macro AUC over the 4 targets is primary; the median and every per-target AUC
  are reported. The bootstrap resamples designs within each target (stratified). A candidate passes if
  (a) the paired 95% interval for (macro AUC_k − macro AUC_P0) does not lie wholly below zero, (b) the point
  estimate is not worse than −0.02, and (c) no single target is worse than P0 by more than 0.05. The
  floor panel {Boltz-2, ESMFold2} is reported beside every candidate. A candidate that passes but is
  indistinguishable from the floor is still worth shipping, because the slot exists to keep the 3-engine
  gate satisfied without AF3, not to raise AUC; the report says so in those words.
- Read the result as a hypothesis, not a proof: four targets; earlier single-pool effects in this
  project were retracted; and {Boltz-2, ESMFold2} already scored 0.7279 against 0.7231 for the full panel
  (not significant), so a pass may mean "the third engine hardly matters" as much as "the candidate is
  as good as AF3". The report must say which. Also record each candidate's training cutoff, since the
  Adaptyv targets may appear in its training set, as they may for AF3.
- Output: a report and a licence table (source URL, quote, date) per candidate.

### Part 2: the switch (built only for candidates that pass)

- Scope: Part 2 builds one engine-agnostic registry, once, and registers every engine that passed; it
  does not build per-candidate machinery. If only one engine passes, only it is registered.
- An engine registry replaces the hard-coded lists (`_ENGINE_IPTM_COLS`, schema columns, merger and
  report handling, `evaluate.sh` flags, `--primary-engine` choices). The second slot is filled by `af3` or
  by a registered engine; the gate and ranking logic are unchanged.
- Columns carry the real engine name (`openfold3_pae_iptm`, never `af3_*`).
- `metrics.csv` and the HTML report record the panel used ("Boltz-2 + OpenFold3 + ESMFold2; AF3 not used"),
  and say plainly that scores from different panels are not on one scale.
- Installer: opt-in, off by default, one engine per option value (exact flag name left to the builder;
  working name `--second-engine <name>`). It installs the engine's env, prints the weights licence and
  where it came from before downloading, records that text and date in the install state, and does not
  require AF3 weights. `evaluate.sh` auto-detects the installed second engine as it detects AF3 now.
- AF3 behaviour is unchanged when the option is not used.
- The switch is explicit and exclusive (**my call**): exactly one second-engine slot, default `af3`;
  a four-engine panel is not allowed, so `consensus_iptm_mean` and `--min-engines` keep their meaning.
  If both AF3 and a replacement are installed, the named slot wins and the other is ignored with a notice.

## Decided by the owner

- Opt-in, not a replacement of AF3 by default.
- Similar ROC AUC of our consensus (`consensus_iptm_mean`) on the Adaptyv benchmark is the success
  measure, compared between the current three-engine panel and the panel with the replacement.
- Candidates: OpenFold3 first, then Protenix, Chai-1, RF3, and IntelliFold-2 after its licence line is checked.
- Boltz-2 and ESMFold2 stay; their terms are acceptable.
- Compute may be borrowed from the aarch64 host or the cluster if needed.

## My calls (flag if wrong)

- Benchmark before any pipeline refactor; the refactor is built only for engines that pass.
- The pass rule above, and bootstrap intervals over designs.
- Pin Protenix to v1.x; never v2.
- Working option name `--second-engine`.
- Reporting the median across the 4 targets as well as the macro average (my reading of a short remark about "the median").

## Order of work and hosts (my calls)

0. Reproduce P0's per-target and macro AUC from the merged CSV and labels. If it does not match the
   figures already on record, stop and find out why.
1. Verify the IntelliFold-2 licence line (a research step in this plan; no run before it is settled).
2. Candidates in order: OpenFold3, Protenix v1.x, Chai-1, RF3, then IntelliFold-2 if cleared. The
   plan covers all of them; the order only decides which result arrives first.
3. Hosts: the x86_64 24 GB boxes for engines that fit; the cluster's 40 to 80 GB cards where one does not
   (OpenFold3's documented floor is 32 GB). On the aarch64 unified-memory host, run only under `tools/gpurun --cap`,
   never uncapped.
4. Part 2 is a gated phase of the same plan: specified at the level of this document now, broken into
   tasks only once Part 1 reports.

## Left to the builder

File layout, how each model is invoked (CLI versus Python), PAE extraction details per engine,
test fixtures, and the report layout.

## Open risks

- OpenFold3's PAE may be atom-level or token-level; the kernel needs token-level, in the right order.
- Chai-1 and RF3 memory on 24 GB cards is unmeasured.
- Licence sentences for OpenFold3 weights and RF3 weights are recent and not in a licence file next to
  the weights; archive snapshots with the benchmark report.
