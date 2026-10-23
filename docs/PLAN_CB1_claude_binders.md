# Plan CB1: the Claude protein-binder-design dataset as a second wet-lab benchmark

Opened 2026-10-13. Source: `Anthropic/claude-protein-binder-design` on Hugging Face (data release, tables and docs tier; the structure-and-PAE tier of 74.5 GB is not needed).

## Why it is worth doing

| property | value | why it matters to us |
|---|---|---|
| Designs with a usable label | 1,320 of 1,440, 354 binders | second labelled pool, independent of the Adaptyv/ProteinBase set (0 exact sequences shared with AK1) |
| Targets | 15 with labels, 4 shared with AK1 (EGFR, IL-7Ra, Nipah-G, PD-L1) | same-target replication plus 11 new targets |
| Generators | PXDesign, RFdiffusion3, Genie3, BoltzGen, BindCraft, RFdiffusion, Proteina-Complexa, others | mostly tools we run, so it tests our own use case |
| Labels | two vendors, called separately and reconciled (`binder_final`) | lets us score each vendor, and expression-gating differs from AK1 |
| Published filters | ipSAE from 10 predictors per design | direct comparison with `consensus_iptm_mean` with no extra compute |

Caveats from the release's own notes: assay formats differ (Adaptyv immobilises the design, Twist captures it as a bivalent Fc fusion, so apparent affinity can include avidity); the two vendors disagree on 136 designs; Adaptyv took part in the campaign; mature GDF-8 (120) has no usable labels. Treat a result on this pool as a hypothesis until it replicates on a second target subset.

## Phase 1: 900 monomer designs (running since 2026-10-13)

Ten targets with one target chain: TREM2, IL-7Ra, PD-L1, RBX1, BHRF1, TrkA, Nipah-G, EGFR, BBF-14, MBP (263 binders; MBP has none and BBF-14 has three, so about eight targets carry the statistics). Run through the unchanged Evaluator at the `v2.0.0` tag: 30 chunks of 30 sorted by length, six Clara H200 workers, target MSAs pre-warmed once and shipped, chunk claiming by atomic mkdir. Expected wall time a few hours.

Pre-registered analysis (written before any result is read):
1. Per target and macro AUC of each engine and of `consensus_iptm_mean` against `binder_final`; then against each vendor's own call.
2. The AK1 contrasts, as a replication test: mean3 minus best single engine, mean3 minus AF3, mean3 minus ESMFold2, bootstrap over designs within target. AK1 found the mean never worst, not better than the best single engine.
3. Our three-engine mean against the ten published ipSAE columns, on identical designs.
4. Stratify by generator and by binder length; report partial AUC after removing length.
5. Denominator stated beside every number; unexpressed designs reported both ways.

Decision rule: if the mean again fails to beat the best single engine, say so; do not search for a better metric on this pool (Part U found that makes it worse).

## Phase 2: the 330 oligomer-target designs (needs one Evaluator feature)

TNF-alpha (trimer, 150), VEGF-A (dimer, 90), 15-PGDH (dimer, 30), latent GDF-8 (dimer, 60). The release folds these as one binder against N target copies. The Evaluator takes a single target chain, so this needs a `--target-copies N` option in all three refold scripts, covering chain naming, the PAE and chain-pair iPTM handling, and the extractor. Folding them as one copy would give a different, wrong interface for the biology, so it is not offered as a shortcut. Cost: a small feature plus tests, then about a third of Phase 1's compute. Gate: only worth building if Phase 1 shows the ranking carries signal on this pool.

## Phase 3: Cas9 and mature GDF-8 (probably never)

Cas9 (90 designs) is folded against a ribonucleoprotein including 98-nt sgRNA. Boltz-2 and AF3 take nucleic chains; ESMFold2 cannot, so the cross-engine gate would have to drop to two engines (`--min-engines 2`), and the release itself reports ipSAE exactly zero for 44 to 83 percent of Cas9 designs. Low expected value. Mature GDF-8 has no labels. Neither is scheduled.

## Order of work

1. Phase 1 refold and analysis (now).
2. Archive raw output and report to muni-disk, same layout as AK1.
3. Decide Phase 2 from the Phase 1 result.
4. Record the result and its caveats in the 2.0 plan next to the AK1 findings.

## Result (Phase 1, 2026-10-20)

Macro AUC over the ten monomer targets (263 binders): `consensus_iptm_mean` 0.671, Boltz-2 0.616, AF3 0.617, ESMFold2 0.687, binder length 0.428. mean3 minus best single engine -0.015 [-0.05, +0.02], so the AK1 pattern replicates. Ranking is strong on PD-L1 (0.90) and TREM2 (0.92), at chance on BBF-14, BHRF1 and Nipah-G. Per the decision rule, no metric search was run. Phase 2 (`--target-copies`) is therefore justified only as a replication of this modest signal, not as a route to a better ranking. Full write-up: `docs/REPORT_2026-10-23_CB1_GroScore_PPBind.md`.
