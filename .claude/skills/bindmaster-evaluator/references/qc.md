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
