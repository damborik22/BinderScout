# RFD3 — Worker Operations

**Env:** conda env `bindmaster_rfd3` (replaces legacy `bindmaster_rfaa`)
**Run-script template:** `bindmaster_examples/run_rfd3.sh.template`
**Engine reference:** `bindmaster-orchestrator/references/tools/rfd3.md`

RFD3 is in active integration in BindMaster — the configurator does not yet auto-generate run scripts. Use the template carefully; it encodes several non-obvious requirements.

## Source-of-truth files

| File / directory | What it tells you |
|---|---|
| **`<out_dir>/*.cif.gz`** | Compressed mmCIF structures, one per design |
| **`<out_dir>/*.json`** | Per-design metadata (sampler params, contig, recycling info) |
| **`<mpnn_out>/*.fa`** | MPNN sequences per backbone, N sequences each |
| `<run>/foundry.log` | Real Python tracebacks for the foundry CLI |
| sbatch `.out` | Wrapper-level events, batch counters |

For progress monitoring: `ls -1 <out_dir>/*.cif.gz | wc -l` grows monotonically. RFD3 generates in batches; in steady state you should see `diffusion_batch_size` new files per batch wall-time.

## Pre-flight specific to RFD3

The CLAUDE.md runtime gotchas for RFD3 are extensive — most pre-flight failures here are due to missing them:

- **`FOUNDRY_CHECKPOINT_DIRS` is plural-S.** Singular `FOUNDRY_CHECKPOINT_DIR` is silently ignored. Symptom of missing: `Invalid checkpoint: rfd3` even though the `.ckpt` is in your dir.
  ```bash
  export FOUNDRY_CHECKPOINT_DIRS=/path/to/checkpoints
  foundry list-installed   # should show rfd3 and proteinmpnn
  ```
- **ProteinMPNN weights are NOT bundled with `foundry install rfd3`.** That command only fetches `rfd3_latest.ckpt` (~2.5 GB). MPNN weights (~7 MB) need a separate install:
  ```bash
  foundry install proteinmpnn
  # For ligand binders:
  foundry install ligandmpnn
  ```
- **`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`** is REQUIRED on Ampere-class 24 GB cards. Without it, RFD3 will run for 6-7 batches then OOM with fragmentation. See `troubleshooting.md` §4.2. The template sets this.
- **`mpnn` CLI is a SEPARATE console-script**, not part of `foundry`. The `foundry` umbrella CLI has only `install` / `list-available` / `list-installed` / `clean`. Sequence design via:
  ```bash
  mpnn --pdb_path_multi <list> --is_legacy_weights True --designed_chains '["B"]' ...
  ```
- **`--is_legacy_weights True`** is required for the `.pt`-format ProteinMPNN weights from `foundry install proteinmpnn`. Newer `.pkl` weights don't need this.
- **`--designed_chains` wants a JSON list of letter strings:** `'["B"]'`. Bare `B` or bare `1` is rejected (`chain-id strings, got <class 'int'>`).

## OOM / hardware limits

| GPU class | Behavior |
|---|---|
| 24 GB | Works with `low_memory_mode=true` AND `expandable_segments:True`. Without both, OOMs at batch 7. |
| 48 GB | Fine for default config |
| 80+ GB | Fine for everything; can drop `low_memory_mode` |

RFD3 design is more memory-friendly than RFD2 because of batch generation, but the fragmentation issue is real on Ampere.

## Common errors

- **`Invalid checkpoint: rfd3`** → `FOUNDRY_CHECKPOINT_DIRS` missing or singular-S variant. See `troubleshooting.md` §5.3.
- **`chain-id strings, got <class 'int'>`** → `--designed_chains` not passed as JSON list. See §5.4.
- **MPNN sequences not pairing with backbones** → forgot `--is_legacy_weights True`.
- **OOM at batch 7 on 24 GB** → missing `expandable_segments`. See §4.2.
- **`Found N existing example IDs` then re-runs everything** → RFD3's `skip_existing` isn't real resume. See §6.5. Move completed files aside if interrupted mid-run.
- **Reinit warnings from `foundry.utils.weights`** → benign, the v0.1.9 checkpoint wasn't trained with the chunked low-memory code path. Outputs verify clean. See `troubleshooting.md` §7.

## Wedge / kill criteria

- **No new `.cif.gz` after kernel-warmup + 30 min** — wedge.
- **OOM on third+ batch despite `expandable_segments`** — memory pressure from something else on the node; ask orchestrator.
- **Wall exceeds 2× initial estimate** — kill.

## Post-processing MPNN output

MPNN writes 1 `.fa` per backbone, each containing N sequences with `sequence_recovery=...` in the header. Don't try to "fix" the file format yourself; the orchestrator's evaluator does the post-processing:

1. Per `.fa`, pick the sequence with highest `sequence_recovery`.
2. Strip the target prefix from the picked sequence — first `len(target_seq)` characters are the target.
3. The remainder is the designed binder.

Workers can either leave `.fa` files raw (recommended for consistency) or pre-process if the campaign convention demands. Either way, include the raw `.fa` in the tarball for traceability.

## Packaging recipe

```bash
cd ~/runs/<TARGET>-<machine>-rfd3/
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_RFD3_<machine>.tar.gz \
    out_dir/ \
    mpnn_out/ \
    inputs/<TARGET>.json \
    run.sh foundry.log *.out
```

For `_final`:

```bash
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_RFD3_<machine>_final.tar.gz \
    out_dir/ \
    mpnn_out/ \
    inputs/<TARGET>.json
```

(RFD3 output is typically not huge; full and `_final` are often the same.)

## Reporting back

```markdown
🔄 → ✅ | SLURM <id> done. <n_designs> backbones generated, <m> MPNN sequences total.
Output format: .cif.gz (target = chain A, binder = chain B).
Top metrics from .json: <n_chainbreaks min>, <n_clashing min>.
MPNN sequence_recovery range: <x>-<y>.
Wall: <h> on <GPU>. Compute: <GPU-h>.
Packaged: <TARGET>_RFD3_<machine>.tar.gz (<size>).
```

**Note about cross-validation:** RFD3 + MPNN are independent of Boltz-2, Protenix, and AF3 — RFD3 outputs are among the cleanest signals in the BindMaster pool for cross-engine refold consensus. See `bindmaster-orchestrator/references/tools/README.md`.
