# Protein-Hunter

**Engine:** Iterative structure-hallucination-within-diffusion framework — uses AF3-style structure predictors (Boltz-1/2 or Chai-1) as the hallucination oracle. Lightweight, fine-tuning-free; starts from an all-X (unknown amino acid) sequence and iteratively cycles structure prediction → sequence sampling until convergence. Two backends in the repo: `boltz_ph` (Boltz edition, used by BindMaster) and `chai_ph` (Chai edition, under active development). Optional AF3 cross-validation.
**Role:** design
**Status:** in active integration (no automated configurator yet in BindMaster; run scripts written by hand from `bindmaster_examples/run_protein_hunter.sh.template`)
**Environment:** conda env `bindmaster_protein_hunter`; requires Boltz-2 cache populated at `~/.boltz/`

## Principle

Protein-Hunter's central insight is that AF3-style structure predictors can be coerced into *hallucinating* high-quality folded structures even for sequences that wouldn't naturally adopt those conformations — the same way image diffusion models hallucinate plausible images beyond their training distribution. By starting from an "all-X" sequence (every residue is the unknown token) and letting the diffusion-based structure predictor denoise toward a well-folded backbone, you get a fold sampled from the predictor's learned prior. The pipeline then iteratively (a) samples sequences consistent with the hallucinated structure and (b) re-predicts the structure with the new sequence, converging on a self-consistent design.

This is a different paradigm from BindCraft (gradient backprop through AF2) and Mosaic (gradient backprop through Boltz-2) — Protein-Hunter doesn't differentiate through the predictor. It uses iterative sample-and-repredict cycles, which is computationally cheap per step and works with any predictor (no JAX requirement). The trade-off: convergence is empirical, not gradient-driven.

`percent_X` controls how much of the initial sequence is the X token vs. random amino acids:
- `--percent_X 100` — fully de novo exploration (all X)
- `--percent_X 50` — mix of X and random AAs (broader sampling, more diversity)
- `--percent_X 0` — fully specified initial sequence (refinement / contact specification mode)

Lower `percent_X` → more constrained search → tighter, more structured outputs. Higher → more diversity but risk of disconnected / floating structures.

## Strengths

- **Lightweight.** No fine-tuning of the underlying predictor. Inference-only, fast per cycle. Authors position it as comparable to AF3 in silico success rate at much lower cost.
- **Multi-modal.** Native support for protein-protein, multimer, cyclic peptide, small-molecule binder (CCD code or SMILES), DNA, RNA, and heterogeneous targets (protein + ligand + template).
- **Predictor-agnostic design loop.** Both Boltz and Chai backends; AF3 used optionally for cross-validation only. Decouples design from any single predictor's biases.
- **Contact specification.** `--contact_residues` lets the user specify interface residues on the target; `--no_potentials False` turns on contact potentials in the diffusion guidance.
- **Alanine bias controls.** `--alanine_bias` discourages alanine accumulation during sampling (common diffusion failure mode).
- **Cyclic peptide design native.** `--cyclic` flag, used the same way as linear binder design.
- **Multimer targets.** Separate chain sequences with `:` in `--protein_seqs`.
- **Trajectory visualization.** LogMD + py2Dmol integration (developed by Sergey Ovchinnikov) — useful for debugging hallucination convergence.
- **MIT licensed.**

## Weaknesses

- **Experimental software, no automated runner.** Per BindMaster CLAUDE.md, the configurator does not yet generate Protein-Hunter run scripts; written by hand from the template.
- **No experimental wet-lab validation in the paper.** Authors flag: "EXPERIMENTAL SOFTWARE: This pipeline is under active development and has NOT been experimentally validated in laboratory settings."
- **CLAUDE.md runtime gotchas** — each one bit during the CALCA run:
  - `--msa_mode` valid values are `single` or `mmseqs`, **NOT** `single_sequence`. The literal `single_sequence` raises `argparse: invalid choice`.
  - Boltz-2 cache must live at `~/.boltz/` with three things: `boltz2_conf.ckpt` (~2.3 GB), `boltz2_aff.ckpt` (~2.1 GB), and a populated `mols/` directory (~45k .pkl files). Missing `mols/ALA.pkl` → `ValueError: CCD component ALA not found!` at startup.
  - `download_boltz2` requires a **positional** `cache: pathlib.Path` argument. Bootstrap with `python -c "from boltz.main import download_boltz2; from pathlib import Path; download_boltz2(cache=Path.home()/'.boltz')"`. Passing a `str` silently no-ops on some versions.
  - `pyrosetta-installer` ≥ 0.3 renamed `download_pyrosetta` → `install_pyrosetta`. BindMaster's `install/install.sh` was updated in commit `7642942`; fresh manual envs need the new name.
  - Output layout creates a `{name}/` subdirectory under `--save_dir`. With `--save_dir runs/CALCA_helix/protein_hunter --name CALCA_helix`, actual CSVs land at `protein_hunter/CALCA_helix/summary_*.csv`. Path printed twice in the run banner — confusing but correct.
  - `summary_high_iptm.csv` row count > `num_designs` is normal: every cycle crossing `--high_iptm_threshold` gets a row, so a 7-cycle run with several passing cycles produces more rows than designs (CALCA: 133 rows from 100 designs).
  - "No structure was generated for run N (no eligible best design …)" is **not** a failure — none of the N cycles produced a sequence under the `--percent_X` alanine cap. Final-run row may be absent from `summary_all_runs.csv`.
- **AF3 cross-validation is heavy.** Requires AF3 Docker, database paths, HMMER. Off by default in BindMaster usage.
- **Sensitive to `percent_X`.** Too high → floating / disconnected structures; too low → narrow design space. Needs per-target calibration.

## Pick when

- Multi-modal target — protein, cyclic peptide, small molecule (CCD/SMILES), DNA, RNA, or heterogeneous combo. Protein-Hunter's YAML/CLI is the most flexible in the design pool.
- Want a *non-gradient* design loop — useful if you can't afford JAX overhead or want an architecturally independent design path next to BindCraft/Mosaic.
- Cyclic peptide design — the simplest of all tools for this case.
- Want to specify exact contact residues on the target (`--contact_residues`).
- Quick iteration with a few designs at a time — pipeline is lightweight and per-design wall time is low.

## Avoid when

- You need experimentally validated provenance — Protein-Hunter is explicitly flagged as unvalidated in vivo by the authors.
- You need a turnkey, configurator-managed run — BindMaster doesn't auto-generate run scripts yet.
- You need stable cross-model validation — same-model self-judging applies (the Boltz-2 used for design is the same one used by the BindMaster evaluator's default refold).
- You don't want to manually populate `~/.boltz/` and verify the `mols/` directory before first run.

## Outputs the evaluator parses

**Output directory** (under `--save_dir/{name}/`):

- `high_iptm_yaml/` — designs passing the `--high_iptm_threshold` and `< 20%` alanine. **Default filter.**
- `high_iptm_cif/` — CIF structures for the high-iPTM designs
- `summary_high_iptm.csv` — metrics for the filtered set
- `summary_all_runs.csv` — full per-cycle metrics (browse here for all designs)
- `03_af_pdb_success/` — AF3-validated structures (only if `--use_alphafold3_validation` was set)

**Native metrics:**

- `iptm` per cycle (Boltz-2 native)
- `plddt`, `pae_*` (Boltz-2 native, `[binder|target]` ordering)
- `sequence_recovery` (per inverse-folding cycle)
- `alanine_fraction` (composition guard)
- Cycle number, design ID, name

**Evaluator step (BindMaster):**

Protein-Hunter outputs feed the standard BindMaster evaluator — Boltz-2 refold with uniform 10 Å iPSAE producing `bt_ipsae`, `tb_ipsae`, `ipsae_min` (column prefix `boltz_*`). Protein-Hunter's native iPTM-thresholded selection and per-cycle metrics are preserved alongside the evaluator's cross-method comparator; the evaluator is the unbiased judge across tools, Protein-Hunter's selection is its own native ranking.

## Key knobs (Boltz edition — `boltz_ph/design.py`)

| Knob | Typical | Notes |
|---|---|---|
| `--num_designs` | 50–500 | Number of independent design jobs. |
| `--num_cycles` | 5–7 | Iterative refinement cycles per design. More = more refinement, more cost. |
| `--protein_seqs` | target sequence | Use `:` to separate chains for multimer targets. |
| `--ligand_ccd` | e.g. `SAM` | CCD code for small-molecule target. Mutually exclusive with `--ligand_smiles`. |
| `--nucleic_seq` / `--nucleic_type` | e.g. `AGAGAGAGA` / `rna` | DNA/RNA targets. |
| `--min_protein_length` / `--max_protein_length` | 90 / 150 (protein) or 10 / 20 (cyclic peptide) | Binder length range. |
| `--percent_X` | 0–100 | Fraction of unknown-AA tokens in initial sequence. 100 = fully de novo, 0 = refinement. |
| `--high_iptm_threshold` | 0.7 (protein), 0.8 (cyclic peptide) | Cycles below this aren't kept. |
| `--msa_mode` | `single` or `mmseqs` | **NOT** `single_sequence` — that's invalid. `single` is no-MSA (fastest), `mmseqs` calls ColabFold server. |
| `--contact_residues` | e.g. `2,3,10` | Specify interface residues on target. Requires `--no_potentials False`. |
| `--no_potentials` | `True` (default) | Set to `False` to enable contact-residue potentials. |
| `--alanine_bias` | off | Discourages alanine accumulation during diffusion. Useful when `--percent_X` is high. |
| `--cyclic` | off | Cyclic peptide design mode. |
| `--use_msa_for_af3` | off (BindMaster default) | Use MSA when AF3 cross-validation enabled. |
| `--use_alphafold3_validation` | off (BindMaster default) | Enable AF3 cross-validation. Requires AF3 Docker, database, HMMER. |
| `--alphafold_dir` / `--af3_docker_name` / `--af3_database_settings` / `--af3_hmmer_path` | required for AF3 validation | Paths for AF3 integration. |
| `--save_dir` / `--name` | per-run | Output lands under `{save_dir}/{name}/` (subdirectory under save_dir). |
| `--plot` | on (recommended) | Generate diagnostic plots. |
| `--gpu_id` | 0+ | Single GPU. |

## Sources

- Paper: Cho et al. 2025, "Protein Hunter: exploiting structure hallucination within diffusion for protein design," bioRxiv 2025.10.10.681530v2
- Repo: https://github.com/yehlincho/Protein-Hunter
- Authors: Yehlin Cho, Griffin Rangel, Gaurav Bhardwaj, Sergey Ovchinnikov
- Online platform: Tamarind Bio (https://www.tamarind.bio/tools/protein-hunter)
- License: MIT
- Boltz dependency: https://github.com/jwohlwend/boltz (Boltz-1/2 weights at `~/.boltz/`)
- Chai dependency (chai edition): https://github.com/chaidiscovery/chai-lab
- Contact: yehlin@mit.edu
