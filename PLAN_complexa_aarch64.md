# Plan: Proteina-Complexa on DGX Spark (aarch64)

## Context

Proteina-Complexa has been integrated into BindMaster on `master` (x86_64). This plan covers porting it to the `aarch64` branch for DGX Spark (GB10 Blackwell, CUDA 13.0, sm_121).

The approach follows the Mosaic pattern: try building, identify packages without aarch64 wheels, patch them out with `platform_machine != 'aarch64'` markers, then wire into `install_aarch.sh`.

Core deps (PyTorch 2.7, JAX 0.4.29) have aarch64 CUDA wheels. Likely blockers: torchtext, PyG (torch-geometric), esmj, atomworks.

## Files to modify

| File | Change |
|------|--------|
| `install/install_aarch.sh` | Add `install_proteina_complexa()`, patch function, constants, menu entry, uninstall |

Existing x86_64 reference: `install/install.sh` — search for `proteina_complexa` / `PROTEINA_COMPLEXA` to see the pattern already implemented there.

---

## Step 1: Rebase aarch64 branch from master

```bash
cd ~/BindMaster
git checkout aarch64
git fetch origin
git rebase origin/master
# Resolve conflicts if any (install_aarch.sh won't have the new tool yet — that's expected)
git push --force-with-lease origin aarch64
```

## Step 2: Naive clone + build attempt

Try the upstream build script as-is to see what breaks:

```bash
cd ~/BindMaster
git clone https://github.com/NVIDIA-Digital-Bio/proteina-complexa.git Proteina-Complexa
cd Proteina-Complexa
bash env/build_uv_env.sh 2>&1 | tee /tmp/complexa_build.log
```

## Step 3: Identify failing packages

```bash
grep -iE "error|failed|no matching distribution|could not build" /tmp/complexa_build.log
```

Expected aarch64 blockers:

| Package | Likely issue | Fix |
|---------|-------------|-----|
| `torchtext` | No aarch64 wheels on PyPI | Exclude with platform marker |
| `torch-geometric` (PyG) | No pre-built aarch64 CUDA wheels | Exclude or build from source |
| `torch-scatter/sparse/cluster` | PyG sub-deps, no aarch64 wheels | Same as PyG |
| `esmj` | No aarch64 wheel (same as Mosaic) | Exclude with platform marker |
| `atomworks` | NVIDIA package, unknown aarch64 | Test; may need exclusion |

## Step 4: Write the patch function

Based on what actually fails in Step 3, write `_patch_complexa_pyproject()` or `_patch_complexa_requirements()`.

**If Complexa uses pyproject.toml** (like Mosaic):
```bash
_patch_complexa_pyproject() {
    local toml="${PROTEINA_COMPLEXA_DIR}/pyproject.toml"
    [[ -f "${toml}" ]] || return 0

    # For each failing package, add platform_machine exclusion
    # Example for torchtext:
    if grep -q '"torchtext"' "${toml}" && ! grep -q 'platform_machine' "${toml}"; then
        sed -i 's|"torchtext",|"torchtext; platform_machine != '"'"'aarch64'"'"'",|' "${toml}"
        print_ok "Patched torchtext: excluded on aarch64"
    fi
    # Repeat for other failing packages...
}
```

**If Complexa uses requirements.txt or build_uv_env.sh hardcodes packages:**
- Patch build_uv_env.sh directly, or
- Skip it and do manual `uv venv && uv pip install` with filtered deps

## Step 5: Handle PyTorch CUDA

Spark uses CUDA 13.0 / Blackwell sm_121. PyTorch 2.7 for aarch64:
```bash
uv pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cu128
```

If `build_uv_env.sh` pins cu126, force-reinstall PyTorch after the build (same pattern as PXDesign in install_aarch.sh).

## Step 6: Rebuild and test the venv

```bash
cd ~/BindMaster/Proteina-Complexa

# If patching was needed, rebuild:
# rm -rf .venv && bash env/build_uv_env.sh

source .venv/bin/activate

# Basic imports
python -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}')"
python -c "import jax; print(f'JAX {jax.__version__}, devices: {jax.devices()}')"
python -c "import proteinfoundation; print('OK')"

# CLI
complexa --help
```

## Step 7: Quick design test

```bash
source .venv/bin/activate
cd ~/BindMaster/Proteina-Complexa

complexa init
complexa download --complexa-all

# Minimal test run
complexa design configs/search_binder_local_pipeline.yaml \
    ++run_name=spark_test \
    ++generation.search.best_of_n.replicas=1 \
    ++generation.filter.filter_samples_limit=2
```

## Step 8: Add to install_aarch.sh

Once patches are known, add to `install/install_aarch.sh` following the x86_64 pattern in `install/install.sh`:

1. **Constants** (near line 37):
   ```
   PROTEINA_COMPLEXA_REPO="https://github.com/NVIDIA-Digital-Bio/proteina-complexa.git"
   PROTEINA_COMPLEXA_COMMIT="HEAD"
   PROTEINA_COMPLEXA_DIR="${BINDMASTER_DIR}/Proteina-Complexa"
   ```

2. **Install flag**: `DO_PROTEINA_COMPLEXA=false`

3. **Arg parsing**: `proteina-complexa|proteina_complexa|complexa` case

4. **Status check**:
   ```bash
   is_proteina_complexa_installed() {
       [[ -d "${PROTEINA_COMPLEXA_DIR}" ]] && [[ -d "${PROTEINA_COMPLEXA_DIR}/.venv" ]]
   }
   ```

5. **`_patch_complexa_pyproject()`** — from Step 4 findings

6. **`install_proteina_complexa()`** — clone → patch → build venv → force-reinstall PyTorch if needed → complexa init → complexa download → AF2 weights → smoke test → shortcut

7. **Interactive menu**: 7th entry

8. **Uninstall case**: remove .venv + dir + shortcut

9. **Main wiring**: step counter, install call, summary

## Step 9: Verify end-to-end

```bash
# Full pipeline test
cd ~/BindMaster
bindmaster install --tool proteina-complexa
bindmaster configure  # enable Proteina-Complexa
bash runs/<test>/run_proteina_complexa.sh
bindmaster evaluate runs/<test>
```

## Step 10: Push

```bash
git add install/install_aarch.sh
git commit -m "Add Proteina-Complexa to aarch64 installer"
git push --force-with-lease origin aarch64
```

---

## What to bring back

After Step 3, save `/tmp/complexa_build.log` and the output of:
```bash
grep -iE "error|failed|no matching" /tmp/complexa_build.log
```

Also note:
- Contents of `Proteina-Complexa/pyproject.toml` or `requirements.txt` (whichever the build uses)
- Contents of `Proteina-Complexa/env/build_uv_env.sh`
- Whether `complexa` CLI entry point exists after build

With the build log and those files, the patch function can be written precisely.
