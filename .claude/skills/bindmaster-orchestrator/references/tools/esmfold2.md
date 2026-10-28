# ESMFold2

**Engine:** Biohub's ESMFold2 — an ESM-family complex folder that emits interface ipTM
directly. Two checkpoints: `biohub/ESMFold2` (`--model full`, the default) and
`biohub/ESMFold2-Fast` (`--model fast`).

**Weights pinning is only half-done — know this before trusting a cross-node comparison.**
`_MODEL_REVISIONS` (`Evaluator/scripts/refold_esmfold2.py:55`) pins `biohub/ESMFold2` to
revision `8fc3ff47…`, but maps `biohub/ESMFold2-Fast` to `os.environ.get("ESMFOLD2_REVISION")
or None`, and `_load_model` passes no `revision` when that is None. So **`--model fast`
resolves whatever upstream tagged `main` at download time** — exactly the silent divergence
the pin's own comment says it prevents. `$ESMFOLD2_REVISION` also overrides the pin on either
checkpoint. Since `../learnings.md` recommends *Fast* for the cheap pre-filter, that is the
path most likely to diverge between nodes.
**Role:** refolding — BindMaster's **default engine**, and the source of the
`chain_iptm_interface` gate that `autosize` uses.
**Status:** stable; installed by `--tool all`. No gated weights.
**Environment:** `binder-eval-esmfold2` conda env, Python 3.12. x86_64 + aarch64.

## Principle

ESMFold2 folds the *complex* and reports interface confidence directly, rather than
requiring a separate interface metric to be derived from a PAE matrix. That makes it the
cheap engine in the line-up: no gated weights, no MSA dependency of its own, and it runs
on any idle 24 GB card. It is what makes a three-engine consensus affordable at all — the
default `--min-engines 3` gate would otherwise mean every design waits on AF3's gated
weights.

Architecturally it is an ESM-lineage model, so it is independent of every design tool in
the pool: no BindMaster design tool folds with ESMFold2 internally. That is a stronger
independence claim than AF3 can make, since AF3 is correlated with PXDesign through
Protenix.

## Strengths

- **The only engine clean against all seven design tools.** See the bias matrix in
  `README.md`. AF3 is clean against six; Boltz-2 against four.
- **Cheap enough to use as a pre-filter.** Fold the complex, gate on `iptm` up front, and
  promote only the top slice to the expensive Boltz-2 + AF3 + ESMFold2 merge. This is the
  decoupling pattern in `../learnings.md` — it keeps refold load flat as the generated
  pool grows.
- **No gated weights.** Nothing to request, so a fresh install can reach a 2-engine
  consensus immediately and a 3-engine one as soon as AF3's weights land.
- **Feeds `autosize`.** `chain_iptm_interface` is the gate deciding whether enough
  independent backbones have cleared, and therefore how big the next batch should be.

## Weaknesses

- **Not a reference-grade predictor.** It is the cheapest of the three, and on the Part T
  advantage map no engine dominates — do not read a high ESMFold2 iPTM as a substitute for
  the cross-engine mean.
- **Length sensitivity is not characterised for it.** The documented anti-correlation is
  Boltz-2 vs AF3 by binder length (Part T). ESMFold2's own length profile has not been
  measured, so do not assume it is flat.
- **`iptm` and `ipsae_min` are different scales.** `esmfold2_iptm` is the engine's own
  interface ipTM; `esmfold2_ipsae_min` is the evaluator's uniform 10 Å iPSAE computed from
  its PAE. They are not interchangeable.

## When this engine's signal is most important

- **Every run.** It is the default, and the engine that most often makes the difference
  between a 2-engine and a 3-engine consensus.
- **PXDesign outputs.** AF3 is correlated there (Protenix reimplements AF3), so ESMFold2
  is the clean independent read.
- **Autosize loops.** It is the gate, so its threshold *is* the loop's stopping condition.
- **Pre-filtering a large generated pool.** Gate on `iptm`, keep roughly the top 40%, then
  merge.

## Outputs the evaluator parses

`esmfold2_*` columns in `metrics.csv`. **`esmfold2_pae_iptm` is the one that reaches the
ranking** — it is this engine's entry in `_ENGINE_IPTM_COLS` (`comparison/scoring.py:689`),
which feeds `consensus_iptm` and `consensus_iptm_mean`. Do not confuse it with
`esmfold2_iptm`, which is the engine's own reported value and is not the consensus input.

The rest: `idx`, `iptm`, `ptm`, `iptm_pair`, `iptm_pair_min`, `plddt_binder_mean/min`,
`plddt_target_mean`, `pae_bt/tb/bb/overall_mean`, `pae_max`, `bt_ipsae`, `tb_ipsae`,
`ipsae_min`, `ipsae_max`, `chain_iptm_interface`, plus the `esmfold2_cif` /
`esmfold2_pdb` / `esmfold2_pae_file` paths.

## Sources

- Weights: `biohub/ESMFold2` and `biohub/ESMFold2-Fast` on HuggingFace. Only the former is
  pinned — see the pinning note at the top
- CLI: `binder-compare refold-esmfold2` — checkpoint flag is **`--model`** (`fast`|`full`,
  default `full`), plus `--num-loops` (3), `--num-sampling-steps` (50),
  `--num-diffusion-samples` (1), `--seed` (0). The spelling `--esmfold2-model` belongs to the
  `evaluate.sh` orchestrator, which forwards it as `--model`; passing it to `binder-compare`
  directly fails
- Gate definition: `comparison.scoring.add_chain_iptm_interface`, consumed by
  `cli/autosize.py`
- iPSAE formula: DunbrackLab 2025 `d0_res` variant, uniform 10 Å PAE cutoff
