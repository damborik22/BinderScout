# BinderScout Evaluator — Pipeline Reference

## Repo Structure

The Evaluator is bundled inside the BinderScout monorepo:

```
BinderScout/
├── Evaluator/                  # This directory
│   ├── binder_comparison/      # Core Python package
│   ├── scripts/                # Standalone refold scripts
│   ├── envs/                   # Conda env specs
│   ├── evaluate.sh             # Full pipeline orchestrator
│   └── install.sh              # Environment installer
├── evaluator/
│   └── evaluator.py            # Lightweight CLI parser (Mosaic venv)
├── Mosaic/.venv/               # uv venv with JAX + Boltz-2
└── ...
```

## Conda Environments

| Env | Used for | Status |
|-----|----------|--------|
| `binder-eval` | Sequence extraction + reporting | Created by `Evaluator/install.sh` |
| `binder-eval-af3` | AF3 v3.0.2 refolding | `binderscout install --tool af3` (gated weights; runs on 24 GB GPUs) |
| `binder-eval-esmfold2` | ESMFold2 refolding | `binderscout install --tool esmfold2` (in `--tool all`) |
| Mosaic `.venv` | Boltz-2 refolding | Created by `binderscout install --tool mosaic` |

## Quick CLI Reference

```bash
# Step 1: Extract sequences (any tool combination)
conda run -n binder-eval binder-compare extract \
    --bindcraft DIR --bindcraft2 DIR --boltzgen DIR --mosaic DIR --pxdesign DIR -o seqs.fasta

# Step 2: Boltz-2 refolding (uses Mosaic uv venv)
Mosaic/.venv/bin/binder-compare refold-boltz2 \
    --sequences seqs.fasta --target-seq SEQ -o boltz2.csv

# Step 3: AF3 refolding (runs on 24 GB GPUs; ~4.4 GB peak at ~260 tokens)
conda run -n binder-eval-af3 binder-compare refold-af3 \
    --sequences seqs.fasta --target-seq SEQ -o af3.csv

# Step 4: ESMFold2 refolding (lightweight, no gated weights)
conda run -n binder-eval-esmfold2 binder-compare refold-esmfold2 \
    --sequences seqs.fasta --target-seq SEQ -o esmfold2.csv

# Step 4: Generate report
conda run -n binder-eval binder-compare report \
    --boltz2-results boltz2.csv --af3-results af3.csv --esmfold2-results esmfold2.csv \
    --sequences seqs.fasta -o ./report

# Full orchestrator
bash Evaluator/evaluate.sh \
    --sequences seqs.fasta --target-seq SEQ --target-pdb PDB -o ./results
```

## Critical Facts

- **PAE ordering**: Boltz-2 outputs `[binder|target]`; AF3 and ESMFold2 output `[target|binder]` (token order, target first) and the evaluator transposes them. Column prefixes (`boltz_pae_*`, `af3_*`, `esmfold2_*`) distinguish them.
- **pLDDT scale**: Boltz-2 and ESMFold2 are native [0,1]; AF3 is [0,100] and is divided by 100 on ingest so every engine's columns are directly comparable.
- **ipsae_min direction**: **HIGHER IS BETTER** — TM-score-like metric (DunbrackLab 2025 formula).
- **Append-mode CSVs**: the refold scripts append. If rerun after a partial failure, check for duplicate `run_id` entries. Use `--resume` to skip completed sequences.
- **Mosaic `is_top` filtering**: Default extracts only `is_top=1` rows (~40 refolded designs instead of all ~800). Use `--all-mosaic-designs` to override.
- **Mosaic CSV column mismatch**: `designs.csv` can mix two column formats (old 11-col / new 13-col) when multiple workers run. Parser may misalign columns for some workers.

## Metrics

| Metric | Direction | Description |
|--------|-----------|-------------|
| `ipsae_min` | higher = better | Primary ranking metric. min(bt_ipSAE, tb_ipSAE) |
| `iptm` | higher = better | Interface pTM (gameable by the engine that designed the sequence — never rank on one engine) |
| `pae_bt_mean` | lower = better | Mean binder-to-target PAE (angstroms) |
| `pae_tb_mean` | lower = better | Mean target-to-binder PAE |
| `plddt_binder_mean` | higher = better | Mean binder pLDDT [0,1] |
| `agreement_count` | higher = better | Engines agreeing ipsae_min > 0.61 |

### BindCraft 2 native metrics

Each design carries the numbers its own tool produced, under a `bindcraft2_`
prefix so they sit beside the refold columns without being mistaken for them.
They are worth reading separately because none of their scales matches the rest
of the table.

| Metric | Direction | Description |
|--------|-----------|-------------|
| `bindcraft2_ipdae` | higher = better | BindCraft 2's own ranking metric. Its `rank` column is a plain descending sort on this and nothing else — not i_pTM, not a composite. Bounded [0,1]; it reads like an error term but behaves as a TM-score analogue |
| `bindcraft2_iptm` | higher = better | Design-time i_pTM, already on [0,1]. Biased by the engine that designed the sequence exactly as BindCraft 1's is, so it never enters `consensus_iptm_mean` |
| `bindcraft2_plddt` | higher = better | Binder pLDDT, already on [0,1] |
| `bindcraft2_ipae` | lower = better | Interface PAE divided by 31 — **not in angstroms**, so it is not comparable with `pae_*` above |

Do not rescale `bindcraft2_plddt` or `bindcraft2_iptm` on reflex: unlike AF3's
[0,100] pLDDT, which the ingest divides by 100, they arrive on [0,1] and
dividing them again would quietly flatten the pool.

## Known Issues

- **BoltzGen pass rate is low**: In CALCA target testing, only 1/50 designs passed `ipsae_min > 0.61`. Sequences designed for Boltz-2 often don't cross-validate well.
- **Cross-engine disagreement**: for short binders (~60 aa) the engines often disagree on interface quality. That is signal, not noise — `consensus_iptm_spread` records it, and the two-stage mean rank demotes designs only one engine likes.
- **Binder length is a main driver**: Longer binders tend to score lower on `ipsae_min` (r ~ -0.78).
