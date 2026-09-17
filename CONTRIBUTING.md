# Contributing to BindMaster

## Development setup

### Prerequisites

- Linux (x86_64 or aarch64 with NVIDIA GPU)
- NVIDIA driver with CUDA >= 12.1
- Miniconda, Anaconda, or Miniforge
- Python >= 3.10 (system Python for `bindmaster.py` and `configurator.py`)
- `git`, `docker` (for testing)

### Clone

```bash
git clone https://github.com/damborik22/BinderScout.git
cd BindMaster
```

### Install tools

```bash
bindmaster install --tool all
```

---

## Conda environments

| Environment | Purpose | Python |
|---|---|---|
| `BindCraft` | BindCraft AF2 + MPNN design | 3.10 |
| BindCraft2 `.venv` (uv) | BindCraft 2 AF2 hallucination (JAX, no PyRosetta) | >= 3.12 |
| `BoltzGen` | BoltzGen Boltz-1 design | 3.12 |
| Mosaic `.venv` (uv) | Mosaic hallucination + Boltz-2 refolding | 3.12 |
| `bindmaster_pxdesign` | PXDesign (Protenix) | 3.11 |
| Proteina-Complexa `.venv` (uv) | Flow matching binder design | 3.12 |
| `binder-eval` | Evaluator extract + report | 3.10 |
| `binder-eval-af2` | Evaluator AF2 refolding | 3.10 |

> Each tool/environment is isolated. Never mix packages across environments.

BindCraft 2 is a uv venv and not a conda environment because it is a rewrite
rather than a new version of BindCraft: no PyRosetta, no conda dependency, JAX
and Python >= 3.12 the whole requirement. It coexists with BindCraft 1, which
keeps its own environment. It is installed **editable**, so `BindCraft2/` is not
a disposable build artefact — the checkout *is* the installation. That directory
is gitignored and must never be committed. There is no public download either:
the source is supplied per machine, with
`bindmaster install --tool bindcraft2 --bc2-source <zip|dir>` or by exporting
`$BINDCRAFT2_SOURCE` once for the host.

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
docker build -f Dockerfile.test --target base -t bindmaster-test .
docker run --rm -it bindmaster-test bash
```

The `base` target validates the build without requiring a GPU. Full tests
require `--gpus all` and a CUDA-capable host.

### Evaluator manual testing

```bash
cd Evaluator
bash evaluate.sh \
    --sequences example/sequences.fasta \
    --target-pdb example/target.pdb \
    --output ./test_results
```

---

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
