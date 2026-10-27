# RFD4-Proteina pool on PD-L1 and TrkA, refolded by the unchanged Evaluator (2026-10-27)

In silico only. No binding was measured and no hit rate is claimed.

**Setup.** RFD4-Proteina (RosettaCommons/RFD4-Proteina at aaccdd2, weights nvidia/RFD4-Proteina) generated 360 PD-L1 and 330 TrkA binders of 60 to 100 aa, all unique. Refold used Evaluator v2.0.1 (Boltz-2, AF3, ESMFold2), the same recipe and byte-identical targets as CB1. Jobs 247631 and 247632 ran on l40s-06 in 8.8 h and 8.5 h. Every design has three engine scores and passes the three-engine gate.

| | PD-L1 (360) | TrkA (330) |
|---|---|---|
| median `consensus_iptm_mean` | 0.598 | 0.209 |
| designs at or above 0.8 | 81 (22.5%) | 8 (2.4%) |
| at or above 0.7 on all three engines | 63 | 10 |
| CB1 binders / non-binders, median | 0.912 / 0.858 | 0.891 / 0.857 |
| RFD4 above CB1 non-binder median | 9.7% | 1.8% |
| engine agreement (Spearman) | 0.60 to 0.76 | 0.27 to 0.45 |
| Spearman, length vs consensus | -0.19 | -0.36 |
| low-complexity flagged, median vs rest | 0.557 vs 0.604 (n=16) | 0.171 vs 0.212 (n=30) |

Top designs: PD-L1 `rfd4_pdl1_0153` 0.912, `0196` 0.907, `0327` 0.902; TrkA `rfd4_trka_0107` 0.924, `0294` 0.923, `0126` 0.920. Two of the PD-L1 top 10 are low-complexity flagged.

**Reading.** The unfiltered pool sits mostly below CB1, which was already filtered by its authors, so the comparison is not like for like. TrkA is much weaker and the engines agree less; the target is the NGF-bound 1WWA conformation with NGF removed. The paper's TrkA binder claims are experimental and are not tested here. High scores for the best designs show the engines like them, not that they bind.

**Not done.** Length-matched comparison, comparison with Adaptyv PD-L1, clustering at 40% identity (the distinct counts of 63 and 10 use a 4-mer overlap proxy), a hotspot-conditioned arm.

**Input fixes the generator needs.** Contigs resolve on mmCIF label_seq_id, not author numbering: PD-L1 input was edited so label equals author numbering; TrkA contig is A5-105. Full command record: `INSTALL_LOG.md`, `RUN_LOG.md`, `install_replay.sh`, `replay_pool.sh` (archived under MUNI `EVALUATOR/Benchmark_RFD4_Proteina/`). Weights licence not verified.
