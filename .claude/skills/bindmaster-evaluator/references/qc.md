# Quality control — monomer validation

Does the binder hold its fold *without* the target? Refold each binder **alone** and compare it to
its conformation in the complex by Cα RMSD. A large RMSD means the fold is target-stabilized
(context-dependent) — it may not express/behave as a standalone protein.

## Command

```bash
# 1. refold the binders alone (a GPU step), matched by id to the complex PDBs
# 2. compare:
binder-compare monomer --complex-dir runs/<name>/structures \
    --monomer-dir runs/<name>/monomer --binder-chain B -o monomer.csv
```
Output per design: `monomer_rmsd`, `fold_robust` (RMSD ≤ 3.0 Å).

## How to act
- **Robust (≤ 3 Å):** fold is self-contained — fine.
- **Borderline (3–5 Å):** keep but flag; verify the monomer fold's pLDDT was decent (a bad monomer
  prediction can inflate RMSD — not necessarily a real risk).
- **Context-dependent (> 5 Å):** down-weight in the shortlist; if it's otherwise a top binder,
  prefer **maturing** it (`bindmaster-wetlab` → `mature` MPNN-redesign to stabilize the fold) over
  shipping it to the lab as-is.

## Caveats
- Length-aware: longer binders tolerate slightly higher RMSD; a 3 Å cut is calibrated for typical
  ~60–120 aa binders. `TODO:` per-length thresholds once we have data.
- This QC is independent of the binding metrics — a design can rank well on two-stage yet fail
  monomer QC. Run it on the shortlist before wet-lab handoff.

## Fold sanity BEFORE you trust any metric — radius of gyration

Monomer RMSD assumes the binder is a fold at all. An extended coil finishes with exit 0, a
populated `sequences.csv` and confident-looking native metrics; a 304-backbone RFD3 round shipped
exactly that way and nothing caught it. So gate on GEOMETRY FIRST — before MPNN, before any
refold — with `tools/rfd3_gate.py` (reads chain-B Cα from mmCIF, `.cif` / `.cif.gz`):

```bash
# both the .cif.gz and the sidecar .json live in rfd3/diffusion/ — an `rfd3/*.json`
# glob hits settings.json instead and the gate only reports "cannot verify" (exit 1)
python3 tools/rfd3_gate.py geometry 'runs/<name>/rfd3/diffusion/*.cif.gz'   # Rg/expected + contacts
python3 tools/rfd3_gate.py origin   'runs/<name>/rfd3/diffusion/*.json'     # RFD3 only: |fixed_com| > 5 Å
```
- **`Rg / (2.2 · N^0.38)` must be ≤ 1.45** — the denominator is the expected compact Rg (Å) of an
  N-residue globule. The broken coil pool sat at **1.90**.
- **Long-range Cα contacts (|i−j| ≥ 9, within 8 Å) ≥ 0.80 per residue.** Broken pool: **0.28**.
- Both must hold or the gate exits non-zero. If it fails these are coils — **do NOT run MPNN or a
  refold on them.** Pro/Gly-rich MPNN sequences are a *symptom* of a bad backbone, not an MPNN
  setting to tune.
