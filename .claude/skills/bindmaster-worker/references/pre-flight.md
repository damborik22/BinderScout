# Pre-flight Checks — Before Submitting Any Worker Job

Run these checks in order before touching the run script. If any fails, append a failure entry to `PROGRESS.md` Worker updates and ask the orchestrator/user — don't muscle through.

## 1. Read and validate the assignment

**Driven mode (BM1/BM2/BM4 via `tools/fleet.sh`):** there's no `CLUSTER/` doc — read the run script `fleet.sh launch` will ship (or already shipped) instead; it carries the same settings a `CLUSTER/` doc's "Setup / install" section would. The rest of this checklist (§2-5, §7-9) still applies; §6 (muni-disk reachability) does not.

Open `CLUSTER/<TARGET>_<tool>_<machine>_SETTINGS.md`. Confirm it has:

- Why this run (1 paragraph)
- Settings table with `Param | Value | Why`
- `target_settings.json` (or equivalent) copy-pasteable
- Setup / install commands
- Runtime expectation + kill criterion
- Output handoff (tar/zip command, destination)
- Critical gotchas
- Pinned BindMaster commit SHA

Any missing section → ask the orchestrator. Don't improvise the missing parts.

## 2. Verify conda env / venv

The assignment names the env. Check it exists:

```bash
conda env list | grep <env_name>
# or for venvs:
ls -la ~/dev/BindMaster/<tool>/.venv/bin/python
```

Activate and test:

```bash
set +u                              # required around conda activate (see troubleshooting.md §6)
conda activate <env_name>
set -u

# Sanity check the tool's CLI runs
<tool> --help                       # or python -c "import <tool>"
```

If the env doesn't exist, or activation fails, or the import errors out — that's a pre-flight failure. Report and stop.

## 3. Verify GPU + memory class

```bash
nvidia-smi
```

Check:
- **GPU present** (not all lab machines have one; confirm the assignment matched correctly)
- **Memory class matches assignment expectation:**
  - 24 GB (3090, 4090) — has hard ceilings; see `tools/<tool>.md` for per-tool limits
  - 48 GB (L40S, A6000) — handles most tools at moderate target sizes
  - 80+ GB (A100, H100, H200, GH200) — handles anything

If memory class is below what the assignment needs, that's a pre-flight failure. The orchestrator may have made an assumption that doesn't hold; report it.

### 3.1 GPU-busy floor (BM1/BM2/BM4)

When checking "is the GPU actually free" before a manual launch on one of the LAN machines, apply the same >512 MiB floor `tools/fleet.sh` uses (`GPU_BUSY_MIB`) — small desktop-integration processes ride the GPU permanently on these boxes and don't count as busy. Confirmed on BM4: a ~6 MiB `snapd-desktop-integration` process and, at times, a ~294 MiB `rustdesk` process are both always-on and both correctly ignored by the floor. A check without the floor will conclude the machine is busy when it isn't.

```bash
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits \
    | awk -F', *' '$2+0 > 512'
# empty output = actually idle
```

`fleet.sh launch` applies this floor automatically when you go through it (driven mode); apply it by hand if you're checking GPU occupancy on a LAN machine outside `fleet.sh`.

### 3.2 RAM class (LAN machines — GPU memory and system RAM are different budgets)

```bash
free -g | awk '/^Mem:/{print $2}'   # total installed RAM, not free/available
```

BM1 has **31 GB** total RAM against BM2/BM4's 62 GB. The BindCraft JAX RSS leak (§ below, and `troubleshooting.md` §4.4) killed BM4 at 58 GB after nine days; on BM1 the same run OOMs far sooner, before it produces meaningful yield. **Do not route long BindCraft runs to BM1** — short jobs or non-BindCraft tools are fine there.

### 3.3 `PYTORCH_CUDA_ALLOC_CONF` (LAN machines, RFD3)

All three x86 LAN boxes are 24 GB Ampere, so `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` is mandatory before `rfd3 design` (fragmentation OOM — see `troubleshooting.md` §4.2). `fleet.sh launch` exports this automatically for every driven-mode job. If you're hand-starting a job — assignment mode, or a manual session outside `fleet.sh` — set it yourself.

## 4. Verify disk space

```bash
df -h ~/runs                # local scratch
df -h /path/to/muni-disk    # output destination (if mounted)
```

Budget guide per tool (rough):

| Tool | Local scratch | Output tarball |
|---|---|---|
| BindCraft | 30-80 GB (trajectories + outputs) | 5-30 GB |
| BoltzGen | 50-200 GB (intermediate + refold dirs) | 10-100 GB |
| Mosaic | 20-60 GB | 5-15 GB |
| Protein-Hunter | 30-80 GB (per-cycle outputs) | 10-30 GB |
| PXDesign | 30-80 GB | 5-20 GB |
| Proteina-Complexa | 50-150 GB (multi-stage) | 15-50 GB |
| RFD3 | 20-50 GB | 5-15 GB |

If <100 GB free on `~/runs`, clean up old run dirs (with user confirmation) before starting.

## 5. Verify BindMaster repo is at pinned commit

```bash
cd ~/dev/BindMaster
git fetch --all
git status                          # should be clean
git checkout <pinned-SHA-from-assignment>
git log -1 --oneline                # verify HEAD
```

If the pinned SHA doesn't exist locally even after fetch, the orchestrator may have committed locally on Spark without pushing. Report it.

If the repo has uncommitted changes locally, that's a worker-side mess; ask before stashing or discarding.

## 6. Verify muni-disk reachable

This check applies to **assignment mode** — Clara, or any machine reading a `CLUSTER/` doc directly. **Skip it for driven-mode LAN jobs** (BM1/BM2/BM4 launched via `tools/fleet.sh` from BM5): the run script arrives by direct SSH push, not a `CLUSTER/` read, and results are pulled back by `fleet.sh fetch` and archived to muni-disk by BM5 itself — the worker machine never touches muni-disk in that flow. See `bindmaster-orchestrator/references/lab-deploy.md`.

For assignment mode, either it's mounted:

```bash
ls /path/to/muni-disk/<TARGET>/CLUSTER/   # should show your assignment
```

Or it needs the right VPN:

```bash
# After connecting to MUNI VPN:
ls /path/to/muni-disk/<TARGET>/CLUSTER/
```

**Which machines need which:**
- **Clara** needs the MUNI VPN to reach XBay — VPN-only access (see `troubleshooting.md` §8).
- **BM1/BM2/BM4** are on the university LAN and mount muni-disk **directly, no VPN**. If one of them is ever run in assignment mode (rather than driven mode) and needs to read a `CLUSTER/` doc, it should already be reachable without switching anything.

If not reachable and you're on Clara, you may be on the wrong VPN. Switch and re-check.

**Note for VPN switching:** if you need to switch VPN (Clara-VPN ↔ MUNI-VPN), announce it in a PROGRESS.md Worker updates entry first. The orchestrator may be relying on your current VPN for monitoring. This doesn't apply to BM1/BM2/BM4 — they need no VPN at all.

## 7. Tool-specific cache verification

Different tools cache different things. Verify per-tool before running:

### Boltz-2-based tools (Protein-Hunter, BoltzGen, Mosaic)

```bash
ls ~/.boltz/
# Should show:
#   boltz2_conf.ckpt    (~2.3 GB)
#   boltz2_aff.ckpt     (~2.1 GB)
#   mols/               (~45k .pkl files; ALA.pkl, GLY.pkl, etc.)
```

If `mols/` directory is empty or missing `ALA.pkl`, bootstrap:

```bash
python -c "from boltz.main import download_boltz2; from pathlib import Path; download_boltz2(cache=Path.home()/'.boltz')"
# NOTE: positional Path argument, NOT a string
```

### PXDesign (its internal Protenix — not a refold engine)

```bash
echo $PROTENIX_DATA_ROOT_DIR
ls $PROTENIX_DATA_ROOT_DIR/ccd_cache/   # or wherever CCD cache lives
```

If the env var isn't set, the install defaults to `${project_root}/release_data/ccd_cache`.

### RFD3

```bash
echo $FOUNDRY_CHECKPOINT_DIRS           # NOTE: plural-S; singular FOUNDRY_CHECKPOINT_DIR is silently ignored
foundry list-installed                  # should show rfd3 and proteinmpnn
```

If `proteinmpnn` is missing (RFD3 install only fetches `rfd3_latest.ckpt`), install separately:

```bash
foundry install proteinmpnn
# For ligand binders also:
foundry install ligandmpnn
```

### AF3 (refold use only, aarch64)

Database and model paths set in `binder-eval-af3` env. See `Evaluator/docs/pipeline_reference.md`.

## 8. aarch64-specific checks (Spark, future ARM nodes)

```bash
uname -m                                # should print 'aarch64'
```

Confirm tool-specific aarch64 ports:
- **BindCraft:** ARM64 `DAlphaBall.gcc` and `dssp` bundled in `bindmaster_examples/`; run-script template copies them automatically. Verify post-copy:
  ```bash
  ls -la ~/dev/BindMaster/BindCraft/functions/DAlphaBall.gcc  # should be ARM64
  file ~/dev/BindMaster/BindCraft/functions/DAlphaBall.gcc
  ```
- **Proteina-Complexa:** NOT yet ported. Refuse the assignment if it landed here by mistake; ask the orchestrator.
- **Protein-Hunter:** permanently blocked on aarch64, not just "not yet ported" — PyRosetta has no aarch64 wheels. Refuse if this machine is BM5/Spark; route to BM1/BM2/BM4 or Clara instead.
- **RFD3:** should work via foundry; the `mpnn` console-script needs ARM64-built wheels.
- **PXDesign:** install patches handle Blackwell sm_120; verify they were applied (see `troubleshooting.md`).

## 9. Final sanity step: dry-run the run script (if cheap)

Some tools have a dry-run / check mode that validates the config without launching the full pipeline:

- **BindCraft:** `python bindcraft.py --settings <target>.json --check_only` (if available in your fork)
- **BoltzGen:** `boltzgen check example/<TARGET>/<TARGET>.yaml` — validates the YAML, writes a check.cif, opens binding-site visualization
- **PXDesign:** `pxdesign pipeline --validate -i <yaml>` (if available)
- **Proteina-Complexa:** `complexa validate design configs/<pipeline>.yaml`
- **RFD3:** the `validate_only: true` JSON flag, if supported by the inference config

If the tool has a fast dry-run, use it. Catches misconfigurations before you burn 6 hours.

## Pre-flight pass — proceed

If all 9 checks pass, you're cleared to start. Move to Phase 2 (Setup + submit) in the SKILL.md.

## Pre-flight fail — report and stop

Append to PROGRESS.md Worker updates:

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
⏳ → ❌ pre-flight | <which check failed, in one line>
<details: env name, GPU class, disk free, what's missing>
Need: <what the orchestrator/user should do to unblock>
```

Then stop. Don't try to fix orchestrator-level decisions (wrong GPU class, wrong env name) yourself.
