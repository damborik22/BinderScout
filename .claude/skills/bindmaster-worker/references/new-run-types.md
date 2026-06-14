# New run types (extension to the worker skill)

Execution playbooks for the BindMaster2-graft capabilities the worker now runs, beyond the seven
design tools. Each is driven by a `binder-compare …` spec from the orchestrator/evaluator.

## 1. Rosetta interface energy (for `affinity`, Part N)
The only one fully pinned today — PyRosetta lives in the **BindCraft** env on every platform we run
BindCraft on (x86_64 **and** aarch64 / Spark):
```bash
conda run -n BindCraft python Evaluator/scripts/interface_energy.py \
    --structures-dir runs/<name>/structures --interface B_A -o interface_energy.csv
```
- `--interface <binder>_<target>` chain ids; **B_A** = RFD3 convention (binder B, target A) — verify
  against your structures (a wrong spec silently mis-scores).
- One row per PDB (`design_id, interface_dG, interface_dSASA`); a bad structure is skipped, not fatal.
- `binder-compare affinity --run-rosetta` calls this for you; run it standalone for batching/caching.

## 2. Monomer refold (for `monomer` QC)
Refold each binder **alone** (no target) with a refold engine, emitting per-design PDBs whose
**stem matches** the complex PDB stem (the `monomer` subcommand pairs by stem):
```bash
# binder-only sequences → PDBs in runs/<name>/monomer/<design_id>.pdb
binder-compare refold-esmfold2 --sequences binders.fasta --target-seq "" --output-dir runs/<name>/monomer …
```
`TODO:` confirm the binder-only invocation (no target chain) for each engine + the id→filename convention.

## 3. Maturation runs (for `mature`)
Inputs = the `maturation_round.json` from `binder-compare mature` (strategy + parent ids):
- **partial_diffusion** → RFD3 with a **partial** noise schedule seeded from each parent backbone
  (re-noise a fraction, re-denoise) to explore *local* backbone space, then ProteinMPNN → refold.
  `TODO:` pin the RFD3 partial-diffusion flag(s) (noise scale / partial-T) + the seed-from-parent input.
- **mpnn_redesign** → ProteinMPNN best-of-N on the **fixed** parent backbones, then refold.
  Reuse the RFD3-MPNN recipe in `tools/rfd3.md` (the `mpnn` console-script, `--is_legacy_weights`).
- **mutation_scan** → enumerate point mutants of the single best parent; refold + score.

Each round's outputs re-enter the normal flow: package → `autosize` gate → `evaluator`.

## General
- Use `$CONDA_PREFIX/bin/<tool>` in batch (the `bin/` wrappers fail non-interactively — learnings #9).
- These are short, eval-host-local jobs (Rosetta, monomer) or standard design jobs (maturation) —
  no new cluster patterns beyond the existing tool playbooks.
