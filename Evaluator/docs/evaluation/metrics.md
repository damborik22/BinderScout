# Metric catalogue

**As of 2026-10-04.** One row per column the Evaluator emits, with the field whose absence caused
the drift this file exists to prevent: **ROLE** — what the column is actually allowed to do.

`RANKS` feeds `rank` · `GATES` can exclude or demote · `WARNS` is a per-design caution for a
human · `REPORTS` is emitted for inspection only · `NATIVE` is a design tool's own metric carried
through untouched.

For why the ranking is what it is, and what it is worth, see [ranking.md](ranking.md).

## 6. Metric catalogue

**ROLE** is the field that was missing everywhere: `RANKS` feeds `rank` · `GATES` can
exclude or demote · `WARNS` is a per-design caution for a human · `REPORTS` is emitted for
inspection only · `NATIVE` is a design tool's own metric carried through untouched.

| column | what it is | dir | ROLE | validation |
|---|---|---|---|---|
| `consensus_iptm_mean` | mean of the three PAE-recomputed ipTMs | ↑ | **RANKS** (key 2) | 0.706 CALCA / 0.496 CBG / 0.723 Adaptyv |
| `passes_engine_gate` | cleared `--min-engines` | ↑ | **RANKS** (key 1) + GATES | gate inert at 100 % coverage |
| `consensus_iptm_n` | how many engines scored it (0–4) | ↑ | **RANKS** (key 3) | — |
| `agreement_denom` | how many engines actually produced an **ipSAE** for this design | ↑ | **WARNS** (the denominator of `agreement_count`) | Added 2026-10-03. Without it `agreement_count = 1` cannot distinguish *two engines doubt this* from *two engines never ran*; 99 labelled benchmark designs are capped at 2 of 3 |
| `consensus_iptm` | **max** ipTM across engines | ↑ | **RANKS** (key 4) | max-ranking loses to mean-ranking (Part U) |
| `plddt_binder_mean/min` | binder fold confidence | ↑ | **RANKS** (key 5, min) | — |
| `rank` | the single output ordering | ↓ | the result | — |
| `agreement_count` | engines over an **absolute ipSAE 0.61** — **a different quantity from the ipTM that ranks** | ↑ | **WARNS**, note-only since 2026-10-03: it prints in `wetlab_reason` and cannot withhold the recommendation | macro-AUC **0.6295** on the registered pool's all-3-engine subset (70.5 % tied at zero). Monotone then saturating — binder rate 0.378 → 0.567 → **0.778** → 0.758, so *some vs none* carries the information and **2-vs-3 carries none**. The 0.532/87.2 % quoted elsewhere is a **Cao** figure, not this pool |
| `*_pae_iptm` | per-engine ipTM recomputed from PAE | ↑ | **RANKS** (via the mean) | — |
| `*_iptm` | engine's **self-reported** ipTM | ↑ | REPORTS | scales differ sharply between engines |
| `ipsae_min` | min(bt,tb) iPSAE, DunbrackLab 2025 | ↑ | REPORTS + GATES (affinity) | **measured INVERTED** on our SPOC data |
| quality tiers (High/Medium/Low/Reject) | bands on `ipsae_min` | — | REPORTS | **measured INVERTED** — "Reject" held 6/10 CBG binders; "High" fired on none |
| `passes_affinity_gate` | `ipsae_min >= 0.61` | ↑ | GATES (`affinity` only) | **measured INVERTED** |
| `*_pae_*`, `ipae` | PAE block statistics | ↓ | REPORTS | |
| `ranking_loss` | Mosaic's design-stage loss | ↓ | NATIVE | gameable: Mosaic's own objective |
| `self_consistency_rmsd`, `passes_self_consistency` | target-aligned RMSD between refolds | ↓ / ↑ | REPORTS (shadow) | unvalidated |
| `passes_confidence_gate`, `confidence_fail_reasons` | BindCraft's filters, ported exactly | ↑ | REPORTS (shadow) | unvalidated |
| `would_exclude_*` | what each shadow gate *would* have removed | — | REPORTS | — |
| `seq_family_*` | near-duplicate sequences, k-mer Jaccard ≥ 0.20 | — | REPORTS | all observed near-dupes were same-tool |
| `struct_family_*` | shared fold, Foldseek TM ≥ 0.5, binder chain only | — | REPORTS | max pairwise sequence Jaccard 0.298 over 114 designs — folds are invisible to sequence methods |
| `generation_index`, `_source` | where a design fell in generation order | — | REPORTS | 5 of 8 tools can report; `unavailable` is first-class |
| `soluprot_*` | sequence-only solubility | ↑ | REPORTS (label only) | best available predictor of *expression*; filter mode removed |
| `tmprot_*` | predicted melting temperature | ↑ | REPORTS (label only) | advisory; must not grow a filter |
| `wetlab_recommended`, `wetlab_reason` | blockers + informational notes, concatenated | ↑ | GATES (advisory) | Blocks on the cross-engine gate, binder pLDDT < 0.50, and a FAILED RUN. **SoluProt (2026-09-28) and `agreement_count` (2026-10-03) are notes that cannot block** — both measured badly against our own Kd results |
| `epitope_match_fraction` | contact overlap with intended hotspots | ↑ | REPORTS | — |
| `native_*` | a tool's own metrics, prefixed | — | NATIVE | each gameable by its own tool |

---

---

## 7. Conventions that have caused real bugs

1. **pLDDT scale.** Boltz-2 returns [0,1]; AF3 is native [0,100] and is rescaled on ingest.
   **BindCraft 2's `bindcraft2_plddt` and `_iptm` arrive on [0,1] and must NOT be rescaled**
   — dividing again silently flattens the pool. `bindcraft2_ipae` is interface PAE **÷ 31**
   and is **not in ångströms**, so it is not comparable with `pae_*`.
2. **PAE ordering.** Boltz-2 is native `[binder|target]`. AF3 is token-order, so the target
   goes first in the input JSON and the matrix is **permuted** (an `np.block`
   rearrangement, not a transpose). A new engine must declare its ordering.
3. **Column registration.** See §5 — membership of `_ENGINE_IPTM_COLS` is the gate's actual
   mechanism.
4. **Gameability map.** Never read a tool's own engine as an independent opinion about that
   tool's designs: Mosaic ↔ Boltz-2 (it *is* Boltz-2 gradient hallucination), BindCraft and
   BindCraft 2 ↔ AF2 i_pTM, PXDesign ↔ its internal Protenix, Protein-Hunter ↔ Boltz-2 /
   Chai-1. Note §2's finding that this bias is **not** observed at refold time.
5. **AF3 bucket floor.** `AF3_MIN_BUCKET = 256`, AF3's own smallest compilable shape. Below
   it, tokamax's kernels request 110,592 bytes of shared memory against sm_86's 101,376 and
   the refold aborts. Measured both ways on an RTX 3090.
6. **The target MSA is fetched once per target** and shared by all three engines via a
   SHA-256-keyed disk cache. This is what defeats the ColabFold rate limit across sessions.

---

---

## Facts that live in only one place

Each of these was, at the time of writing, recorded in exactly one file. They are collected here
because each one changes how a number is read:

- **AF3 weights licensing** (`Evaluator/README.md`) — the ToU bars commercial use of
  outputs and release of raw scores/structures for training, which conflicts with
  publishing our scores. The only record of *why* the engine line-up is what it is on legal
  grounds.
- **The cross-method bias matrix** — 8 design tools × 3 refold engines, clean/correlated per
  cell (`skills/binderscout-orchestrator/references/tools/README.md`). The evaluator skill
  names that file as its authority, so it cannot simply be deleted.
- **The measured GPU-memory table** (`README.md`) — AF3 2.3–5.2 GB flat; **ESMFold2's
  14.2 GB floor at 150 tokens, so a 12 GB card cannot run it at any size** (`require_device_memory`
  now refuses before the weight download); Boltz-2 139.6 GB at 900 tokens. ESMFold2 and AF3 still
  *write* a blank row on a per-design CUDA OOM, but a blank row no longer exits 0 — see
  `tests/test_a_blank_refold_row_is_not_a_score.py`.
- **`chain_iptm_interface` macro-AUC 0.69** on the *full* Adaptyv batch, with the explicit
  instruction not to quote the inflated 0.745 subset figure.
- **BindCraft 2 native scales** (`pipeline_reference.md`) — `bindcraft2_plddt`/`_iptm` arrive on [0,1] and must NOT be rescaled; `bindcraft2_ipae` is interface PAE ÷ 31 and is **not** in ångströms.
- **The iPSAE directional formula in prose** and the 10 Å uniform-cutoff rationale
  (`references/evaluation.md`), plus wall-time budgets (~30 GPU-h per 500-design 3-engine
  pool).
- **The Stage-1 inertness counterexample** (`CLAUDE.md`) — A=(.5,.5,.5) vs B=(.9,.1,.1)
  shows elementwise `mean ≤ max` does not imply rank preservation.

---
