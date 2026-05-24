# Mosaic — Worker Operations

**Env:** `Mosaic/.venv` (uv venv, Python 3.12)
**Run-script template:** `bindmaster_examples/run_mosaic.sh.template`
**Engine reference:** `bindmaster-orchestrator/references/tools/mosaic.md`

Mosaic is a framework, not a turnkey tool. The assignment's settings table will be detailed because the loss weights, optimizer params, and recycling steps all need explicit values per target.

## Source-of-truth files

| File | What it tells you |
|---|---|
| **`designs.csv`** | Per-design sequence + Mosaic-internal metrics (Boltz-2 design-time confidence, `ranking_loss`). Header + ~800 rows typical. |
| **`is_top` column in designs.csv** | Boolean — `True` for the ~40 designs Mosaic refolded internally and kept as "top." Default evaluator filter is `is_top=1`. |
| `refold_cifs/*.cif` | Re-folded structures for `is_top=1` designs |
| `refold_paes/*.npz` | Per-design PAE matrices (Boltz-2 native [binder\|target] ordering) |
| sbatch `.out` | Stdout — Mosaic doesn't have a separate log file. JIT-compile messages appear here. |

For progress monitoring: `wc -l designs.csv` grows monotonically as design steps complete. Slow start because of JIT compilation (~minutes); steady-state ~1 design per few seconds depending on hardware.

## Pre-flight specific to Mosaic

- **JAX + CUDA in the venv** — verify with:
  ```bash
  source ~/dev/BindMaster/Mosaic/.venv/bin/activate
  python -c "import jax; print(jax.devices())"
  # Should list GPU(s); CPU-only means CUDA setup broken
  ```
- **Boltz-2 cache at `~/.boltz/`** (Mosaic uses Boltz-2 for refolding via `joltz`) — same pre-flight as Protein-Hunter / BoltzGen. See `troubleshooting.md` §5.1.
- **`use_msa` settings in the run script:**
  - Binder: `use_msa=False` (de novo binder, no MSA available)
  - Target: `use_msa=True` for known targets — but **only set once**. Otherwise Mosaic's continuously-evolving binder triggers a fresh MMseqs request per design step and accumulates past the rate limit (per `learnings.md` §1).
- **`target_sequence` not set to `"REPLACE_ME"`** — that's the template placeholder. Mosaic will silently skip designs with placeholder targets. Check before launching.

## OOM / hardware limits

| GPU class | Behavior |
|---|---|
| 24 GB | OOMs on most targets ≥300 aa; ship to ≥48 GB |
| 48 GB (L40S) | Fine for moderate-size targets and standard composite losses |
| 80+ GB | Fine for everything; composite losses with multiple structure predictors stack memory |

Composite-objective design (multiple loss terms each requiring a structure prediction call) stacks memory fast. If the assignment specifies a multi-objective loss, double-check GPU memory budget.

## Common errors

- **JIT compilation slow start** — normal. First few designs take much longer than steady-state. Don't kill the run thinking it's wedged in the first 15 minutes.
- **Mixed 11/13-column `designs.csv`** when multiple workers wrote concurrently → `troubleshooting.md` §6.4. Pass through as-is; evaluator handles it.
- **`"REPLACE_ME"` in target_sequence** → evaluator silently skips. Symptom: 0 refolded outputs despite normal-looking `designs.csv`. Verify pre-flight.
- **Boltz-2 cache missing `mols/ALA.pkl`** → `troubleshooting.md` §5.1.
- **JAX OOM with composite losses** → reduce `recycling_steps`, drop one loss term, or move to a bigger GPU.

## Wedge / kill criteria

- **`designs.csv` not growing after JIT-warmup phase (15 min)** — wedge.
- **JAX recompilation thrashing** — visible in stdout as repeated "compiling..." messages. Means loss weights or optimizer params caused a graph change; likely a misconfiguration.
- **Wall exceeds 2× initial estimate** — kill.

## Packaging recipe

```bash
cd ~/runs/<TARGET>-<machine>-mosaic/
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_Mosaic_<machine>.tar.gz \
    designs.csv \
    refold_outputs/ \
    refold_cifs/*.cif \
    refold_paes/*.npz \
    target_settings.py run.sh *.out
```

Include `refold_outputs/` (which holds Boltz-2 prediction outputs for `is_top=1` designs) — it has the `.cif` + `.npz` pairs the evaluator needs.

For `_final` (just the top designs):

```bash
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_Mosaic_<machine>_final.tar.gz \
    designs.csv \
    refold_cifs/ refold_paes/ \
    target_settings.py
```

The `designs.csv` is small enough to always include in full (~800 rows).

## Reporting back

```markdown
🔄 → ✅ | SLURM <id> done. <total> designs generated; <is_top> marked is_top=1 and refolded.
Loss weights used: <list from assignment for clarity>.
Top metrics: ranking_loss min <x>, iPTM_design max <y> (Boltz-2 design-time, NOT cross-validated).
Wall: <h> on <GPU>. Compute: <GPU-h>.
Packaged: <TARGET>_Mosaic_<machine>.tar.gz (<size>).
```

**Note about cross-validation:** Mosaic's design-time confidence is from Boltz-2 — the same model the evaluator uses by default. Mosaic-output `agreement_count` is most decisive when Protenix and AF3 agree independently. See `bindmaster-orchestrator/references/tools/README.md`.
