# BindCraft — Worker Operations

**Env:** conda env `BindCraft` (Python 3.10)
**Run-script template:** `bindmaster_examples/run_bindcraft.sh.template`
**Engine reference (for context):** `bindmaster-orchestrator/references/tools/bindcraft.md`

This file is operational — the engine reference covers the principle, knobs, and "when to pick." Here we cover where progress shows up, how to verify outputs, common errors, and packaging.

## Source-of-truth files

| File | What it tells you |
|---|---|
| **`final_design_stats.csv`** | The canonical accept count. New row per accept. Header-only = 0 accepts. |
| `MPNN_design_stats.csv` | MPNN candidate count (most don't pass AF2 cross-val) |
| `bindcraft.log` (outer) | Wrapper-level events: stage transitions, acceptance-rate monitoring, kill events |
| `bindcraft/outputs/*.log` (inner) | Real Python tracebacks if it crashes — most recent timestamp |
| `Accepted/Ranked/*.pdb` | Final ranked design structures |
| sbatch `.out` | SLURM wall, exit code |

**DO NOT count `ls Accepted/` for completion** — there are always 4 empty placeholder subdirs (`Ranked/`, `BIRDS/`, etc.) regardless of accept count. Count rows in `final_design_stats.csv` instead.

## Pre-flight specific to BindCraft

In addition to the generic `pre-flight.md` checks:

- **AF2 weights** (~5.3 GB) — verify presence in the env: `ls ~/.colabdesign_params/` or wherever BindCraft expects them. The installer downloads on first run.
- **PyRosetta license** — academic free, commercial requires license. Confirm the env was installed with the right license posture.
- **Aarch64 binaries (if on Spark / ARM):** `DAlphaBall.gcc` and `dssp` ARM64 versions bundled in `bindmaster_examples/`. The run-script template copies them; verify post-copy:
  ```bash
  file ~/dev/BindMaster/BindCraft/functions/DAlphaBall.gcc
  # Should report: ELF 64-bit LSB shared object, ARM aarch64
  ```
- **Beta detection / `optimise_beta`** — if running on a known beta-sheeted target, the trajectory might trigger extra iterations. Wall-clock budget should account for this.

## OOM / hardware limits

| GPU class | Hard ceilings |
|---|---|
| 24 GB (3090, 4090) | Binder length ≤ 120 always; ≤ 130 only with hotspots OFF |
| 48 GB (L40S, A6000) | Up to 150 aa fine |
| 80 GB (A100) | Up to ~180 aa |
| 141 GB (H200, GH200) | Up to 200 aa |

If you OOM on a 24 GB card with binder length ≥130 hotspots-on, that's the documented limit. Report it; orchestrator may need to reassign.

## Common errors

- **PyRosetta `DAlphaBall.gcc` missing libgfortran** → `troubleshooting.md` §2. Set `LD_LIBRARY_PATH` and `LD_PRELOAD` inline.
- **JAX OOM at start (XLA preallocation)** → `troubleshooting.md` §4.3. Set `XLA_PYTHON_CLIENT_PREALLOCATE=false` or `XLA_PYTHON_CLIENT_MEM_FRACTION=0.75`.
- **Squashed trajectories** — AF2-multimer is sensitive to sequence input; documented limitation. Detected and discarded automatically. Inflates effective trajectory cost but isn't a failure.
- **0 accepts after 60+ trajectories** — likely the wrong filter/advanced preset for this target. Check learnings.md §3 for V2+V4 vs V1+default; the assignment should already have picked the right combo.

## Wedge / kill criteria

- **Process RSS > 50 GB** — JAX leak. Kill, restart (BindCraft can resume from `Accepted/Ranked/` + `final_design_stats.csv`).
- **Acceptance rate dropped to 0 and 60+ trajectories elapsed** — BindCraft's internal `acceptance_rate` monitor will auto-stop. If it doesn't, kill.
- **Wall exceeds 2× initial estimate without first accept** — kill.

The assignment should name the kill criterion explicitly. Apply that one.

## Packaging recipe

See `packaging.md` for the canonical recipe. Quick version:

```bash
cd ~/runs/<TARGET>-<machine>-bindcraft/
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_BindCraft_<machine>.tar.gz \
    Accepted/ \
    final_design_stats.csv \
    MPNN_design_stats.csv \
    target_settings.json advanced_settings.json filters.json \
    run.sh bindcraft.log *.out

# Skip trajectories/ unless campaign needs trajectory provenance
# Skip bindcraft/outputs/ unless debugging
```

For a curated `_final` subset (faster for orchestrator to inspect):

```bash
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_BindCraft_<machine>_final.tar.gz \
    Accepted/Ranked/ final_design_stats.csv target_settings.json
```

## Reporting back

Completion entry should include:

```markdown
🔄 → ✅ | SLURM <id> done. <N> accepts (iPTM range: <min> to <max>).
MPNN candidates: <M>; accept rate <N/M> = <%>.
Top metrics: iPTM_avg <x>, dG <y>, ShapeComplementarity <z> (from final_design_stats.csv top row).
Wall: <h> on <GPU>.
Compute: <GPU-h> on <node-id>.
Packaged: <TARGET>_BindCraft_<machine>.tar.gz (<size>).
```
