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
git clone -b v2.0.x https://github.com/damborik22/BinderScout.git
cd BinderScout
```

The default branch is `master`, a separate 1.x line; `-b v2.0.x` gets this one.

### Install tools

```bash
./binderscout.py install --tool all   # the `binderscout` shortcut exists only after this has run once
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
| `RFD4-Proteina/.venv` (uv) | RFD4-Proteina latent-reasoning diffusion (backbone and sequence in one pass; opt-in `--tool rfd4`, the checkout is the installation) | 3.12 |
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
pip install ruff==0.17.0   # the version CI pins; bump both together
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
network, about ten seconds.

Run it with the *environment's* Python, not an ambient `pytest`. `$EVAL` below
is your `binder-eval` env — under a standalone install that is
`./conda/envs/binder-eval`, otherwise `conda env list` will say:

```bash
EVAL=./conda/envs/binder-eval        # adjust for a system conda

"$EVAL/bin/python" -m pytest tests/integration/
"$EVAL/bin/python" -m pytest tests/            # the whole suite, ~1 minute
```

A bare `pytest tests/integration/` collects but then **errors on import**: the
pool builder needs numpy, and a standalone install's base Miniforge Python does
not have it. The failure reads as a broken test rather than a missing
dependency, which is why the env is named explicitly here.

To look at a report by hand, the same applies — `binder-compare` also lives in
the env:

```bash
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

There is no `aarch64` branch: one tree serves both architectures (`install/install.sh` on
x86_64, `install/install_aarch.sh` on aarch64). Branches are release lines.

| Branch | Notes |
|---|---|
| `v2.0.x` | The 2.0 line (tags `v2.0.0` onward). Working branch for new work |
| `master` | A separate 1.x line, currently `v1.2.x`; `v2.0.x` is not an ancestor of it, so fixes are re-applied by hand, not cherry-picked |

`v1.1.x` was retired to the tag `archive/v1.1.x`.

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

---

## Releasing

A release is a tag on a clean, verified tree. Every step below exists because skipping
it once produced a tag that did not match what was tested.

1. **Start from a clean tree.** `git status` shows nothing. Never tag on a dirty tree: the
   `binderscout_git_sha` written into every run's `settings.json` must name code that exists.
2. **Run the full suite on a clean clone,** not in the directory you developed in (an
   untracked file or an editable install can make a test pass that fails for everyone
   else): clone the branch into a scratch directory and run `python -m pytest -q` there
   with the `binder-eval` environment's Python. Zero failures.
3. **Lint with the CI-pinned tools:** `ruff check .` and `ruff format --check .` with
   `ruff==0.17.0` (the version `.github/workflows/ci.yml` pins), and
   `shellcheck --shell=bash --severity=warning` over the shell scripts listed above.
4. **Write the changelog.** Move the `[Unreleased]` entries under a new
   `## [X.Y.Z] — date` heading in `CHANGELOG.md`, leaving an empty `[Unreleased]` above it.
   Call out every behaviour change a user could notice.
5. **Bump `__version__`** in `binderscout.py` in the same commit.
   `tests/test_version_matches_changelog.py` compares it with the newest numbered changelog
   heading; it is marked `xfail(strict=True)` while a release is being prepared, so the
   release commit is where that marker is removed.
6. **Create an annotated tag** on that commit (`git tag -a vX.Y.Z -m "..."`). Lightweight
   tags carry no message and no date.
7. **Push the branch and the tag,** then create the GitHub release with
   `gh release create vX.Y.Z --latest=false`. `--latest=false` so that a release of this
   line does not take the repository's "Latest" badge.
8. **Re-pin the fleet.** Move each machine's checkout to the new tag and confirm with
   `binderscout install --verify`, which reports tools built against another commit as `STALE`.

**Tags are immutable once pushed.** A clone, a fleet checkout or a recorded
`binderscout_git_sha` may already point at one. If a tag turns out to be wrong, do not move
or delete it: cut the next patch release that supersedes it and say so in the changelog.
