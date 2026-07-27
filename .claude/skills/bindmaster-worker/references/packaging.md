# Packaging + Transfer to RESULTS/

Once a run finishes (success or failure), you package the outputs. **Assignment mode** (Clara, non-LAN machines): transfer the tarball to muni-disk yourself, as before. **Driven mode** (BM1/BM2/BM4, launched via `tools/fleet.sh` from BM5): package locally and leave it in the run dir — BM5 pulls it with `fleet.sh fetch` and archives a copy to muni-disk itself; you don't push. This file's naming convention and per-tool recipes are unchanged either way — only the transfer leg differs (see "Transfer" below).

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

The commands below write straight to `/path/to/RESULTS/` — that's the **assignment-mode** convention (muni-disk mounted or VPN-reachable). **In driven mode** (BM1/BM2/BM4), tar to a local path instead — anywhere under the run dir works, e.g. `~/runs/<TARGET>-<machine>-<tool>/<TARGET>_<tool>_<machine>.tar.gz` — and leave it there for BM5 to pull with `fleet.sh fetch` (see "Transfer", below). Everything else about these recipes — what's included, the naming convention — is identical either way.

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

## Transfer

### Driven mode (BM1/BM2/BM4, launched via `tools/fleet.sh`)

Leave the tarball where you packaged it, in the run dir on the worker machine — you don't push to muni-disk yourself. BM5 (playing the orchestrator role here) pulls it:

```bash
tools/fleet.sh fetch <machine> <remote-dir>/<TARGET>_<tool>_<machine>.tar.gz ~/eval_workdir/<TARGET>/
```

This runs `rsync -s -a --partial` and, for a `.tar.gz`, verifies the archive with `tar -tzf` before declaring success — a corrupt or partial transfer dies loudly (`fetch` refuses to report success) rather than silently landing a bad file. BM5 then archives one copy to muni-disk RESULTS/ itself; that copy — not your worker-side tarball — is what closes the campaign record. See `bindmaster-orchestrator/references/lab-deploy.md` §3.5.

You still append the completion-entry to PROGRESS.md (below) — driven mode doesn't change who owns that record, only who does the muni-disk write.

### Assignment mode (Clara, non-LAN machines)

#### If muni-disk is mounted directly

```bash
cp <TARGET>_<tool>_<machine>.tar.gz /path/to/muni-disk/<TARGET>/RESULTS/
```

Verify the copy:

```bash
ls -la /path/to/muni-disk/<TARGET>/RESULTS/<TARGET>_<tool>_<machine>.tar.gz
# Check the file size matches
```

#### If muni-disk needs VPN switching (Clara → MUNI)

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

Driven mode: `fleet.sh fetch` already verifies `.tar.gz` integrity automatically with `tar -tzf` (see above) — no manual step needed. The checksum flow below is for assignment-mode scp/rsync transfers.

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

Until the muni-disk archive is confirmed readable and complete. The worker-side run dir is your local backup until the campaign closes — this holds in both modes, just who does the confirming differs.

Pattern that works (assignment mode):
1. Transfer tarball to muni-disk.
2. Append completion-entry to PROGRESS.md Worker updates.
3. Wait for the orchestrator to merge and confirm.
4. Only after that confirmation, optionally delete the worker-side run dir (with user OK).

Pattern that works (driven mode):
1. Package locally; leave the tarball in the run dir.
2. Append completion-entry to PROGRESS.md Worker updates, noting it's ready for `fleet.sh fetch`.
3. Wait for BM5 to fetch (`tar -tzf`-verified) and archive to muni-disk.
4. Only after that confirmation, optionally delete the worker-side run dir (with user OK).

If disk space pressure is real, *move* the tarball locally to a "delete-pending" subdirectory rather than deleting outright — gives a recovery window if the muni-disk copy is bad.

## Append the completion-entry to PROGRESS.md

After successful transfer (or, in driven mode, after packaging — see pattern above):

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
🔄 → ✅ | SLURM <id> done. <accept-count> accepts at iPTM ≥ <threshold>, <total> total designs.
Wall: <hours>. Compute: <GPU-hours> on <node-id>.
Packaged: <TARGET>_<tool>_<machine>.tar.gz (<size>) at RESULTS/.
[Optional] _final subset: <TARGET>_<tool>_<machine>_final.tar.gz (<size>).
[Optional] New error: <error + reproduction>.
[Optional] New lesson: <one sentence candidate for learnings.md>.
```

**Driven mode:** replace `SLURM <id>` with the tmux job name, and replace "Packaged: ... at RESULTS/" with "Packaged: ... in `<remote-dir>`, ready for `fleet.sh fetch`" — the RESULTS/ path is only accurate once BM5 has archived its own fetched copy there.

For failures (❌) or planned kills:

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
🔄 → ❌ | SLURM <id> failed at hour <X>. <Failure mode in one line>.
Inner traceback: <log path on worker>.
Partial outputs (if useful): packaged as <TARGET>_<tool>_<machine>_partial.tar.gz.
Suggested next step: <retry with X, or abandon this config>.
```

The orchestrator merges this on next read.
