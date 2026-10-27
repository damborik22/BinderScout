# What these pins are evidence for

Captured **2026-10-27** from the installation on one x86_64 box (RTX 3090, 24 GB,
driver 580.159.03), during a full PDL1 (`5O45`, 118 aa) design campaign.

"Pinned" is not the same as "proven". This file says which is which, because a pin
recording a version that was never run is a false reassurance, and the whole point
of `install/locks/` is to stop guessing.

## Design tools

| Tool | Lock | Status | Evidence |
|---|---|---|---|
| **BoltzGen** | `BoltzGen.txt` | **ran, produced designs** | 140 output files, exit 0 |
| **BindCraft** | `BindCraft.txt` | **ran, produced designs** | 7 design rows, zero `set_interface` crashes — this is the env that confirmed the BUG-14 PyRosetta fix (it produced **0** rows before it) |
| **PXDesign** | `bindmaster_pxdesign.txt` | **ran, produced designs** | 1000 designs, 7434 files (and 1000 is itself BUG-22: `pxdesign_n_designs` was silently ignored for a 1-design campaign) |
| **Protein-Hunter** | `bindmaster_protein_hunter.txt` | **ran, produced designs** | `summary_high_iptm.csv` + `summary_all_runs.csv` written |
| **Proteina-Complexa** | `proteina-complexa.txt` | **installed; import fixed, generation not yet re-run** | Its campaign run died at stage 1 on BUG-20 (`atomworks` 3.0.0 removed `AtomSelectionStack`). After pinning `atomworks==2.2.1`, `proteinfoundation.utils.pdb_utils` imports cleanly. **A full generate has not been run since.** |
| **RFD3** | `bindmaster_rfd3.txt` | **installed and loading; design not yet re-run** | Its run died at input validation on BUG-21 (the contig said `A1-118`, the target is numbered `A17-134`) — a configurator bug, not an environment fault. Checkpoint registry and ProteinMPNN resolve. **A design run has not been re-attempted.** |
| **Mosaic** | `mosaic.uv.lock` | **ran, produced designs** — after the lock had to be corrected | The first capture of this lock was taken from an install that had never *run* a design, and it pinned `esm2quinox==0.2.0`, which crashes Mosaic's ESM2 prior with `KeyError: 'b'` (BUG-24). Re-pinned to `0.1.0` and re-vendored; Mosaic then optimised with the prior active. **This row is why this file exists** — see the note below. |

## Evaluator

| Env | Lock | Status | Evidence |
|---|---|---|---|
| `binder-eval` | `binder-eval.txt` | **ran** | extraction (1003 sequences) and reporting for the campaign |
| `binder-eval-soluprot` | `binder-eval-soluprot.txt` | **ran** | solubility screen over the pool, pre-refold |
| Boltz-2 refold | `mosaic.uv.lock` | **ran** | `refold-boltz2` over the campaign FASTA |
| `binder-eval-esmfold2` | `binder-eval-esmfold2.txt` | **installed** | default refold engine; not reached in this campaign before capture |
| `binder-eval-af3` | *(none)* | **no lock** | AF3 weights are gated and the env is absent on this box, so there was nothing to capture. The only env without a lock. |

## Not covered by any lock

- **aarch64 / DGX Spark.** Every file here is an x86_64 capture, and `_constraints()`
  refuses to apply them on another architecture: they would pin `+cu121`/`+cu124`
  wheels that have no aarch64 build. `install/install_aarch.sh` deliberately uses
  different versions (torch 2.10.0+cu130, jax 0.6.2). Capture aarch64 locks on an
  aarch64 box; do not reuse these.
- **Conda package versions.** `PIP_CONSTRAINT` and `-c` reach pip only. The conda
  specs in `install.sh` (`python=3.12`, `pytorch>=2.2`, `gcc_linux-64<14`, …) and
  in BindCraft's own installer stay loose. This is the largest remaining unpinned
  surface.
- **`install_aarch.sh` itself** still carries `PXDESIGN_COMMIT="HEAD"` and an
  unpinned conda `pyrosetta` (so the BUG-14 exposure exists there too). Left alone
  rather than guessed at, because it cannot be verified from this machine.

## Two findings that came out of capturing this

1. **A pin can be a lie.** `install.sh` claimed `torch==2.5.1+cu121` for BoltzGen.
   The live env was **torch 2.14.1** from PyPI: the editable `pip install -e BoltzGen`
   on the next line resolves BoltzGen's own `torch>=2.4.1` unconstrained and upgraded
   straight over it. The superseded cu121 wheel's orphaned `nvidia_*_cu12` dist-infos
   were still sitting beside the cu13 set. The installer now names what actually runs.

2. ~~**Two envs need *different* versions of the same package.**~~ **Retracted.**
   This said `bindmaster_rfd3` requires `atomworks==3.0.4` while `proteina-complexa`
   requires `2.2.1`, and offered it as the justification for per-env files. It was
   wrong, and wrong in the way finding 3 describes: 3.0.4 was merely what `rc-foundry`
   had *installed* in an env whose design run had never completed. Once RFD3 actually
   ran, atomworks 3.x aborted it — 3.0.0 moved `extra_fields`/`build_assembly` off
   `parse_atom_array()` and rejects leftover kwargs, which rfd3's pinned code still
   passes. **Both envs need `2.2.1`**, for two unrelated reasons, and `ATOMWORKS_VERSION`
   is now one constant serving both. Per-env files are still right — the envs differ
   in dozens of other packages, and two run different Pythons — but this was not the
   example that showed it.

3. **A lock captured from an un-run install can pin a broken version.** This file's
   first version said Mosaic was "installed; not run in this campaign". That was
   true, and it was the whole exposure: `install/locks/mosaic.uv.lock` recorded
   `esm2quinox==0.2.0` — a version under which Mosaic cannot complete a single
   optimisation step (BUG-24). The env installed cleanly and passed `import mosaic`;
   nothing short of a design run could have caught it. So read the Status column as
   a confidence level, not a formality: **"installed" means the pins are untested,
   and untested pins have now been wrong once.** The remaining "installed"-only rows
   are `binder-eval-esmfold2` (since exercised by a 1003-sequence refold) and the
   Proteina-Complexa / RFD3 re-runs.
