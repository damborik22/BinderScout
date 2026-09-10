# BindMaster Evaluator

**Sequences in → independent refolding → ranked interface metrics out.**

Takes candidate binder sequences from any generative tool, refolds each binder+target
complex with two orthogonal structure predictors (Boltz-2 and AlphaFold2), and produces
a ranked report of interface quality metrics. It does not design sequences.

---

## Why independent refolding?

Every generative tool scores its own outputs with its own model. Those native scores are
biased toward the tool's training distribution and cannot be compared across tools. This
pipeline removes that bias by evaluating all sequences on neutral ground:

- **Boltz-2** (Markov Research) — diffusion-based predictor; TM-score interface metric (ipSAE)
- **AlphaFold2 multimer** (ColabDesign) — established baseline; PAE-based interface metric

The composite score rewards sequences that **both models independently** agree are strong
binders. A sequence that scores well on only one model is ranked lower.

**Primary metric: `ipsae_min`** — min(bt_ipSAE, tb_ipSAE), Dunbrack 2025 formula.
Range 0-1, higher is better. Pass threshold: > 0.61.

---

## Why Boltz-2 and not AlphaFold3?

The [Overath et al. 2025 meta-analysis](https://www.biorxiv.org/content/10.1101/2025.08.14.670059v2.abstract)
identifies AF3 as the recommended filter for ipSAE-based binder screening, with a slightly
higher rank correlation than Boltz-2. We chose Boltz-2 for two reasons.

**Licensing.** The AF3 weights terms of use prohibit:
- Any commercial use of model outputs, or use on behalf of commercial entities
- Release of raw scores and structures for others to train on (even under the open-source carve-out)

Since we intend to release raw scores and structures publicly, and do not want to exclude
commercial participants or take on legal risk from the carve-out, AF3 is not compatible
with our goals.

**Performance.** The difference in discrimination power is small. ROC and precision-recall
curves computed on the meta-analysis data show that ipSAE_min from Boltz-1 and AF3 perform
similarly for distinguishing binders from non-binders. Boltz-2 is a strict Pareto improvement
over Boltz-1 (better across all benchmarks), and the Boltz-2 authors confirmed that the
choice between models is unlikely to make a large practical difference.

---

## Installation

The Evaluator is bundled inside the BindMaster repository. No separate clone needed.

### 1. Install Mosaic (Boltz-2 environment)

The Boltz-2 refolding step uses the **Mosaic** uv virtual environment:

```bash
cd ~/BindMaster
bindmaster install --tool mosaic
```

### 2. Install the evaluator environments

```bash
cd ~/BindMaster/Evaluator
bash install.sh
```

`install.sh` auto-detects the Mosaic venv, installs `binder-compare` into it,
and creates two additional conda environments:

| Environment | Used for | Python |
|-------------|----------|--------|
| Mosaic venv (existing) | `refold-boltz2` | 3.12 |
| `binder-eval` | `extract`, `report` | 3.10 |
| `binder-eval-af3` | `refold-af3` | 3.10 |
| `binder-eval-esmfold2` | `refold-esmfold2` | 3.10 |

> The refold engines are **Boltz-2 + AF3 + ESMFold2**. AF2 refolding was removed in
> Part I and Protenix refolding on 2026-07-26 — there is no `refold-af2` or
> `refold-protenix` subcommand and no `binder-eval-af2` env. AF3 needs gated weights
> (but runs on a 24 GB GPU — ~4.4 GB peak for a 258-token complex); ESMFold2 needs
> neither. `evaluate.sh` auto-detects
> whichever engine envs exist and skips the rest.

---

## Usage

You need two input files:

| File | Description |
|------|-------------|
| `sequences.fasta` | Binder sequences to evaluate |
| `target.pdb` | Target protein structure |

### Run (single command)

```bash
bash Evaluator/evaluate.sh \
    --sequences  sequences.fasta \
    --target-seq "MGFQKFSPF..." \
    --target-pdb target.pdb \
    --output     ./results
```

This runs all steps in the correct environments automatically and writes:
- `results/report/report.html` — interactive ranked report
- `results/report/metrics.csv` — all metrics, ranked
- `results/report/summary.json` — per-tool aggregate statistics

### Via the BindMaster CLI

```bash
bindmaster evaluate runs/<name>
bindmaster evaluate runs/<name> --refold 5 --target runs/<name>/target/target.pdb
```

### Resume a partial run

```bash
bash Evaluator/evaluate.sh \
    --sequences  sequences.fasta \
    --target-seq "MGFQKFSPF..." \
    --target-pdb target.pdb \
    --output     ./results \
    --skip-boltz2        # reuse existing results/boltz2_results.csv
```

### Prepare your sequences FASTA

If your sequences come from a supported design tool, `extract` builds the FASTA
from the tool's output directory:

```bash
conda run -n binder-eval binder-compare extract \
    --bindcraft /path/to/bindcraft/output \
    --boltzgen  /path/to/boltzgen/output \
    --mosaic    /path/to/mosaic/output \
    --pxdesign  /path/to/pxdesign/output \
    -o sequences.fasta
```

Otherwise, any standard FASTA works — `>id` headers are used as binder IDs.

---

## Pipeline Steps

### `extract`
Reads native output directories for each supported tool, extracts sequences and metadata,
deduplicates, and writes a combined FASTA with `binder_id` and `source` tags.

Supported inputs: `--bindcraft`, `--boltzgen`, `--mosaic`, `--pxdesign`, `--proteina-complexa`,
`--protein-hunter`, `--rfd3` — all seven, on both `extract` and `run`.

A requested directory that yields 0 sequences is an error (`--allow-empty` to override),
so a mistyped path cannot silently shrink the pool before hours of GPU refolding.

### `refold-boltz2`
Refolds each binder+target pair with Boltz-2. Calls ColabFold for MSA, then runs Boltz-2
structure prediction. Computes ipSAE, ipTM, PAE statistics, and pLDDT per sequence.

Output: `boltz2_results.csv` (appends on re-run — check for duplicates after partial runs).

### `refold-af3`
Refolds with AlphaFold 3 v3.0.2 in the `binder-eval-af3` env. Columns carry the `af3_`
prefix; pLDDT is rescaled 0–100 → 0–1 on ingest and the PAE matrix is transposed from
token order (`[target|binder]`) to `[binder|target]` to match Boltz-2. Runs on 24 GB
consumer GPUs: a 258-token binder:target complex peaks at ~4.4 GB (RTX 3090, 2026-08-14).

Output: `af3_results.csv` (append mode — check for duplicates after partial runs).

### `refold-esmfold2`
Refolds with ESMFold2 (biohub) in the `binder-eval-esmfold2` env. Columns carry the
`esmfold2_` prefix and include `iptm_pair` / `iptm_pair_min`, which feed
`chain_iptm_interface` — the gate the `autosize` loop counts passers against. No gated
weights.

Output: `esmfold2_results.csv`.

### `report`
Merges the per-engine result CSVs on the `sequence` column, computes ipSAE and the
PAE-recomputed per-engine iPTMs, applies the two-stage cross-engine ranking and the
quality-tier thresholds, and renders a self-contained interactive HTML report (the NGL
3D viewer is inlined, so it works offline).

Output: `report.html`, `metrics.csv`, `metrics_zscore.csv`, `summary.json`

---

## Metrics Reference

| Metric | Direction | Description |
|--------|-----------|-------------|
| `ipsae_min` | higher = better | min(bt_ipSAE, tb_ipSAE) — primary ranking metric |
| `iptm` | higher = better | interface predicted TM-score (Boltz-2) |
| `ipae` | lower = better | mean interface PAE in angstroms |
| `pae_bt` | lower = better | binder-to-target PAE |
| `pae_tb` | lower = better | target-to-binder PAE |
| `pae_bb` | lower = better | intra-binder PAE |
| `plddt_binder_mean` | higher = better | mean binder pLDDT [0-1] |
| `af3_ipsae_min` | higher = better | ipSAE_min from AF3 PAE matrices |
| `esmfold2_ipsae_min` | higher = better | ipSAE_min from ESMFold2 PAE matrices |
| `consensus_iptm` | higher = better | max of the per-engine PAE-recomputed iPTMs (Stage-1 screen) |
| `consensus_iptm_mean` | higher = better | mean across engines (Stage-2 rank) |
| `consensus_iptm_n` | higher = better | how many engines contributed (Stage-0 gate, default 3) |
| `agreement_count` | higher = better | number of engines agreeing ipsae_min > 0.61 |

### Quality tiers (based on `ipsae_min`)

| Tier | Threshold |
|------|-----------|
| High | > 0.80 |
| Medium | 0.61 - 0.80 |
| Low | 0.40 - 0.61 |
| Reject | <= 0.40 |

---

## Directory Structure

```
Evaluator/
├── evaluate.sh             # Full pipeline orchestrator (single command entry point)
├── install.sh              # Create all conda environments
├── run.sh                  # Legacy runner script
├── pyproject.toml          # Package: "binder-comparison" v0.1.0
├── binder_comparison/      # Core package: CLI, extractors, refolding, report
├── scripts/                # Standalone refold scripts (refold_boltz2.py, refold_af3.py, refold_esmfold2.py)
├── envs/                   # Conda environment specs (binder-eval.yml, binder-eval-af3.yml, binder-eval-esmfold2.yml)
├── docs/                   # Pipeline reference, analysis notes
└── example/                # Example outputs from CALCA run
```

---

## Troubleshooting

### 1. An engine is silently skipped

`evaluate.sh` prints a `[note] conda env '<env>' not found — … will be skipped` line for
each absent engine and adjusts the step count. That is by design, but it changes the
ranking: with fewer than `--min-engines` (default 3) engines nothing passes the Stage-1
screen, and the run warns saying so.

```bash
conda env list | grep binder-eval        # which engine envs exist
bindmaster install --tool esmfold2       # add the lightweight third engine
```

### 2. CUDA version mismatch

```bash
nvidia-smi          # check driver CUDA version
```

If the driver version is too old, update your NVIDIA driver.

### 3. `refold-af2` / `refold-protenix`: `invalid choice`

Both were removed — AF2 refolding in Part I, Protenix on 2026-07-26. Use `refold-af3`
and `refold-esmfold2`. There is no `binder-eval-af2` env for any installer to create.

### 4. Nothing passes the Stage-1 screen

The cross-engine gate found fewer than `--min-engines` engines per design. Either run the
missing engine, or lower the gate knowingly:

```bash
binder-compare report ... --min-engines 2   # floor is 2; below that it is not a consensus
```

### 5. PAE file not found during report generation

The refolding step was interrupted. Re-run with `--resume`:

```bash
bash Evaluator/evaluate.sh \
    --sequences sequences.fasta --target-pdb target.pdb \
    --output ./results --resume
```

### 6. Mosaic venv path not found

```bash
bash Evaluator/install.sh     # auto-detects the venv
```

### 7. Duplicate CSV rows after a partial run

Use `--resume` on re-run to skip already-completed sequences.
