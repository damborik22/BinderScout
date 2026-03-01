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
Range 0–1, higher is better. Pass threshold: > 0.61.

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
choice between models is unlikely to make a large practical difference — because all of these
models are trained to detect different poses of the same complex, not to compare different
complexes, which makes the task inherently hard regardless of the predictor.

---

## Installation

### 1. Install Mosaic (Boltz-2 environment)

The Boltz-2 refolding step uses the **Mosaic** environment from the
[BindMaster-installator](https://github.com/damborik22/BindMaster-installator).
Install it first if you haven't already:

```bash
cd /path/to/BindMaster-installator
bash install.sh --tool mosaic
```

This creates a self-contained uv virtual environment inside the Mosaic directory
with JAX, Boltz-2, and all required dependencies.

### 2. Install the evaluator

```bash
git clone https://github.com/damborik22/BindMaster-evaluator.git
cd BindMaster-evaluator
bash install.sh
```

`install.sh` auto-detects the Mosaic venv, installs `binder-compare` into it,
and creates two additional conda environments:

| Environment | Used for | Python |
|-------------|----------|--------|
| Mosaic venv (existing) | `refold-boltz2` | 3.12 |
| `binder-eval` | `parse-seqs`, `report` | 3.10 |
| `binder-eval-af2` | `refold-af2` | 3.10 |

> **AF2 weights** (~4 GB) must be downloaded separately and the path set in
> `AF2_DATA_DIR`. See `docs/pipeline_reference.md`.

---

## Usage

You need two input files:

| File | Description |
|------|-------------|
| `sequences.fasta` | Binder sequences to evaluate |
| `target.pdb` | Target protein structure |

### Run (single command)

```bash
bash evaluate.sh \
    --sequences  sequences.fasta \
    --target-seq "MGFQKFSPF..." \
    --target-pdb target.pdb \
    --output     ./results
```

This runs all three steps in the correct environments automatically and writes:
- `results/report/report.html` — interactive ranked report
- `results/report/metrics.csv` — all metrics, ranked
- `results/report/summary.json` — per-tool aggregate statistics

### Resume a partial run

If one step completed and you want to skip it on re-run:

```bash
bash evaluate.sh \
    --sequences  sequences.fasta \
    --target-seq "MGFQKFSPF..." \
    --target-pdb target.pdb \
    --output     ./results \
    --skip-boltz2        # reuse existing results/boltz2_results.csv
```

### Prepare your sequences FASTA

If your sequences come directly from a supported design tool, `extract` builds the FASTA
from the tool's output directory and tags each sequence with its source:

```bash
conda run -n binder-eval binder-compare extract \
    --bindcraft /path/to/bindcraft/output \
    --boltzgen  /path/to/boltzgen/output \
    --mosaic    /path/to/mosaic/output \
    -o sequences.fasta
```

Otherwise, any standard FASTA works — `>id` headers are used as binder IDs.

---

## Pipeline Steps

### `extract`
Reads native output directories for each supported tool, extracts sequences and metadata,
deduplicates, and writes a combined FASTA with `binder_id` and `source` tags.

Supported inputs: `--bindcraft`, `--boltzgen`, `--mosaic`, `--pxdesign`

### `refold-boltz2`
Refolds each binder+target pair with Boltz-2. Calls ColabFold for MSA, then runs Boltz-2
structure prediction. Computes ipSAE, ipTM, PAE statistics, and pLDDT per sequence.

Output: `boltz2_results.csv` (appends on re-run — check for duplicates after partial runs).

### `refold-af2`
Refolds with AlphaFold2 multimer via ColabDesign. Requires the target as a `.pdb` file.
All output columns carry the `af2_` prefix. PAE arrays are saved for ipSAE computation.

Output: `af2_results.csv` (append mode — check for duplicates after partial runs).

### `report`
Merges both result CSVs, computes composite scores and z-scores, applies quality-tier
thresholds, and renders a self-contained interactive HTML report.

Output: `report.html`, `metrics.csv`, `metrics_zscore.csv`, `summary.json`

---

## Metrics Reference

| Metric | Direction | Description |
|--------|-----------|-------------|
| `ipsae_min` | ↑ higher better | min(bt_ipSAE, tb_ipSAE) — primary ranking metric |
| `iptm` | ↑ higher better | interface predicted TM-score (Boltz-2) |
| `ipae` | ↓ lower better | mean interface PAE in Å |
| `pae_bt` | ↓ lower better | binder→target PAE in Å |
| `pae_tb` | ↓ lower better | target→binder PAE in Å |
| `pae_bb` | ↓ lower better | intra-binder PAE in Å |
| `plddt_binder_mean` | ↑ higher better | mean binder pLDDT [0–1] |
| `af2_ipsae_min` | ↑ higher better | ipSAE_min computed from AF2 PAE matrices |
| `composite_score` | ↑ higher better | weighted z-score sum across all metrics |

### Quality tiers (based on `ipsae_min`)
| Tier | Threshold |
|------|-----------|
| High | > 0.70 |
| Medium | 0.61 – 0.70 |
| Low | 0.40 – 0.61 |
| Reject | ≤ 0.40 |

### ipSAE
Computed via Dunbrack 2025. Analogous to a TM-score for the interface — values near 1
indicate a well-defined, confident binding geometry. `ipsae_min` uses the minimum of the
two directional scores (binder→target and target→binder) to penalise asymmetric predictions.

---

## Example (CALCA target, 216 sequences)

Target: CALCA/P01258 (calcitonin), 141 aa sequence.

| Tool | n | Pass rate (ipsae_min > 0.61) | Mean ipsae_min |
|------|---|------------------------------|----------------|
| PXDesign | 100 | **34%** | 0.544 |
| BindCraft | 6 | 33% | 0.585 |
| Mosaic | 60 | 27% | 0.501 |
| BoltzGen | 50 | 2% | 0.366 |

Example output files in `example/`:
- `metrics.csv` — top 20 designs, all metrics
- `summary.json` — per-tool aggregate statistics
- `report.html` — full interactive ranked report

BoltzGen sequences scored high under Boltz-2 natively but failed to cross-validate under
AF2 — consistent with sequences fitted to Boltz-2's scoring landscape rather than true
binding geometry.

---

## Supported Input Tools

| Tool | Flag | Reads from |
|------|------|------------|
| BindCraft | `--bindcraft` | AF2 + MPNN design output directory |
| BoltzGen | `--boltzgen` | Boltz-2 diffusion design JSONs |
| Mosaic | `--mosaic` | `designs.csv` output |
| PXDesign | `--pxdesign` | Protenix-scored design outputs |

---

## Repository Structure

```
evaluate.sh           # Run a full evaluation (single command entry point)
install.sh            # Create all three conda environments
envs/                 # Conda environment definitions (binder-eval, -boltz2, -af2)
binder_comparison/    # Core package: CLI, extractors, refolding runners, report generator
scripts/              # Standalone refold scripts (refold_boltz2.py, refold_af2.py)
example/              # Example outputs from CALCA run
docs/                 # Pipeline reference notes
pyproject.toml
```

---

## References

- ipSAE metric: Dunbrack et al. 2025
- Boltz-2: Markov Research
- AlphaFold2 multimer via ColabDesign
- BindCraft: github.com/martinpacesa/BindCraft

---

## Troubleshooting

### 1. `AF2_DATA_DIR` not set or AF2 weights missing

```bash
export AF2_DATA_DIR=/path/to/af2_params
ls "$AF2_DATA_DIR"/params_model_*.npz   # should list 5 model files
```

If the `.npz` files are missing, download them:
```bash
# See https://github.com/google-deepmind/alphafold for download instructions
```

### 2. CUDA version mismatch

Symptoms: `RuntimeError: CUDA error` or JAX failing to initialise.

```bash
nvidia-smi          # check driver CUDA version
nvcc --version      # check toolkit version (if installed)
```

If the driver version is too old, update your NVIDIA driver. If reinstalling the
evaluator environments, pass the matching CUDA version:

```bash
bash install.sh   # environments are pinned to compatible CUDA versions
```

### 3. `binder-eval-af2` environment not found

```bash
conda env list                    # check if environment exists
bash install.sh                   # re-run evaluator installer
```

### 4. ColabDesign import error

If `refold-af2` fails with an import error from ColabDesign:

```bash
conda run -n binder-eval-af2 pip install --force-reinstall colabdesign==1.1.1
```

### 5. PAE file not found during report generation

If `report` fails because `*_pae.npy` files are missing, the refolding step was
interrupted before saving PAE arrays. Re-run with `--resume` to fill in the gaps:

```bash
bash evaluate.sh \
    --sequences sequences.fasta \
    --target-pdb target.pdb \
    --output ./results \
    --resume
```

### 6. Mosaic venv path not found

The evaluator installer saves the Mosaic venv path to `envs/mosaic_venv_path`.
If this file is missing or wrong:

```bash
# Re-run the evaluator installer (auto-detects the venv)
bash install.sh

# Or set manually
echo "/path/to/Mosaic/.venv" > envs/mosaic_venv_path
```

### 7. Duplicate CSV rows after a partial run

If a refolding step was interrupted and re-run without `--resume`, the append-mode
CSV may contain duplicate entries. Deduplicate with:

```bash
# Use --resume on re-run to skip already-completed sequences
bash evaluate.sh --sequences sequences.fasta --target-pdb target.pdb --output ./results --resume

# Or manually deduplicate an existing CSV (keeps first occurrence)
python -c "
import pandas as pd
df = pd.read_csv('results/boltz2_results.csv')
df = df.drop_duplicates(subset='sequence', keep='first')
df.to_csv('results/boltz2_results.csv', index=False)
"
```
