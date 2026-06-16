# Affinity among binders (Part N)

Two-stage ranking separates binders from non-binders; it does **not** order affinity. The affinity
score is the interface energy *density*, with `ipsae_min` used as a binder **gate** (not a multiplier):

```
affinity_energy_density = |interface_dG / interface_dSASA|     # the rank
passes_affinity_gate    = ipsae_min ≥ 0.61                     # the cull
```

Rank survivors by `affinity_energy_density` (higher = tighter predicted affinity) among the
gated-in binders. **Why not `ipsae_min × |dG/dSASA|`:** on the Adaptyv 4-target benchmark
(experimental Kd) `ipsae_min` carries no affinity signal among binders (Spearman vs log10 Kd ≈ 0,
sign flips per target), so multiplying it in only adds variance — gate, don't weight. Run this
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
  or to feed `bindmaster-wetlab`'s maturation (`affinity_energy_density` is the pre-experimental
  affinity proxy when there's no Kd yet).
- **No:** the whole pool (too slow), or a single-engine pool where ranking is dominated by bias.

## Caveats
- An *interface-energy density* proxy, not a measured Kd — calibrate against any real data you have.
- ΔG depends on the interface chain spec being right; a wrong `--interface` silently mis-scores.
- `TODO:` PRODIGY fallback wiring if a host lacks PyRosetta (BindCraft env should always have it).
