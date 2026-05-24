# Proteina-Complexa — Worker Operations

**Env:** `Proteina-Complexa/.venv` (uv venv, Python 3.12) or Docker container
**Run-script template:** `bindmaster_examples/run_proteina_complexa.sh.template`
**Engine reference:** `bindmaster-orchestrator/references/tools/proteina-complexa.md`

PC has the most complex setup of any tool in the BindMaster stack (Hydra config tree, multiple checkpoint variants, separate `.env` for community model paths). Verify carefully.

## Source-of-truth files

| File / directory | What it tells you |
|---|---|
| **`outputs/<run_name>/analyze/`** | Aggregate analysis CSVs — final result |
| **`outputs/<run_name>/evaluate/`** | Per-sample evaluation with AF2/RF3/ESMFold results |
| `outputs/<run_name>/filter/` | Post-reward-filtering survivors |
| `outputs/<run_name>/generate/` | Raw flow-matching samples |
| `outputs/<run_name>/.hydra/` | Hydra config snapshot + logs |
| `$PC/logs/.../generate.log` | Real Python tracebacks for generate stage |
| sbatch `.out` | Wrapper-level + stage transitions |

PC runs a four-stage pipeline: `generate → filter → evaluate → analyze`. Each stage writes to its own subdirectory. Progress can be monitored by which subdirectories have populated.

## Pre-flight specific to Proteina-Complexa

- **Ubuntu 22.04+ (or equivalent GLIBC)** — Ubuntu 20.04 will throw GLIBC errors. Use Docker option on older systems.
- **NOT supported on aarch64 yet** — per CLAUDE.md known issues, Proteina-Complexa hasn't been ported to ARM64. Don't accept assignments for Spark.
- **`.env` populated with community model paths:**
  ```
  AF2_DIR=/path/to/AF2/params
  ESM_DIR=/path/to/ESM2
  RF3_CKPT_PATH=/path/to/rf3.ckpt
  RF3_EXEC_PATH=/path/to/.venv/bin/rf3
  SC_EXEC=/path/to/sc                  # CCP4 shape complementarity
  FOLDSEEK_EXEC=/path/to/foldseek
  MMSEQS_EXEC=/path/to/mmseqs
  DSSP_EXEC=/path/to/dssp
  LOCAL_CODE_PATH=/path/to/Proteina-Complexa
  COMMUNITY_MODELS_PATH=${LOCAL_CODE_PATH}/community_models
  DATA_PATH=/path/to/PFM_data
  ```
  Run `complexa init` for the wizard if `.env` is missing.
- **Model checkpoints downloaded:** `complexa download --all` or per-variant (`--complexa-all`). Three variants per pipeline:
  - Protein Binder: `complexa.ckpt` + `complexa_ae.ckpt`
  - Ligand Binder: `complexa_ligand.ckpt` + `complexa_ligand_ae.ckpt`
  - AME (Motif Scaffolding): `complexa_ame.ckpt` + `complexa_ame_ae.ckpt`
- **`dssp` and `sc` binaries** present at the paths in `.env`. Not bundled with PC; obtain from FreeBindCraft repo (`functions/` dir) or build locally.
- **2 GPUs by default** (`gen_njobs=2`, `eval_njobs=2`). If on single GPU, override:
  ```
  complexa design ... ++gen_njobs=1 ++eval_njobs=1
  ```
- **AME targets** require specific chain conventions: ligand on chain A as `L:0`, motif residues on chain B. Malformed inputs cause silent failures. The bundled `M0024_1nzy_v3` is the example.
- **Config validation** before design:
  ```
  complexa validate design configs/search_binder_local_pipeline.yaml
  ```
  Catches config resolution errors (missing env vars, bad paths) at config-time rather than burning hours.

## OOM / hardware limits

| GPU class | Behavior |
|---|---|
| 24 GB | Not recommended — default config wants 2 GPUs, single 24 GB usually OOMs |
| 48 GB | Workable with `gen_njobs=1 eval_njobs=1` overrides |
| 80+ GB | Fine for default 2-GPU config (or single-GPU with overrides) |

JAX AF2 reward model recompiles per unique sequence length on the first sample of each new length (~20 s build + compile, then 1-5 s per sample). Many length variations = many recompiles.

## Common errors

- **GLIBC errors on Ubuntu 20.04** → use Docker option.
- **`InterpolationKeyError` at config resolution** → an env var referenced in YAML config isn't set in `.env`. Run `complexa validate` to identify which.
- **tmol install failure on Python 3.12** → llvmlite/numba version conflict. The README documents the pre-install workaround for `build_uv_env.sh`. See engine reference.
- **AME silent failures** → wrong chain/residue naming in input PDB. Re-chain so ligand is chain A as `L:0` and motif residues are chain B.
- **RF3 ligand atom-completion errors during AME evaluation** → RF3 attempts to add missing atoms based on CCD code, causing shape mismatches. Workaround per README:
  ```python
  from atomworks.io import load_any, to_pdb_file
  atom_array = load_any("my_design.pdb")[0]
  ligand_mask = atom_array.chain_id == "A"
  atom_array.res_name[ligand_mask] = "L:0"
  to_pdb_file(atom_array, "my_design_rf3_ready.pdb")
  ```
- **JAX AF2 first-sample slow (~20 s)** — expected; subsequent samples ~1-5 s. Don't kill thinking it's wedged.

## Wedge / kill criteria

- **`generate/` not progressing after first sample completed + 1 h** — wedge.
- **Any stage's log shows OOM repeatedly** — kill, ask orchestrator for memory adjustments.
- **Wall exceeds 2× initial estimate** — kill.

## Packaging recipe

```bash
cd ~/runs/<TARGET>-<machine>-proteina-complexa/
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_ProteinaComplexa_<machine>.tar.gz \
    outputs/<run_name>/generate/ \
    outputs/<run_name>/filter/ \
    outputs/<run_name>/evaluate/ \
    outputs/<run_name>/analyze/ \
    outputs/<run_name>/.hydra/ \
    .env \
    run.sh *.out
```

For `_final`:

```bash
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_ProteinaComplexa_<machine>_final.tar.gz \
    outputs/<run_name>/analyze/ \
    outputs/<run_name>/filter/successful/ \
    outputs/<run_name>/.hydra/
```

## Reporting back

```markdown
🔄 → ✅ | SLURM <id> done. Pipeline: generate → filter → evaluate → analyze.
Generated: <N> samples. After filter: <X>. After evaluate: <Y>. Final analyzed: <Z>.
Reward models used: AF2 w=<w1>, RF3 w=<w2>, force-field w=<w3>.
Search algorithm: <beam-search | MCTS | best-of-N>.
Top metrics: <from analyze CSVs>.
Diversity (Foldseek clusters): <count>.
Wall: <h> on <GPU>. Compute: <GPU-h>.
Packaged: <TARGET>_ProteinaComplexa_<machine>.tar.gz (<size>).
```

**Note about cross-validation:** Proteina-Complexa uses AF2 and RF3 as reward models internally, not Boltz-2 — so the orchestrator's Boltz-2 refold is a structurally independent check for PC outputs. See `bindmaster-orchestrator/references/tools/README.md` cross-method bias matrix.
