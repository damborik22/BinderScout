# Packaging + Transfer to RESULTS/

Once a run finishes (success or failure), you package the outputs. **Assignment mode** (HPC cluster, non-LAN machines): transfer the tarball to the shared archive yourself, as before. **Driven mode** (<node1>/<node2>/<node3>, launched from the orchestrator machine): package locally and leave it in the run dir — the orchestrator machine pulls it (rsync, integrity-verified) and archives a copy to the shared archive itself; you don't push. This file's naming convention and per-tool recipes are unchanged either way — only the transfer leg differs (see "Transfer" below).

## Naming convention

```
<TARGET>_<tool>_<machine>.tar.gz        ← full run dir, all evidence
<TARGET>_<tool>_<machine>_final.tar.gz  ← curated subset (optional, for large outputs)
<TARGET>_<tool>_<machine>.zip           ← smaller variant if tar.gz tooling unavailable
```

Examples:

```
<TARGET>_BindCraft_<node>.tar.gz
2VDY_BoltzGen_<node>.tar.gz
2VDY_BoltzGen_<node>_final.tar.gz          ← curated, only Accepted/ + key CSVs
ApoE4_RFD3_Spark.tar.gz
CALCA_ProteinHunter_<node>.tar.gz
```

The evaluator does not parse these names: it attributes designs by which `--<tool> DIR` flag each unpacked tool directory is passed under (`binder-compare extract --bindcraft DIR …`) and writes `report/metrics.csv`. **Keep this naming anyway** — the fetch command and PROGRESS.md entries below use it.

## What to include vs. exclude

Each tool has a different "real evidence" set. See per-tool guidance below. General principles:

**Always include:**
- The tool's source-of-truth CSV (`final_design_stats.csv`, `summary.csv`, `designs.csv`, etc.)
- Accepted design structures (`.pdb`, `.cif`, or `.cif.gz`)
- Per-design metric files (`.npz` for PAE matrices, `.json` for AF3/RFD3 per-design metadata)
- The run script `run.sh` (for reproduction)
- The `target_settings.json` (or equivalent) used
- The per-run `settings.json` in the tool's output dir (`runs/<name>/<tool>/` under `bindmaster configure`) — every generated run script writes it before the design step; it records `tool`, `started_at`, `version`, `target`, `design_params` and `env`, i.e. what produced these designs
- The sbatch `.out` log (for wall-clock and SLURM ID provenance)

**Exclude (to save space):**
- Trajectory PDBs for failed designs (BindCraft `bindcraft/outputs/Trajectory/` and `Rejected/` — usually optional; `bindcraft/outputs/` itself is the results directory, never exclude it)
- Tool conda env directories (they're rebuildable; never tar an env)
- Boltz-2 cache (`~/.boltz/` — rebuildable, machine-specific)
- PXDesign kernel compilation cache (rebuildable)

When unsure, err toward inclusion. Disk is cheap; lost evidence is expensive.

## Per-tool packaging recipes

The commands below write straight to `/path/to/RESULTS/` — that's the **assignment-mode** convention (the shared archive mounted or VPN-reachable). **In driven mode** (<node1>/<node2>/<node3>), tar to a local path instead — anywhere under the run dir works, e.g. `~/runs/<TARGET>-<machine>-<tool>/<TARGET>_<tool>_<machine>.tar.gz` — and leave it there for the orchestrator machine to pull (see "Transfer", below). Everything else about these recipes — what's included, the naming convention — is identical either way.

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
    bindcraft/outputs/Accepted/Ranked/ \
    bindcraft/outputs/final_design_stats.csv \
    bindcraft/target_settings.json
```

Skip `bindcraft/outputs/Trajectory/` unless the campaign needs trajectory provenance. Skip `bindcraft/outputs/MPNN/` and `bindcraft/outputs/Rejected/` unless debugging.

### BoltzGen

```bash
cd ~/runs/<TARGET>-<machine>-boltzgen/
tar czf /path/to/RESULTS/<TARGET>_BoltzGen_<machine>.tar.gz \
    boltzgen/outputs/final_ranked_designs/ \
    boltzgen/outputs/intermediate_designs_inverse_folded/refold_cif/ \
    boltzgen/outputs/intermediate_designs_inverse_folded/aggregate_metrics_analyze.csv \
    boltzgen/outputs/intermediate_designs_inverse_folded/per_target_metrics_analyze.csv \
    boltzgen/outputs/config/ \
    boltzgen/outputs/steps.yaml \
    boltzgen/config.yaml \
    boltzgen/settings.json \
    run*.sh \
    *.out
```

The `_final` subset (substantially smaller — BoltzGen's full output can be 50+ GB):

```bash
tar czf /path/to/RESULTS/<TARGET>_BoltzGen_<machine>_final.tar.gz \
    boltzgen/outputs/final_ranked_designs/final_<budget>_designs/ \
    boltzgen/outputs/final_ranked_designs/final_designs_metrics_<budget>.csv \
    boltzgen/outputs/final_ranked_designs/results_overview.pdf \
    boltzgen/outputs/config/
```

### Mosaic

```bash
cd ~/runs/<TARGET>-<machine>-mosaic/
tar czf /path/to/RESULTS/<TARGET>_Mosaic_<machine>.tar.gz \
    mosaic/designs.csv \
    mosaic/structures_*/ \
    mosaic/hallucinate.py \
    mosaic/settings.json \
    run*.sh \
    *.out
```

Note: if Mosaic's `designs.csv` mixed 11-col and 13-col rows during the run (multiple workers concurrent — a known issue), the orchestrator's evaluator handles this. Don't try to fix the CSV; pass it through as-is.

### Protein-Hunter

```bash
cd ~/runs/<TARGET>-<machine>-protein-hunter/
tar czf /path/to/RESULTS/<TARGET>_ProteinHunter_<machine>.tar.gz \
    protein_hunter/high_iptm_yaml/ \
    protein_hunter/high_iptm_pdb/ \
    protein_hunter/summary_high_iptm.csv \
    protein_hunter/summary_all_runs.csv \
    run.sh \
    *.out
```

Note there is no `<name>/` subdirectory: at the pinned Protein-Hunter commit `--save_dir` is used as-is, and `--name <TARGET>_<variant>` only prefixes filenames (`<name>_run_<N>_cycle_<M>_structure.pdb`). A `<name>/` layer exists only when `--save_dir` is omitted (`./results_boltz/<name>/`).

### PXDesign

```bash
cd ~/runs/<TARGET>-<machine>-pxdesign/
tar czf /path/to/RESULTS/<TARGET>_PXDesign_<machine>.tar.gz \
    pxdesign/outputs*/design_outputs/ \
    pxdesign/input*.yaml \
    pxdesign/sequences.csv \
    pxdesign/settings.json \
    run*.sh \
    *.out
```

### Proteina-Complexa

```bash
cd ~/runs/<TARGET>-<machine>-proteina-complexa/
tar czf /path/to/RESULTS/<TARGET>_ProteinaComplexa_<machine>.tar.gz \
    proteina_complexa/structures/ \
    proteina_complexa/raw/ \
    proteina_complexa/sequences.csv \
    proteina_complexa/target_bindmaster.yaml \
    proteina_complexa/settings.json \
    run*.sh \
    *.out
```

All of this lives in the run dir: the run script's harvest step copies Complexa's PDBs and metrics CSVs out of its own clone (`Proteina-Complexa/inference/`, `evaluation_results/`) into `proteina_complexa/{structures,raw}/` and adds a `structure` column to `sequences.csv`. Package from the run dir, never from the clone — it is gitignored and `bindmaster install --uninstall` deletes it.

For the `_final` subset:

```bash
tar czf /path/to/RESULTS/<TARGET>_ProteinaComplexa_<machine>_final.tar.gz \
    proteina_complexa/sequences.csv \
    proteina_complexa/structures/ \
    proteina_complexa/settings.json
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

### Driven mode (<node1>/<node2>/<node3>, launched)

Leave the tarball where you packaged it, in the run dir on the worker machine — you don't push to the shared archive yourself. The orchestrator machine (playing the orchestrator role here) pulls it:

```bash
rsync -s -a --partial <fleet-node>:<remote-dir>/<TARGET>_<tool>_<machine>.tar.gz ~/eval_workdir/<TARGET>/ && tar -tzf ~/eval_workdir/<TARGET>/<TARGET>_<tool>_<machine>.tar.gz >/dev/null
```

This runs `rsync -s -a --partial` and, for a `.tar.gz`, verifies the archive with `tar -tzf` before declaring success — a corrupt or partial transfer dies loudly (the fetch should refuse to report success) rather than silently landing a bad file. The orchestrator machine then archives one copy to the shared archive RESULTS/ itself; that copy — not your worker-side tarball — is what closes the campaign record.

You still append the completion-entry to PROGRESS.md (below) — driven mode doesn't change who owns that record, only who does the shared archive write.

### Assignment mode (HPC cluster, non-LAN machines)

#### If the shared archive is mounted directly

```bash
cp <TARGET>_<tool>_<machine>.tar.gz /path/to/<shared-storage>/<TARGET>/RESULTS/
```

Verify the copy:

```bash
ls -la /path/to/<shared-storage>/<TARGET>/RESULTS/<TARGET>_<tool>_<machine>.tar.gz
# Check the file size matches
```

#### If the shared archive needs VPN switching (cluster → storage)

**Announce the VPN switch in PROGRESS.md Worker updates first:**

```markdown
### 2026-MM-DD HH:MM — cluster L40S — BindCraft tuned
🔄 → packaging | Run complete, packaging tarball locally.
VPN: switching from cluster VPN to storage VPN to transfer.
```

Then do the switch, transfer, and switch back if you need the HPC cluster access for anything else:

```bash
# disconnect the HPC cluster VPN
# connect storage VPN
scp <TARGET>_<tool>_<machine>.tar.gz user@<storage-host>:/path/to/<TARGET>/RESULTS/
# (or rsync -avP)
ssh user@<storage-host> "ls -la /path/to/<TARGET>/RESULTS/<TARGET>_<tool>_<machine>.tar.gz"
# verify size matches local

# disconnect storage VPN
# (reconnect the HPC cluster VPN only if you need ongoing the HPC cluster access)
```

### Verifying transfer integrity

Driven mode: The orchestrator's fetch step should verify `.tar.gz` integrity automatically with `tar -tzf` (see above) — no manual step needed. The checksum flow below is for assignment-mode scp/rsync transfers.

For large tarballs, checksum-verify:

```bash
# Locally
md5sum <TARGET>_<tool>_<machine>.tar.gz

# On the shared storage (after transfer)
ssh user@<storage-host> "md5sum /path/to/<TARGET>/RESULTS/<TARGET>_<tool>_<machine>.tar.gz"

# Match → transfer good
```

Not always necessary, but cheap insurance for >10 GB archives.

## Don't delete the worker-side copy yet

Until the shared archive is confirmed readable and complete. The worker-side run dir is your local backup until the campaign closes — this holds in both modes, just who does the confirming differs.

Pattern that works (assignment mode):
1. Transfer tarball to the shared archive.
2. Append completion-entry to PROGRESS.md Worker updates.
3. Wait for the orchestrator to merge and confirm.
4. Only after that confirmation, optionally delete the worker-side run dir (with user OK).

Pattern that works (driven mode):
1. Package locally; leave the tarball in the run dir.
2. Append completion-entry to PROGRESS.md Worker updates, noting it's ready for the orchestrator to fetch.
3. Wait for the orchestrator machine to fetch (`tar -tzf`-verified) and archive to the shared archive.
4. Only after that confirmation, optionally delete the worker-side run dir (with user OK).

If disk space pressure is real, *move* the tarball locally to a "delete-pending" subdirectory rather than deleting outright — gives a recovery window if the shared copy is bad.

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

**Driven mode:** replace `SLURM <id>` with the tmux job name, and replace "Packaged: ... at RESULTS/" with "Packaged: ... in `<remote-dir>`, ready for the orchestrator to fetch" — the RESULTS/ path is only accurate once the orchestrator machine has archived its own fetched copy there.

For failures (❌) or planned kills:

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
🔄 → ❌ | SLURM <id> failed at hour <X>. <Failure mode in one line>.
Inner traceback: <log path on worker>.
Partial outputs (if useful): packaged as <TARGET>_<tool>_<machine>_partial.tar.gz.
Suggested next step: <retry with X, or abandon this config>.
```

The orchestrator merges this on next read.
