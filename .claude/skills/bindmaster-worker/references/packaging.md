# Packaging + Transfer to RESULTS/

Once a run finishes (success or failure), you package the outputs and transfer to muni-disk so the orchestrator can pick them up. This file is the canonical convention.

## Naming convention

```
<TARGET>_<tool>_<machine>.tar.gz        ← full run dir, all evidence
<TARGET>_<tool>_<machine>_final.tar.gz  ← curated subset (optional, for large outputs)
<TARGET>_<tool>_<machine>.zip           ← smaller variant if tar.gz tooling unavailable
```

Examples:

```
2VDY_BindCraft_Clara.tar.gz
2VDY_BoltzGen_BM4.tar.gz
2VDY_BoltzGen_BM4_final.tar.gz          ← curated, only Accepted/ + key CSVs
ApoE4_RFD3_Spark.tar.gz
CALCA_ProteinHunter_BM2.tar.gz
```

The orchestrator's evaluator parses these filenames to attribute designs back to their source tool + machine in the merged `summary.csv`. **Don't deviate from this naming.**

## What to include vs. exclude

Each tool has a different "real evidence" set. See per-tool guidance below. General principles:

**Always include:**
- The tool's source-of-truth CSV (`final_design_stats.csv`, `summary.csv`, `designs.csv`, etc.)
- Accepted design structures (`.pdb`, `.cif`, or `.cif.gz`)
- Per-design metric files (`.npz` for PAE matrices, `.json` for AF3/RFD3 per-design metadata)
- The run script `run.sh` (for reproduction)
- The `target_settings.json` (or equivalent) used
- The sbatch `.out` log (for wall-clock and SLURM ID provenance)

**Exclude (to save space):**
- Trajectory PDBs for failed designs (BindCraft `trajectories/` — usually optional)
- BindCraft's `bindcraft/outputs/` intermediate JAX log files (these are huge and rarely needed)
- Tool conda env directories (they're rebuildable; never tar an env)
- Boltz-2 cache (`~/.boltz/` — rebuildable, machine-specific)
- PXDesign kernel compilation cache (rebuildable)

When unsure, err toward inclusion. Disk is cheap; lost evidence is expensive.

## Per-tool packaging recipes

### BindCraft

```bash
cd ~/runs/<TARGET>-<machine>-bindcraft/
tar czf /path/to/RESULTS/<TARGET>_BindCraft_<machine>.tar.gz \
    Accepted/ \
    final_design_stats.csv \
    MPNN_design_stats.csv \
    target_settings.json \
    advanced_settings.json \
    filters.json \
    run.sh \
    bindcraft.log \
    *.out                                    # sbatch output
```

For the `_final` subset (often what the orchestrator actually wants for fast inspection):

```bash
tar czf /path/to/RESULTS/<TARGET>_BindCraft_<machine>_final.tar.gz \
    Accepted/Ranked/ \
    final_design_stats.csv \
    target_settings.json
```

Skip `trajectories/` unless the campaign needs trajectory provenance. Skip `bindcraft/outputs/` unless debugging.

### BoltzGen

```bash
cd ~/runs/<TARGET>-<machine>-boltzgen/
tar czf /path/to/RESULTS/<TARGET>_BoltzGen_<machine>.tar.gz \
    final_ranked_designs/ \
    intermediate_designs_inverse_folded/refold_cif/ \
    intermediate_designs_inverse_folded/aggregate_metrics_analyze.csv \
    intermediate_designs_inverse_folded/per_target_metrics_analyze.csv \
    config/ \
    steps.yaml \
    run.sh \
    *.out
```

The `_final` subset (substantially smaller — BoltzGen's full output can be 50+ GB):

```bash
tar czf /path/to/RESULTS/<TARGET>_BoltzGen_<machine>_final.tar.gz \
    final_ranked_designs/final_<budget>_designs/ \
    final_ranked_designs/final_designs_metrics_<budget>.csv \
    final_ranked_designs/results_overview.pdf \
    config/
```

### Mosaic

```bash
cd ~/runs/<TARGET>-<machine>-mosaic/
tar czf /path/to/RESULTS/<TARGET>_Mosaic_<machine>.tar.gz \
    designs.csv \
    refold_outputs/ \
    refold_cifs/*.cif \
    refold_paes/*.npz \
    target_settings.py \
    run.sh \
    *.out
```

Note: if Mosaic's `designs.csv` mixed 11-col and 13-col rows during the run (multiple workers concurrent — a known issue), the orchestrator's evaluator handles this. Don't try to fix the CSV; pass it through as-is.

### Protein-Hunter

```bash
cd ~/runs/<TARGET>-<machine>-protein-hunter/
tar czf /path/to/RESULTS/<TARGET>_ProteinHunter_<machine>.tar.gz \
    protein_hunter/<name>/high_iptm_yaml/ \
    protein_hunter/<name>/high_iptm_cif/ \
    protein_hunter/<name>/summary_high_iptm.csv \
    protein_hunter/<name>/summary_all_runs.csv \
    protein_hunter/<name>/plots/ \
    run.sh \
    *.out
```

Note the doubled-name path: `--save_dir runs/<TARGET>/protein_hunter --name <TARGET>_<variant>` puts outputs at `protein_hunter/<TARGET>_<variant>/...`. Confusing but correct.

### PXDesign

```bash
cd ~/runs/<TARGET>-<machine>-pxdesign/
tar czf /path/to/RESULTS/<TARGET>_PXDesign_<machine>.tar.gz \
    design_outputs/<task_name>/ \
    <task_name>.yaml \
    run.sh \
    *.out
```

### Proteina-Complexa

```bash
cd ~/runs/<TARGET>-<machine>-proteina-complexa/
tar czf /path/to/RESULTS/<TARGET>_ProteinaComplexa_<machine>.tar.gz \
    outputs/<run_name>/generate/ \
    outputs/<run_name>/filter/ \
    outputs/<run_name>/evaluate/ \
    outputs/<run_name>/analyze/ \
    .env \
    run.sh \
    *.out
```

For the `_final` subset:

```bash
tar czf /path/to/RESULTS/<TARGET>_ProteinaComplexa_<machine>_final.tar.gz \
    outputs/<run_name>/analyze/ \
    outputs/<run_name>/filter/successful/
```

### RFD3 + MPNN

```bash
cd ~/runs/<TARGET>-<machine>-rfd3/
# Decompress .cif.gz files only if downstream needs them as .cif; otherwise leave compressed
tar czf /path/to/RESULTS/<TARGET>_RFD3_<machine>.tar.gz \
    out_dir/ \
    mpnn_out/ \
    inputs/<TARGET>.json \
    run.sh \
    *.out \
    foundry.log
```

The `mpnn_out/` directory contains the `.fa` files with N sequences per backbone. Post-processing (pick best-of-N, strip target prefix) can happen here OR in the orchestrator's evaluator — by convention, leave the raw `.fa` and let the evaluator do post-processing for consistency across runs.

## Transfer to muni-disk

### If muni-disk is mounted directly

```bash
cp <TARGET>_<tool>_<machine>.tar.gz /path/to/muni-disk/<TARGET>/RESULTS/
```

Verify the copy:

```bash
ls -la /path/to/muni-disk/<TARGET>/RESULTS/<TARGET>_<tool>_<machine>.tar.gz
# Check the file size matches
```

### If muni-disk needs VPN switching (Clara → MUNI)

**Announce the VPN switch in PROGRESS.md Worker updates first:**

```markdown
### 2026-MM-DD HH:MM — Clara L40S — BindCraft tuned
🔄 → packaging | Run complete, packaging tarball locally.
VPN: switching from Clara-VPN to MUNI-VPN to transfer.
```

Then do the switch, transfer, and switch back if you need Clara access for anything else:

```bash
# disconnect Clara VPN
# connect MUNI VPN
scp <TARGET>_<tool>_<machine>.tar.gz user@muni-disk-host:/path/to/<TARGET>/RESULTS/
# (or rsync -avP)
ssh user@muni-disk-host "ls -la /path/to/<TARGET>/RESULTS/<TARGET>_<tool>_<machine>.tar.gz"
# verify size matches local

# disconnect MUNI VPN
# (reconnect Clara VPN only if you need ongoing Clara access)
```

### Verifying transfer integrity

For large tarballs, checksum-verify:

```bash
# Locally
md5sum <TARGET>_<tool>_<machine>.tar.gz

# On muni-disk (after transfer)
ssh user@muni-disk-host "md5sum /path/to/<TARGET>/RESULTS/<TARGET>_<tool>_<machine>.tar.gz"

# Match → transfer good
```

Not always necessary, but cheap insurance for >10 GB archives.

## Don't delete the worker-side copy yet

Until the orchestrator or user confirms the muni-disk archive is readable and complete. The worker-side run dir is your local backup until the campaign closes.

Pattern that works:
1. Transfer tarball to muni-disk.
2. Append completion-entry to PROGRESS.md Worker updates.
3. Wait for the orchestrator to merge and confirm.
4. Only after that confirmation, optionally delete the worker-side run dir (with user OK).

If disk space pressure is real, *move* the tarball locally to a "delete-pending" subdirectory rather than deleting outright — gives a recovery window if the muni-disk copy is bad.

## Append the completion-entry to PROGRESS.md

After successful transfer:

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
🔄 → ✅ | SLURM <id> done. <accept-count> accepts at iPTM ≥ <threshold>, <total> total designs.
Wall: <hours>. Compute: <GPU-hours> on <node-id>.
Packaged: <TARGET>_<tool>_<machine>.tar.gz (<size>) at RESULTS/.
[Optional] _final subset: <TARGET>_<tool>_<machine>_final.tar.gz (<size>).
[Optional] New error: <error + reproduction>.
[Optional] New lesson: <one sentence candidate for learnings.md>.
```

For failures (❌) or planned kills:

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
🔄 → ❌ | SLURM <id> failed at hour <X>. <Failure mode in one line>.
Inner traceback: <log path on worker>.
Partial outputs (if useful): packaged as <TARGET>_<tool>_<machine>_partial.tar.gz.
Suggested next step: <retry with X, or abandon this config>.
```

The orchestrator merges this on next read.
