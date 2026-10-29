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
cd BinderScout
```

### Install tools

`bindmaster.py` writes the `bindmaster` shortcut itself, on any invocation
(`_install_bindmaster_shortcut()`), so the first run goes through the entrypoint in the
clone:

```bash
python3 bindmaster.py install --tool all
```

Afterwards `bindmaster install …` works, once `bin/` is on your PATH:

```bash
export PATH="$(pwd)/bin:$PATH"
```

---

## Conda environments

| Environment | Purpose | Python |
|---|---|---|
| `BindCraft` | BindCraft AF2 + MPNN design | 3.10 |
| `BoltzGen` | BoltzGen Boltz-1 design | 3.12 |
| Mosaic `.venv` (uv) | Mosaic hallucination + Boltz-2 refolding | 3.12 |
| `bindmaster_pxdesign` | PXDesign (Protenix) | 3.11 |
| Proteina-Complexa `.venv` (uv) | Flow matching binder design | 3.12 |
| `bindmaster_protein_hunter` | Protein-Hunter hallucination (Boltz-2 / Chai-1) | 3.10 |
| `bindmaster_rfd3` | RFD3 (`rc-foundry`) diffusion + ProteinMPNN | 3.12 |
| `binder-eval` | Evaluator extract + report | 3.10 |
| `binder-eval-esmfold2` | Evaluator ESMFold2 refolding — **default engine** | 3.12 |
| `binder-eval-af3` | Evaluator AF3 v3.0.2 refolding — canonical 2nd engine; env built by `--tool all`, **weights gated** | 3.12 |
| `binder-eval-soluprot` | SoluProt solubility screen (sequence-only, pre-refold) | 3.7 |

Eleven environments; `CLAUDE.md` is the canonical table. There is **no `binder-eval-af2`
env** — AF2 refolding was deleted in Part I; the installers reference the name only to
remove legacy pre-refactor installs.

> Each tool/environment is isolated. Never mix packages across environments.

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

`evaluate.sh` takes the target as a **sequence**, not a PDB, and the repository ships no
example inputs — point it at a run of your own:

```bash
cd Evaluator
bash evaluate.sh \
    --sequences /path/to/binders.fasta \
    --target-seq "MGFQKFSPF..." \
    --output ./test_results
```

`bash evaluate.sh --help` prints the full flag list. Useful ones while developing:

- `--skip-boltz2` **reuses** an existing `boltz2_results.csv` (and hard-errors if the file
  is missing), so it is the one skip flag that keeps its engine in the report.
- `--skip-af3` / `--skip-esmfold2` **drop** that engine from the report rather than reusing
  its CSV. Combine with `--min-engines 2` or every design fails the default 3-engine gate.
- `--min-engines 2` when a host is genuinely short an engine.
- `--resume` to pick up a part-finished refold.

---

## Pull request conventions

- **Title**: imperative mood, under 70 characters (e.g. "Add PAE heatmaps to HTML report")
- **Body**: reference STAGES.md items (e.g. "Implements E5")
- **CI must pass**: shellcheck, ruff, Docker build
- **One logical change per PR** — split large work into batches matching STAGES.md parts

---

## Branch structure

**There is no `aarch64` branch.** Both installers live on `master`, side by side —
`install/install.sh` for x86_64 and `install/install_aarch.sh` for aarch64 / DGX Spark.
An earlier version of this table listed a platform branch that does not exist on the
remote, so `git checkout aarch64` fails.

| Branch | What it is | Target it? |
|---|---|---|
| `master` | Both platforms. Frozen at the current release; 2.0 work happens elsewhere | Bug fixes and documentation, yes |
| `v2.0.x` | Active development line. Diverged from master at `602345a` and is well ahead | Features, yes — ask first |
| `v1.1.x` | Retired midpoint, kept for now | No |

The three lines share no commits after `602345a`, so **nothing crosses over by itself**:
a fix that lands on `master` needs forward-porting to `v2.0.x`, and vice versa. Say in
the PR which lines you think it belongs on.

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
