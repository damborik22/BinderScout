# BindMaster 2 grafts

Capabilities ported from the (abandoned) [BindMaster 2](https://github.com/damborik22/BindMaster2)
agentic concept onto BinderScout's evaluator. We grafted the **orchestration/lifecycle**
capabilities BinderScout lacked — *not* BM2's agent framework (redundant with our Claude Code
skills + the `autosize` controller) and *not* its evaluator (ours is more advanced: two-stage
ranking, AF3 + ESMFold2 + Protenix, `chain_iptm_interface`, RFD3).

Each graft is a **pure, unit-tested core** in `Evaluator/binder_comparison/comparison/` plus a
thin `binder-compare` subcommand. Heavy steps (GPU refold, Rosetta) are delegated to the
existing tool/refold launchers, exactly like the `autosize` loop.

| # | Subcommand | Core module | What it does | Heavy step (delegated) |
|---|---|---|---|---|
| 1 | `wetlab` | `wetlab.py` | Ranked designs → Markdown wet-lab plan (synthesis, expression, budget-aware assays, FASTA + biophysics) | none (stdlib only) |
| 2 | `mature` | `maturation.py` | Best affinity (Kd or proxy) → next round: partial-diffusion / MPNN-redesign / mutation-scan / done + parents | RFD3 partial-diffusion / ProteinMPNN |
| 3 | `monomer` | `monomer.py` | Binder-alone vs in-complex Cα RMSD; flag context-dependent (target-stabilized) folds | binder-only refold (ESMFold2/Boltz-2) |
| 4 | `affinity` | `affinity.py` | Rank affinity **among** binders via `ipsae_min × \|dG/dSASA\|` (Part N) | Rosetta InterfaceAnalyzer in the **BindCraft** env |
| 5 | `analyze-target` | `target_analysis.py` | Advisory 0–1 difficulty + autosize/length/hotspot suggestions from a PDB | none (Cα-density SASA proxy) |

## The closed campaign loop they enable

Together with the existing `autosize` controller, the grafts complete a full loop:

```
analyze-target → (suggest n_target / tier / tools)
   → autosize  → (design → ESMFold2 gate → decide → repeat)
      → report → (two-stage cross-engine ranking)
         → affinity → (Part N: rank affinity among the binders)
            → monomer → (drop context-dependent folds)
               → wetlab → (experimental plan + FASTA)
                  → [wet lab]
                     → mature → (next computational round) → autosize …
```

## Notes & caveats

- **Rosetta is not x86-gated.** `affinity` runs `Evaluator/scripts/interface_energy.py` via
  `conda run -n BindCraft` — PyRosetta ships in the BindCraft env on every platform we run
  BindCraft on, including aarch64 / DGX Spark.
- **`analyze-target` difficulty is heuristic/advisory.** BM2 never pinned a formula; ours is
  explicit (length 0.45 + disorder 0.25 + flat-surface 0.30, disorder not yet modelled) and
  meant to *seed* a campaign, not replace judgement. Review before committing GPU time.
- **`mature` thresholds** (weak >500 nM, moderate >50 nM) follow BM2 and are CLI-overridable;
  pre-experimentally it can run on the `affinity` composite as a proxy instead of real Kd.
- **`wetlab` vendor/cost** are lab-overridable defaults, not authority.
- What we deliberately did **not** take: BM2's RFAA (we use RFD3), AF2 (we use AF3 + ESMFold2),
  and its in-code agent runtime + state machine (covered by our skills + `autosize`).
