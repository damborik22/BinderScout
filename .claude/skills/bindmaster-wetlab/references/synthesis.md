# Gene synthesis & constructs

The `wetlab` subcommand emits, per design: an **E. coli codon-optimized** gene
(`comparison/wetlab.codon_optimize` — one high-expression codon per residue + stop), a **tag**
(His6-TEV default), and **biophysics** (`sequence_properties`: MW, pI, ε₂₈₀, GRAVY, aromatic
fraction) for the order sheet + downstream concentration math.

## Construct defaults (lab-overridable)
- **Expression host:** E. coli BL21(DE3) for most de novo binders (small, no glycosylation needed).
- **Tag:** His6-TEV (IMAC purification + cleavable). Swap per workflow.
- **Vendor / cost:** placeholder defaults (e.g. Twist, ~$/bp) — **not authority**; the lab sets these.

## Read the biophysics before ordering
- **pI extremes** (very low/high) → buffer/IEX implications; flag designs near the working pH.
- **High GRAVY / large hydrophobic content** → solubility/aggregation risk (cf. the binder-side
  hydrophobicity note in target-analyst `interaction-sites.md`); consider a solubility tag (MBP/SUMO)
  or down-rank.
- **ε₂₈₀ = 0** (no Trp/Tyr) → can't quantify by A280; note an alternative (BCA) or add a Trp.

## Expression method (`WetLabConfig.expression`)
- **`e_coli`** (default) — BL21(DE3), IPTG induction, 18 °C overnight for soluble folding.
- **`cell_free`** — cell-free protein synthesis (E. coli lysate / PURE): transformation-free,
  ~hours to protein, parallel-friendly → ideal for **screening many designs fast** before scaling
  the soluble winners into cells. The plan's section 2 switches on this flag.

## When E. coli isn't right
- Disulfide-rich / glycosylated / large multidomain binders → mammalian (HEK/Expi) or yeast +
  a signal peptide for secretion. `TODO:` mammalian codon table + secretion-tag recipe.

## Caveat
The codon table is a simple max-frequency back-translation — fine for ordering, but a vendor's own
optimizer (avoiding repeats, hairpins, restriction sites) is preferable for the final order.
