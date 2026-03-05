# TODO: Pre-packed Standalone Distribution (Part I — future)

> **Status:** Planned, not started. Depends on Part H (local Miniforge standalone installer).
>
> **Goal:** Ship BindMaster as a single archive that requires zero installation, zero internet,
> and zero system permissions on the target server. Extract, set PATH, run.

---

## Overview

Use `conda-pack` to create relocatable archives of every conda environment, bundle them
with the Mosaic uv venv, tool source code, and model weights into a single distributable
tar.gz. An `unpack.sh` script on the target machine extracts and patches paths.

```
Build machine (full internet, GPU)         Target server (restricted, air-gapped OK)
─────────────────────────────────          ──────────────────────────────────────────
bindmaster install --tool all              tar xzf bindmaster-standalone-*.tar.gz
bindmaster pack --output FILE              cd BindMaster
                                           bash unpack.sh
   produces:                               export PATH="$(pwd)/bin:$PATH"
   bindmaster-standalone-v0.8.0-           bindmaster configure
     x86_64-cuda124.tar.gz                 bash runs/myrun/run_all.sh
   (~10-20 GB compressed)
```

---

## Prerequisites

- Part H complete (local Miniforge standalone installer)
- All envs installed and tested under `BindMaster/conda/envs/`
- `conda-pack` available (`pip install conda-pack` or `conda install conda-pack`)
- For Mosaic venv: `venv-pack2` or manual tar + path patching

---

## Architecture

### Archive contents

```
bindmaster-standalone-v0.8.0-x86_64-cuda124.tar.gz
└── BindMaster/
    ├── conda/                          (Miniforge3 base — stripped, ~200 MB)
    │   ├── bin/
    │   ├── etc/profile.d/conda.sh
    │   └── envs/                       (empty — populated by unpack.sh)
    ├── envs_packed/                    (relocatable env archives)
    │   ├── BindCraft.tar.gz            (~4 GB compressed)
    │   ├── BoltzGen.tar.gz             (~3 GB compressed)
    │   ├── binder-eval.tar.gz          (~500 MB compressed)
    │   └── binder-eval-af2.tar.gz      (~1.5 GB compressed)
    ├── mosaic_venv_packed.tar.gz       (~2 GB compressed)
    ├── BindCraft/                      (source code + AF2 weights)
    │   ├── params/*.npz                (~4 GB — optional, see --no-weights)
    │   └── ... (source files)
    ├── BoltzGen/                       (source code, weights downloaded separately)
    ├── Mosaic/                         (source code, no .venv — unpacked by unpack.sh)
    ├── Evaluator/                      (bundled evaluation pipeline)
    ├── configurator/
    ├── evaluator/
    ├── bindmaster.py
    ├── bin/                            (shortcuts — patched by unpack.sh)
    ├── unpack.sh                       (post-extraction setup script)
    ├── pack_manifest.json              (metadata: versions, platform, checksums)
    └── ... (other repo files)
```

### Size estimates

| Component | Raw | Compressed (gzip) | Notes |
|---|---|---|---|
| Miniforge3 base (stripped) | ~500 MB | ~200 MB | Remove pkgs/, docs |
| BindCraft env | ~12 GB | ~4 GB | Includes PyRosetta, JAX, CUDA |
| BindCraft AF2 weights | ~4 GB | ~3.5 GB | 15 x .npz files (poorly compressible) |
| BoltzGen env | ~8 GB | ~3 GB | PyTorch + CUDA 12.1 |
| BoltzGen weights | ~6 GB | ~5 GB | Downloaded on first run — exclude by default |
| Mosaic venv | ~6 GB | ~2 GB | JAX + Boltz-2 + CUDA |
| binder-eval env | ~2 GB | ~500 MB | Lightweight, Python 3.10 |
| binder-eval-af2 env | ~5 GB | ~1.5 GB | ColabDesign + JAX CUDA |
| Source code | ~50 MB | ~20 MB | Negligible |
| **Total (no model weights)** | **~34 GB** | **~11 GB** | |
| **Total (with AF2 weights)** | **~38 GB** | **~15 GB** | |
| **Total (all weights)** | **~44 GB** | **~20 GB** | Including BoltzGen weights |

---

## Implementation plan

### I1. Add `conda-pack` to binder-eval env (or base conda)

- `conda install -n base conda-pack` or `pip install conda-pack` in the build env
- Verify it can pack each env: `conda pack -n BindCraft -o /tmp/test.tar.gz`
- Document minimum conda-pack version (>=0.7.0 for Python 3.12 support)

### I2. Create `pack/build_pack.sh` — the build script

Runs on the build machine (requires completed install + GPU for smoke tests).

```bash
#!/bin/bash
# Build a standalone BindMaster distribution archive.
# Usage: bash pack/build_pack.sh [--no-weights] [--output FILE]

Steps:
  1. Validate all tools are installed (conda envs exist, Mosaic venv exists)
  2. Run smoke tests on each env
  3. conda-pack each conda env into envs_packed/
  4. Pack Mosaic venv:
     - Tar the .venv directory
     - Record original prefix for path patching
  5. Strip Miniforge base:
     - Remove conda/pkgs/ (package cache)
     - Remove conda/envs/ (will be unpacked on target)
     - Keep bin/, lib/, etc/ (needed for conda activate/run)
  6. Optionally include model weights (--no-weights to exclude)
     - AF2: BindCraft/params/*.npz
     - BoltzGen: ~/.boltz/ or wherever cached (skip by default)
  7. Generate pack_manifest.json:
     {
       "version": "0.8.0",
       "platform": "x86_64",
       "cuda": "12.4",
       "glibc_min": "2.35",
       "python_versions": {"BindCraft": "3.10", "BoltzGen": "3.12", ...},
       "envs": ["BindCraft", "BoltzGen", "binder-eval", "binder-eval-af2"],
       "includes_weights": {"af2": true, "boltzgen": false},
       "checksums": {"BindCraft.tar.gz": "sha256:...", ...},
       "build_date": "2026-03-05",
       "build_host": "hostname"
     }
  8. Create final archive:
     tar czf bindmaster-standalone-v${VERSION}-${ARCH}-cuda${CUDA}.tar.gz \
       --exclude='conda/pkgs' --exclude='conda/envs' \
       BindMaster/
```

### I3. Create `pack/unpack.sh` — the target setup script

Runs on the target server after extracting the archive. No internet needed.

```bash
#!/bin/bash
# Unpack BindMaster standalone distribution.
# Usage: bash unpack.sh

Steps:
  1. Verify pack_manifest.json exists and is valid
  2. Check platform matches (uname -m vs manifest)
  3. Check glibc version >= manifest minimum:
     ldd --version 2>&1 | head -1
  4. For each packed conda env:
     mkdir -p conda/envs/NAME
     tar xzf envs_packed/NAME.tar.gz -C conda/envs/NAME/
     conda/envs/NAME/bin/conda-unpack    # fixes hardcoded paths
  5. Unpack Mosaic venv:
     tar xzf mosaic_venv_packed.tar.gz -C Mosaic/
     # Patch shebangs and pyvenv.cfg:
     sed -i "s|ORIGINAL_PREFIX|$(pwd)/Mosaic/.venv|g" Mosaic/.venv/bin/*
     sed -i "s|ORIGINAL_PREFIX|$(pwd)/Mosaic/.venv|g" Mosaic/.venv/pyvenv.cfg
  6. Regenerate shortcuts in bin/:
     Write bindmaster, bindcraft, boltzgen, mosaic, evaluate scripts
     with correct absolute paths ($(pwd)/conda/, $(pwd)/Mosaic/, etc.)
  7. Validate:
     conda/bin/conda run -n BindCraft python -c "import colabdesign; print('OK')"
     conda/bin/conda run -n BoltzGen boltzgen --help
     Mosaic/.venv/bin/python -c "import mosaic; print('OK')"
  8. Print instructions:
     export PATH="$(pwd)/bin:$PATH"
     # Add to .bashrc for persistence
```

### I4. Create `pack/manifest.py` — manifest generation helper

Python script (stdlib only) that:
- Reads installed env versions (conda list)
- Computes SHA-256 checksums of packed archives
- Writes `pack_manifest.json`
- Validates manifest on unpack

### I5. Add `bindmaster pack` subcommand to `bindmaster.py`

```python
elif cmd == "pack":
    script = REPO / "pack" / "build_pack.sh"
    os.execv("/bin/bash", ["/bin/bash", str(script)] + args)
```

### I6. Handle venv relocation properly

The Mosaic uv venv contains hardcoded paths in:
- `pyvenv.cfg` (`home = /original/path/.venv/bin`)
- Shebang lines in `bin/` scripts (`#!/original/path/.venv/bin/python`)
- `.pth` files and `site-packages/*.dist-info/RECORD`
- `__pycache__/*.pyc` files (contain embedded paths)

Approach:
- Record original venv prefix during build
- On unpack, use `sed` to rewrite prefix in text files
- Delete `__pycache__/` directories (rebuilt on first import)
- Alternative: investigate `venv-pack2` package which handles this automatically

### I7. Handle BoltzGen weights (optional inclusion)

BoltzGen downloads ~6 GB of Boltz-1 model weights on first run to `~/.boltz/`.
Options:
- **Default:** Exclude weights, let user download on first run (requires internet)
- **`--include-boltzgen-weights`:** Copy `~/.boltz/` into archive, set `BOLTZ_CACHE_DIR`
  env var in run scripts to point to local copy
- Document the tradeoff (archive size vs first-run download)

### I8. Platform variants and CI

Build matrix:

| Variant | Arch | CUDA | glibc min | Notes |
|---|---|---|---|---|
| x86_64-cuda124 | x86_64 | 12.4 | 2.35 (Ubuntu 22.04) | Primary |
| x86_64-cuda121 | x86_64 | 12.1 | 2.35 | BoltzGen uses cu121 |
| aarch64-cuda130 | aarch64 | 13.0 | 2.35 | DGX Spark |

CI options:
- **GitHub Actions with self-hosted GPU runner** (ideal but expensive)
- **Manual build on lab machine** (practical for now)
- Upload to GitHub Releases with release notes

### I9. Incremental update mechanism (future)

For updating a packed installation without re-downloading everything:
- `bindmaster update --pack` downloads only changed env packs
- Compare `pack_manifest.json` versions
- Deferred — full repack is acceptable for now

### I10. Documentation

- Add `docs/standalone_pack.md` with:
  - How to build a pack
  - How to deploy on a target server
  - Platform requirements
  - Troubleshooting (glibc mismatch, CUDA driver version, disk space)
- Update README.md with "Standalone deployment" section
- Update CONTRIBUTING.md with pack build instructions

---

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| glibc version mismatch | Env won't run, cryptic errors | Check in unpack.sh, document requirements |
| CUDA driver too old | GPU ops fail at runtime | Check `nvidia-smi` in unpack.sh, warn |
| conda-pack can't handle PyRosetta | BindCraft env broken | Test early; fallback: exclude PyRosetta, install from channel on target |
| Archive too large for GitHub Releases (2 GB limit) | Can't host on GH | Use split archives or external hosting (Zenodo, institutional S3) |
| Mosaic venv path patching misses some files | Import errors | Delete __pycache__, comprehensive sed, smoke test in unpack.sh |
| Python .pyc files contain original paths | Warnings or errors | Delete all __pycache__ dirs during build, they regenerate |
| Packed env activation slow | UX degradation | Acceptable — same as normal conda, no mitigation needed |

---

## Open questions

1. **Hosting:** GitHub Releases has 2 GB per-asset limit. Split into multiple files? Use
   institutional storage? Zenodo (50 GB free for research)?
2. **BoltzGen weights:** Include by default or not? First-run download may not work on
   air-gapped servers.
3. **Selective packing:** Allow `bindmaster pack --tool mosaic,boltzgen` to create smaller
   archives with only some tools?
4. **Signature/verification:** Should packed archives be GPG-signed for integrity? Overkill
   for academic use?

---

## Dependencies

- Part H (local Miniforge standalone) must be complete first
- `conda-pack >= 0.7.0`
- Build machine with all tools installed and tested
- ~60 GB free disk on build machine (raw + compressed)
