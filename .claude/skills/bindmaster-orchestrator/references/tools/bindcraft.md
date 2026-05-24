# BindCraft

**Engine:** AF2 backpropagation hallucination → ProteinMPNN sequence design → PyRosetta filtering. Turnkey three-stage pipeline with **built-in cross-validation**: AF2-ptm and AF2-multimer alternate as design vs. validation oracle (whichever is used for design, the other validates).
**Role:** design
**Status:** stable (the well-tuned reference in BindMaster)
**Environment:** conda env `BindCraft` (Python 3.10); requires ~5.3 GB AF2 weights, ≥32 GB GPU memory recommended

## Principle

BindCraft is the direct descendant of ColabDesign / RSO hallucination: it backpropagates through AF2 to optimize a sequence whose predicted structure binds the target. The novelty vs. raw RSO is the three-stage pipeline that bolts an extensive filter battery onto the design step. After hallucination converges, ProteinMPNN redesigns the sequence for the trajectory's backbone (with the interface optionally fixed), then PyRosetta computes a battery of physics-based interface metrics — Rosetta ΔG, shape complementarity, packstat, ΔSASA, interface H-bond counts, unsatisfied buried H-bonds. Designs are filtered against thresholds (`default_filters.json`), and the script self-monitors acceptance rate — if too few trajectories pass, it terminates so weights can be retuned.

Because the AF2 model used for design is *not* the same one used to validate, BindCraft does its own internal cross-validation step. This is the most important architectural difference vs. Mosaic.

## Strengths

- **Well-tuned defaults.** The reference "press button, get binders" workflow. Mosaic's own README cites it as the well-tested baseline.
- **Internal cross-validation.** AF2-ptm ↔ AF2-multimer hand-off catches designs that overfit one model. No other tool in the BindMaster stack does this natively.
- **Comprehensive physics filters.** PyRosetta computes ΔG, shape complementarity, packstat, ΔSASA, interface H-bond accounting — signals no other design tool exposes natively. These are unique features in the evaluator's pooled CSV.
- **Acceptance-rate auto-stop.** Terminates if filter pass-rate drops below threshold, preventing wasted GPU on a mistuned weight set.
- **Mature lineage.** ColabDesign, ProteinMPNN, PyRosetta — all battle-tested.

## Weaknesses

- **iPTM is not an affinity proxy.** BindCraft itself notes iPTM is a binary binding predictor, not an affinity predictor (and the BindMaster CLAUDE.md flags iPTM as gameable across tools). BindCraft's internal iPTM ranking is its native within-tool signal; for cross-method comparison in the pooled BindMaster pool, the evaluator adds `ipsae_min` as the common comparator.
- **AF2-only.** No Boltz-2, no AF3-family models. Strong on protein-protein interfaces only — no native support for DNA, RNA, or small-molecule targets.
- **Hydrophilic interfaces underperform.** Acknowledged in the README.
- **Compute cost.** Needs hundreds to thousands of trajectories for difficult targets. Trajectory generation is slow vs. diffusion-based approaches.
- **No backbone diversity.** Hallucination converges; output backbones cluster tightly.
- **"Squashed" trajectories.** A documented failure mode — AF2-multimer is sensitive to sequence input. Detected and discarded automatically but inflates effective trajectory cost.
- **PyRosetta license.** Required for commercial use. Academic use is free.

## Pick when

- New, untuned target where you want a reliable default before reaching for harder tools.
- You need the Rosetta interface metrics (ΔG, shape complementarity, packstat, unsat-Hbond counts) for filtering — only BindCraft surfaces these natively.
- Target is protein with a clear epitope; specifying `target_hotspot_residues` works well.
- You have ≥32 GB GPU and time for thousands of trajectories.
- You want internal AF2 cross-validation as a first-pass filter before the BindMaster evaluator.

## Avoid when

- Target is DNA / RNA / small-molecule → **RFD3** (all-atom) or **PXDesign** (Protenix).
- You need backbone diversity → **RFD3** or **BoltzGen** (diffusion-sampled backbones).
- Fast exploratory iterations on a difficult target → BindCraft's trajectory budget is too high for rapid iteration loops; use **Mosaic** or **Protein-Hunter** for that.
- Modern model ranking is required → BindCraft is AF2-only; use **Mosaic** if you want Boltz-2-driven design.

## Outputs the evaluator parses

BindCraft's per-design CSV with the full AF2 + Rosetta metric battery:

- **AF2 confidence:** `pLDDT`, `pTM`, `i_pTM`, `pAE`, `i_pAE`, `i_pLDDT`, `ss_pLDDT`
- **Rosetta interface:** `Binder_Energy_Score`, `Surface_Hydrophobicity`, `ShapeComplementarity`, `PackStat`, `dG`, `dSASA`, `dG/dSASA`, `Interface_SASA_%`, `Interface_Hydrophobicity`, `n_InterfaceResidues`, `n_InterfaceHbonds`, `InterfaceHbondsPercentage`, `n_InterfaceUnsatHbonds`, `InterfaceUnsatHbondsPercentage`
- **Secondary structure:** `Interface_Helix%`, `Interface_BetaSheet%`, `Interface_Loop%`, `Binder_Helix%`, `Binder_BetaSheet%`, `Binder_Loop%`, `InterfaceAAs`
- **RMSD / cross-val:** `HotspotRMSD`, `Target_RMSD`, `Binder_pLDDT`, `Binder_pTM`, `Binder_pAE`, `Binder_RMSD`

**Normalization note:** BindCraft normalizes AF2 metrics differently — pAE is divided by `n/31`. The evaluator must un-normalize before comparing with raw PAE from Boltz-2 / Protenix / AF3.

**After evaluator re-fold:** `.cif` + PAE `.npz` → `bt_ipsae`, `tb_ipsae`, `ipsae_min`. Both BindCraft's native ranking (by iPTM, with the full Rosetta + AF2 metric battery) and the evaluator's cross-method `ipsae_min` are preserved in `summary.csv`. The evaluator provides a method-agnostic comparator over the merged design pool — it sits alongside BindCraft's internal metrics, not above them.

## Key knobs

| Knob | File | Typical | Notes |
|---|---|---|---|
| `target_hotspot_residues` | `settings_target/*.json` | e.g. `A30-50` or `null` | Critical for difficult targets; `null` lets AF2 choose. |
| `lengths` | settings_target | `[55, 150]` | Range of binder lengths to design. |
| `number_of_final_designs` | settings_target | 100 | Filter-passing count target; script stops when reached. |
| `design_algorithm` | advanced | `4stage` | 2/3/4-stage logits ladder, or `greedy` / `mcmc`. 4stage is default and most extensive. |
| `use_multimer_design` | advanced | `True` | AF2-multimer for design, AF2-ptm for validation. Flip for the alternative. |
| `num_recycles_design` / `num_recycles_validation` | advanced | 1 / 3 | Recycles per AF2 pass. |
| `soft` / `temporary` / `hard` / `greedy iterations` | advanced | 75/100/5/15 | Design schedule across the logits→softmax→one-hot ladder. |
| `weights_iptm` / `weights_plddt` / `weights_pae_inter` / `weights_con_inter` / `weights_helicity` / `weights_rg` | advanced | per-target | Main tuning surface — shape what the hallucination optimizes for. |
| `mpnn_weights` | advanced | `original` or `soluble` | Soluble MPNN biases against surface hydrophobics. |
| `num_seqs` / `max_mpnn_sequences` | advanced | 20 / 2 | MPNN samples per trajectory; top kept. |
| `sampling_temp` | advanced | 0.1 | MPNN sampling temperature; 0 = argmax, >>1 = random. |
| `backbone_noise` | advanced | 0.00–0.02 | MPNN backbone noise. |
| `predict_initial_guess` | advanced | `False` | Bias prediction by providing binder atom positions; recommended if designs fail post-MPNN. |
| `predict_bigbang` | advanced | `False` | Atom position bias in structure module; recommended for large complexes (>600 AA). |
| `rm_template_seq_design` / `rm_template_sc_design` | advanced | `False` | Remove target template sequence / sidechains for design (increases target flexibility). |
| `optimise_beta` | advanced | `True` | Extra iterations if beta-sheet trajectory detected. |
| Filter thresholds | `settings_filters/*.json` | defaults | Shape of accepted population; loosen if acceptance rate is too low. |
| `acceptance_rate` / `start_monitoring` | advanced | 0.05 / 100 | Auto-stop guard against mistuned weights. |

## Sources

- Paper: Pacesa et al. 2024, "BindCraft: one-shot design of functional protein binders," bioRxiv 2024.09.30.615802
- Repo: https://github.com/martinpacesa/BindCraft
- Wiki: https://github.com/martinpacesa/BindCraft/wiki
- Lineage: ColabDesign (sokrypton/ColabDesign), ProteinMPNN (dauparas/ProteinMPNN), PyRosetta
- BindMaster note: iPTM is flagged gameable across tools in CLAUDE.md `Critical domain facts`; the evaluator's `ipsae_min` is the cross-method comparator.
