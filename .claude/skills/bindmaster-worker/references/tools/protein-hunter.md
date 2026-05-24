# Protein-Hunter — Worker Operations

**Env:** conda env `bindmaster_protein_hunter`
**Run-script template:** `bindmaster_examples/run_protein_hunter.sh.template`
**Engine reference:** `bindmaster-orchestrator/references/tools/protein-hunter.md`

Protein-Hunter is in active integration in BindMaster — the configurator does not yet auto-generate run scripts. Hand-write from the template, carefully.

## Source-of-truth files

| File / directory | What it tells you |
|---|---|
| **`<save_dir>/<name>/summary_high_iptm.csv`** | Designs passing `--high_iptm_threshold` and `< 20%` alanine (default filter) |
| **`<save_dir>/<name>/high_iptm_cif/`** | CIF structures for the high-iPTM designs |
| **`<save_dir>/<name>/high_iptm_yaml/`** | YAML specs for each accepted design |
| `<save_dir>/<name>/summary_all_runs.csv` | Full per-cycle metrics across all designs (browse here for everything) |
| `<save_dir>/<name>/plots/` | Per-design diagnostic plots |
| `runs/<n>/protein_hunter/<name>/logs/*.log` | Per-design inner logs (for triage) |

**Output path trap:** with `--save_dir runs/<TARGET>/protein_hunter --name <TARGET>_<variant>`, outputs actually land at `protein_hunter/<TARGET>_<variant>/...` — a doubled-name subdirectory under `save_dir`. The path is printed twice in the run banner, which is confusing but correct.

**Row count > num_designs is expected:** every cycle that crosses `--high_iptm_threshold` gets a row in `summary_high_iptm.csv`. A 7-cycle run with several passing cycles produces more rows than designs. Don't be alarmed; report row count and design count separately.

## Pre-flight specific to Protein-Hunter

In addition to the generic checks:

- **Boltz-2 cache at `~/.boltz/`** populated — see `troubleshooting.md` §5.1. **This is the most common pre-flight failure for PH.**
- **`--msa_mode` value:** `single` or `mmseqs`. NOT `single_sequence` (that's the most common typo — `argparse: invalid choice`). Per learnings.md §1, prefer `mmseqs` for known targets.
- **`pyrosetta-installer` version** ≥ 0.3 renamed `download_pyrosetta` → `install_pyrosetta`. If your install script uses the old name, you'll fail at install time. See `troubleshooting.md` §5.7.
- **AF3 cross-validation disabled** unless the assignment explicitly enables it. Default is off; BindMaster usage typically skips the AF3 cross-val (heavy and not needed since the orchestrator runs AF3 in evaluation phase anyway).
- **`--percent_X` calibration** — assignment will name a value (typically 50-100). Too high (mostly-X initial sequence) risks floating/disconnected structures; too low narrows the design space.

## OOM / hardware limits

| GPU class | Behavior |
|---|---|
| 24 GB | OOMs on most targets ≥300 aa; ship to ≥48 GB |
| 48 GB (L40S) | Fine for moderate-size targets |
| 80+ GB | Fine for everything |

Cycle-iterative design has lower peak memory than gradient-based hallucination tools (BindCraft, Mosaic), but still needs ≥48 GB for non-trivial targets.

## Common errors

- **`--msa_mode single_sequence` rejected** → use `single` or `mmseqs`. See `troubleshooting.md` §5.2.
- **`ValueError: CCD component ALA not found!`** → Boltz-2 cache missing `mols/ALA.pkl`. See §5.1.
- **`download_boltz2` silent no-op** → must pass positional `Path` argument, not `str`. See §5.1.
- **`install_pyrosetta` not found** → installer using old name `download_pyrosetta`. See §5.7.
- **"No structure was generated for run N (no eligible best design …)"** → not a failure; none of the N cycles produced a sequence under the alanine cap. See §6.3.
- **Output appearing at unexpected path** → doubled subdirectory under `save_dir`. Don't try to "fix" the path; the orchestrator's evaluator finds it.

## Wedge / kill criteria

- **`summary_high_iptm.csv` empty + `summary_all_runs.csv` not growing after 6 h** — wedge.
- **All cycles for all designs producing 0 sequences** — `--percent_X` too restrictive given alanine cap. Kill, ask orchestrator to adjust.
- **Wall exceeds 2× initial estimate** — kill.

## Packaging recipe

```bash
cd ~/runs/<TARGET>-<machine>-protein-hunter/
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_ProteinHunter_<machine>.tar.gz \
    protein_hunter/<name>/high_iptm_yaml/ \
    protein_hunter/<name>/high_iptm_cif/ \
    protein_hunter/<name>/summary_high_iptm.csv \
    protein_hunter/<name>/summary_all_runs.csv \
    protein_hunter/<name>/plots/ \
    run.sh *.out
```

(Path uses the doubled-subdirectory layout; adjust if your `--save_dir` was different.)

## Reporting back

```markdown
🔄 → ✅ | SLURM <id> done. <num_designs> designs, <num_cycles> cycles each.
<X> cycle-passes in summary_high_iptm.csv (note: > num_designs is normal).
Unique designs in high_iptm_cif/: <Y>.
Top iPTM: <z> (Boltz-2 + target MSA).
Wall: <h> on <GPU>. Compute: <GPU-h>.
Packaged: <TARGET>_ProteinHunter_<machine>.tar.gz (<size>).
```

**Note about cross-validation:** Protein-Hunter (Boltz edition) hallucinates against Boltz-2 — same model as the evaluator's default refold. Per learnings.md §5, scoring engines aren't directly comparable across tools. The orchestrator's `agreement_count` weighting handles this.
