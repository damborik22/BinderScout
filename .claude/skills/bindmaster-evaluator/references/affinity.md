# Affinity among binders (Part N)

Two-stage ranking separates binders from non-binders; it does **not** order affinity. The composite
that does (BindMaster 2 / Overath 2025 best single affinity predictor) is:

```
affinity_composite = ipsae_min × |interface_dG / interface_dSASA|
```

interface confidence × interface energy *density* — higher = tighter predicted affinity. Run it
**only on the two-stage shortlist** (the survivors worth wet-lab time), not the whole pool.

## Command

```bash
binder-compare affinity --metrics report/metrics.csv \
    --structures-dir runs/<name>/structures --run-rosetta --interface B_A -o affinity.csv
```
- ΔG / ΔSASA come from **Rosetta InterfaceAnalyzer**, run via `conda run -n BindCraft` — PyRosetta
  is in the BindCraft env on **every** BindCraft platform incl. aarch64 / Spark (NOT x86-gated).
- `--interface B_A` = binder_target chains (RFD3 convention is binder B, target A — check yours).
- Or supply a precomputed `--energy interface_energy.csv` (skip `--run-rosetta`).

## When is it worth the Rosetta cost?
- **Yes:** you have a two-stage shortlist (tens of designs) and need to pick the tightest for SPR,
  or to feed `bindmaster-wetlab`'s maturation (the composite is the pre-experimental affinity proxy
  when there's no Kd yet).
- **No:** the whole pool (too slow), or a single-engine pool where ranking is dominated by bias.

## Caveats
- A *structure-confidence × energy* proxy, not a measured Kd — calibrate against any real data you have.
- ΔG depends on the interface chain spec being right; a wrong `--interface` silently mis-scores.
- `TODO:` PRODIGY fallback wiring if a host lacks PyRosetta (BindCraft env should always have it).
