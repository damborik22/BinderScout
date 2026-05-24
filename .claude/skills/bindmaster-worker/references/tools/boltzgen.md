# BoltzGen — Worker Operations

**Env:** conda env `BoltzGen` (Python 3.12)
**Run-script template:** `bindmaster_examples/run_boltzgen.sh.template`
**Engine reference:** `bindmaster-orchestrator/references/tools/boltzgen.md`

## Source-of-truth files

| File / directory | What it tells you |
|---|---|
| **`final_ranked_designs/final_<budget>_designs/`** | Final diversity-filtered designs (the deliverable) |
| **`final_ranked_designs/final_designs_metrics_<budget>.csv`** | Per-design metrics for the final selection |
| `final_ranked_designs/all_designs_metrics.csv` | Full population metrics (useful for re-filtering) |
| `intermediate_designs_inverse_folded/refold_cif/*.cif` | Refolded structures post-inverse-folding |
| `intermediate_designs_inverse_folded/aggregate_metrics_analyze.csv` | Pre-filter analysis metrics |
| `final_ranked_designs/results_overview.pdf` | Diagnostic plots |
| sbatch `.out` | Stage transitions and SLURM wall |

For progress monitoring, the most useful single signal is the `intermediate_designs_inverse_folded/refold_cif/` directory file count — it grows as the `folding` pipeline step processes designs. Wait until the `filtering` step writes `final_ranked_designs/` for "done."

## Pipeline stages to expect (in order)

1. `design` — diffusion-based backbone generation (longest stage)
2. `inverse_folding` — BoltzGen IF model generates sequences
3. `folding` — Boltz-2 refolds complex (binder + target)
4. `design_folding` — Boltz-2 refolds binder alone (skipped for peptide/nanobody)
5. `affinity` — Boltz-2 affinity prediction (only protein-small_molecule protocol)
6. `analysis` — compute design-quality metrics
7. `filtering` — diversity-aware ranking to `--budget`

The `filtering` step is fast (~15 s) and re-runnable without redesigning — useful if the user wants to retune thresholds post-run.

## Pre-flight specific to BoltzGen

- **Model cache (~6 GB)** at `~/.cache` (or `$HF_HOME` if set, or `--cache <path>`). First run downloads. Verify after first launch:
  ```bash
  ls ~/.cache/huggingface/hub/models--boltzgen--*
  ls ~/.cache/huggingface/hub/models--boltz--*
  ```
- **mmCIF residue indexing** — BoltzGen uses `label_asym_id` (canonical mmCIF), NOT `auth_asym_id` (author). If the assignment's YAML mis-references residues, hotspots end up in the wrong place. Always run `boltzgen check <yaml>` first and visualize the generated mmCIF (open in MolStar; binding-site colored differently than rest).
- **`--use_msa_server` setup** — defaults to ColabFold MMseqs2 server. Has rate limits; the orchestrator may have configured a private MSA setup instead. Check the assignment.

## OOM / hardware limits

| GPU class | Behavior on 389 aa target (2VDY-like) |
|---|---|
| 24 GB | OOMs at design stage; ship to ≥48 GB |
| 48 GB (L40S) | Handles up to ~300 aa fine; large targets may need lower `diffusion_batch_size` |
| 80 GB (A100) | Fine for almost everything |
| 141 GB (H200, GH200) | Fine for everything |

## Common errors

- **Boltz-2 cache `ALA.pkl` missing** → `troubleshooting.md` §5.1. Bootstrap `~/.boltz/` with `download_boltz2(cache=Path.home()/'.boltz')`.
- **MSA server rate limit (HTTP 429)** — back off, the run will retry. Don't smash retry yourself.
- **JAX OOM at start** → `XLA_PYTHON_CLIENT_PREALLOCATE=false`.
- **mmCIF index confusion** — symptoms include hotspots in wrong location, "binding site" looks wrong in the check output. Always `boltzgen check` before submitting.

## Wedge / kill criteria

- **Wall exceeds 2× initial estimate** in any single stage — kill.
- **`intermediate_designs/` empty after 6+ hours** — design stage wedged, kill.
- **MSA server returning persistent 5xx** — kill, alert orchestrator.

## Packaging recipe

```bash
cd ~/runs/<TARGET>-<machine>-boltzgen/
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_BoltzGen_<machine>.tar.gz \
    final_ranked_designs/ \
    intermediate_designs_inverse_folded/refold_cif/ \
    intermediate_designs_inverse_folded/aggregate_metrics_analyze.csv \
    intermediate_designs_inverse_folded/per_target_metrics_analyze.csv \
    config/ steps.yaml \
    run.sh *.out
```

For `_final` subset (BoltzGen's full output can be 50+ GB — the `_final` is often what the orchestrator actually wants for quick inspection):

```bash
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_BoltzGen_<machine>_final.tar.gz \
    final_ranked_designs/final_<budget>_designs/ \
    final_ranked_designs/final_designs_metrics_<budget>.csv \
    final_ranked_designs/results_overview.pdf \
    config/
```

## Reporting back

```markdown
🔄 → ✅ | SLURM <id> done. <num_designs> intermediate → <budget> final.
Refolding RMSD threshold: <X>. Filter pass rate: <%>.
Top final designs metric range: iPTM_refold <min>-<max> (Boltz-2 native, [0,1] scale).
Wall: <h> on <GPU>. Compute: <GPU-h>.
Packaged: <TARGET>_BoltzGen_<machine>.tar.gz (<size>), _final (<size>).
```

**Note about cross-validation:** the orchestrator knows BoltzGen's internal refolding is via Boltz-2 — same model as the evaluator's default refold. The `agreement_count` signal for BoltzGen outputs is most decisive when Protenix and AF3 also agree (engines independent of BoltzGen's design lineage). See `bindmaster-orchestrator/references/tools/README.md` cross-method bias matrix.
