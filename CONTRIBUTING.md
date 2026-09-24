# Contributing to BinderScout

## Development setup

### Prerequisites

- Linux (x86_64 or aarch64 with NVIDIA GPU)
- NVIDIA driver with CUDA >= 12.1
- Miniconda, Anaconda, or Miniforge
- Python >= 3.10 (system Python for `binderscout.py` and `configurator.py`)
- `git`, `docker` (for testing)

### Clone

```bash
git clone https://github.com/damborik22/BinderScout.git
cd BinderScout
```

### Install tools

```bash
binderscout install --tool all
```

---

## Conda environments

| Environment | Purpose | Python |
|---|---|---|
| `BindCraft` | BindCraft AF2 + MPNN design | 3.10 |
| BindCraft2 `.venv` (uv) | BindCraft 2 AF2 hallucination (JAX, no PyRosetta) | >= 3.12 |
| `BoltzGen` | BoltzGen Boltz-1 design | 3.12 |
| Mosaic `.venv` (uv) | Mosaic hallucination + Boltz-2 refolding | 3.12 |
| `binderscout_pxdesign` | PXDesign (Protenix) | 3.11 |
| Proteina-Complexa `.venv` (uv) | Flow matching binder design | 3.12 |
| `binderscout_protein_hunter` | Protein-Hunter (Boltz-2 / Chai-1 hallucination) | 3.10 |
| `binderscout_rfd3` | RFD3 / foundry diffusion + ProteinMPNN | 3.12 |
| `binder-eval` | Evaluator extract + report | 3.10 |
| `binder-eval-af3` | AlphaFold 3 refolding (opt-in; gated weights) | 3.12 |
| `binder-eval-esmfold2` | ESMFold2 refolding — the default engine | 3.10 |
| `binder-eval-soluprot` | SoluProt solubility screen (sequence-only, no GPU) | 3.7 |
| `binder-eval-tmprot` | TmProt melting-temperature screen (sequence-only, no GPU) | 3.11 |

> Each tool/environment is isolated. Never mix packages across environments.

BindCraft 2 is a uv venv and not a conda environment because it is a rewrite
rather than a new version of BindCraft: no PyRosetta, no conda dependency, JAX
and Python >= 3.12 the whole requirement. It coexists with BindCraft 1, which
keeps its own environment. It is installed **editable**, so `BindCraft2/` is not
a disposable build artefact — the checkout *is* the installation. That directory
is gitignored and must never be committed — its licence is its own, not this
repo's MIT. The installer clones it from [https://github.com/PacesaLab/BindCraft2](https://github.com/PacesaLab/BindCraft2)
at `v1.0.1`; override with
`binderscout install --tool bindcraft2 --bc2-source <zip|dir|git-url>` or by
exporting `$BINDCRAFT2_SOURCE` once for the host.

---

## Code style

### Python — ruff

```bash
pip install ruff
ruff check .            # lint
ruff format --check .   # format check
ruff format .           # auto-format
```

Configuration is in `ruff.toml` at the repo root. Key settings:
- Target: Python 3.10
- Line length: 120
- Quote style: double

### Shell — shellcheck

```bash
shellcheck --shell=bash --severity=warning \
    install/install.sh install/install_aarch.sh \
    Evaluator/evaluate.sh Evaluator/install.sh Evaluator/run.sh \
    docker-entrypoint.sh test_env.sh
```

When adding new shell code, prefer inline `# shellcheck disable=SCXXXX` directives
over rewriting existing patterns.

---

## Testing

### Docker test environment

```bash
docker build -f Dockerfile.test --target base -t binderscout-test .
docker run --rm -it binderscout-test bash
```

The `base` target validates the build without requiring a GPU. Full tests
require `--gpus all` and a CUDA-capable host.

### Evaluator manual testing

The quickest honest check is the integration suite — it builds a deterministic
three-engine pool, runs a real `binder-compare report` against it, and also
pins the ranking against a committed fixture from a real campaign. No GPU, no
network, about ten seconds:

```bash
pytest tests/integration/
```

To look at a report by hand, run both steps with the *environment's* Python.
System `python3` will not do: the pool builder needs numpy, and `binder-compare`
lives in the env. `$EVAL` below is your `binder-eval` env — under a standalone
install that is `./conda/envs/binder-eval`, otherwise `conda env list` will say.

```bash
EVAL=./conda/envs/binder-eval        # adjust for a system conda

"$EVAL/bin/python" -c "import sys; sys.path.insert(0, 'tests/integration'); \
    from pathlib import Path; from synthetic_pool import build; build(Path('/tmp/pool'))"

"$EVAL/bin/binder-compare" report \
    --boltz2-results   /tmp/pool/boltz2/boltz2_results.csv \
    --af3-results      /tmp/pool/af3/af3_results.csv \
    --esmfold2-results /tmp/pool/esmfold2/esmfold2_results.csv \
    --sequences        /tmp/pool/sequences.fasta \
    --output           /tmp/report
```

Then open `/tmp/report/report.html`.


## Pull request conventions

- **Title**: imperative mood, under 70 characters (e.g. "Add PAE heatmaps to HTML report")
- **Body**: reference STAGES.md items (e.g. "Implements E5")
- **CI must pass**: shellcheck, ruff, Docker build
- **One logical change per PR** — split large work into batches matching STAGES.md parts

---

## Branch structure

| Branch | Platform | Notes |
|---|---|---|
| `master` | x86_64 Linux + NVIDIA GPU | Primary development branch |
| `aarch64` | NVIDIA DGX Spark / Grace-Hopper | Periodically rebased from master |

---

## Commit style

Follow the existing `Part X:` prefix convention from STAGES.md:

```
Part G: Add CI workflow, badges, and documentation
```

For smaller changes within a part, use descriptive imperative messages:

```
Fix PAE heatmap rendering for single-sequence inputs
```
