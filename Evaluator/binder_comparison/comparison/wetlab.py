"""Wet-lab handoff — turn ranked designs into an experimental plan.

Grafted from BindMaster 2's Wet-Lab Advisor concept onto BinderScout's evaluator. Pure
functions (no I/O, no external deps beyond the standard library): sequence biophysics,
budget-aware assay selection, E. coli codon optimization, and a Markdown plan builder.

Vendor names and costs are intentionally *not* hardcoded as authoritative — they are
defaults a lab overrides via the CLI config. The biophysics tables are standard
(ProtParam-style) and documented inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Average residue masses (Da, peptide-bonded residue = amino acid − water). ProtParam set.
_RESIDUE_MASS: dict[str, float] = {
    "A": 71.0788, "R": 156.1875, "N": 114.1038, "D": 115.0886, "C": 103.1388,
    "E": 129.1155, "Q": 128.1307, "G": 57.0519, "H": 137.1411, "I": 113.1594,
    "L": 113.1594, "K": 128.1741, "M": 131.1926, "F": 147.1766, "P": 97.1167,
    "S": 87.0782, "T": 101.1051, "W": 186.2132, "Y": 163.1760, "V": 99.1326,
}  # fmt: skip
_WATER = 18.01528

# Kyte-Doolittle hydropathy (for GRAVY).
_KD_HYDROPATHY: dict[str, float] = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "E": -3.5, "Q": -3.5,
    "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
    "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}  # fmt: skip

# pKa values for isoelectric point (EMBOSS-style). N/C termini + ionizable side chains.
_PKA_NTERM, _PKA_CTERM = 8.6, 3.6
_PKA_POS = {"K": 10.5, "R": 12.5, "H": 6.5}  # protonated → positive
_PKA_NEG = {"D": 3.9, "E": 4.1, "C": 8.5, "Y": 10.1}  # deprotonated → negative

_STANDARD_AAS = set(_RESIDUE_MASS)


def sequence_properties(seq: str) -> dict:
    """Return biophysical properties of a protein sequence (ProtParam-style).

    Keys: length, molecular_weight (Da), isoelectric_point, extinction_280 (M⁻¹cm⁻¹,
    reduced Cys), gravy (Kyte-Doolittle mean), aromatic_fraction. Non-standard residues
    are ignored for mass/charge (and counted in ``nonstandard``).
    """
    s = (seq or "").upper().strip()
    residues = [c for c in s if c in _STANDARD_AAS]
    n = len(residues)
    if n == 0:
        return {"length": 0, "molecular_weight": 0.0, "isoelectric_point": 0.0,
                "extinction_280": 0, "gravy": 0.0, "aromatic_fraction": 0.0,
                "nonstandard": len(s)}  # fmt: skip

    counts: dict[str, int] = {}
    for c in residues:
        counts[c] = counts.get(c, 0) + 1

    mw = sum(_RESIDUE_MASS[c] for c in residues) + _WATER
    # Pace/Gill reduced extinction at 280 nm: 5500·Trp + 1490·Tyr.
    extinction = 5500 * counts.get("W", 0) + 1490 * counts.get("Y", 0)
    gravy = sum(_KD_HYDROPATHY[c] for c in residues) / n
    aromatic = sum(counts.get(a, 0) for a in "FWY") / n

    return {
        "length": n,
        "molecular_weight": round(mw, 2),
        "isoelectric_point": round(_isoelectric_point(counts), 2),
        "extinction_280": extinction,
        "gravy": round(gravy, 3),
        "aromatic_fraction": round(aromatic, 3),
        "nonstandard": len(s) - n,
    }


def _net_charge(counts: dict[str, int], ph: float) -> float:
    """Net charge of a chain at a given pH from termini + ionizable side chains."""
    pos = 1.0 / (1.0 + 10 ** (ph - _PKA_NTERM))
    for aa, pka in _PKA_POS.items():
        pos += counts.get(aa, 0) * (1.0 / (1.0 + 10 ** (ph - pka)))
    neg = 1.0 / (1.0 + 10 ** (_PKA_CTERM - ph))
    for aa, pka in _PKA_NEG.items():
        neg += counts.get(aa, 0) * (1.0 / (1.0 + 10 ** (pka - ph)))
    return pos - neg


def _isoelectric_point(counts: dict[str, int]) -> float:
    """pH at which net charge is zero, by bisection over [0, 14]."""
    lo, hi = 0.0, 14.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _net_charge(counts, mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def recommend_assay(n_designs: int, budget_usd: float | None = None) -> dict:
    """Assay panel for the lab's Adaptyv-based workflow.

    Designs are submitted to Adaptyv Bio (express + characterize). BLI gives a quick yes/no plus
    first-pass kinetics on everything submitted; the top hits go to SPR (gold-standard kinetics)
    and FIDA (solution-phase Kd, immobilization-free). Throughput / budget govern *how many*
    designs to submit, not which assay.
    """
    panel = {
        "platform": "Adaptyv Bio — express + characterize the submitted designs",
        "screen": "BLI — quick yes/no binding + first-pass kinetics (all submitted designs)",
        "lead_characterization": [
            "SPR — gold-standard kinetics (kon/koff/KD) on the top hits",
            "FIDA — solution-phase Kd, no immobilization (robust for hard-to-immobilize targets)",
        ],
        "submitting": n_designs,
    }
    if budget_usd is not None:
        panel["budget_usd"] = budget_usd
    return panel


# Most-frequent E. coli codon per amino acid (high-expression bias).
_ECOLI_CODON: dict[str, str] = {
    "A": "GCG", "R": "CGC", "N": "AAC", "D": "GAT", "C": "TGC", "E": "GAA",
    "Q": "CAG", "G": "GGC", "H": "CAT", "I": "ATT", "L": "CTG", "K": "AAA",
    "M": "ATG", "F": "TTT", "P": "CCG", "S": "AGC", "T": "ACC", "W": "TGG",
    "Y": "TAT", "V": "GTG",
}  # fmt: skip


def codon_optimize(aa_seq: str, *, add_stop: bool = True) -> str:
    """Back-translate a protein to an E. coli codon-optimized DNA sequence.

    One most-frequent codon per residue (high-expression bias). Non-standard residues
    raise ValueError. Appends a TAA stop unless ``add_stop=False``.
    """
    s = (aa_seq or "").upper().strip()
    out = []
    for c in s:
        if c not in _ECOLI_CODON:
            raise ValueError(f"cannot codon-optimize non-standard residue {c!r}")
        out.append(_ECOLI_CODON[c])
    dna = "".join(out)
    if add_stop:
        dna += "TAA"
    return dna


@dataclass
class WetLabConfig:
    """Knobs for the plan. Vendor/cost are lab-overridable defaults, not authority."""

    organism: str = "e_coli"
    budget_usd: float | None = None
    top_n: int = 20
    tag: str = "His6-TEV"
    gene_vendor: str = "Twist Bioscience"
    cost_per_gene_usd: float = 0.10  # per bp, rough order-of-magnitude default
    notes: list[str] = field(default_factory=list)


def wetlab_plan_markdown(designs: list[dict], config: WetLabConfig | None = None) -> str:
    """Build a Markdown wet-lab plan from ranked design records.

    Each design dict needs at least ``binder_id`` (or ``id``) and ``sequence``; any extra
    metric columns are surfaced in the design table. Returns the Markdown string.
    """
    cfg = config or WetLabConfig()
    selected = designs[: cfg.top_n]
    n = len(selected)
    assay = recommend_assay(n, cfg.budget_usd)

    lines: list[str] = []
    lines.append("# Wet-lab plan")
    lines.append("")
    lines.append(f"**Designs selected:** {n}  ·  **Organism:** {cfg.organism}  ·  **Tag:** {cfg.tag}")
    if cfg.budget_usd is not None:
        lines.append(f"**Budget:** ${cfg.budget_usd:,.0f}")
    lines.append("")

    # 1. Gene synthesis
    total_bp = sum(sequence_properties(d.get("sequence", ""))["length"] * 3 + 3 for d in selected)
    est_cost = total_bp * cfg.cost_per_gene_usd
    lines += [
        "## 1. Gene synthesis",
        f"- Vendor: {cfg.gene_vendor} (override per lab)",
        f"- Constructs: {n} genes, {cfg.tag} tag, E. coli codon-optimized",
        f"- Estimated synthesis: ~{total_bp:,} bp → ~${est_cost:,.0f} (order-of-magnitude)",
        "",
    ]

    # 2. Expression
    lines += [
        "## 2. Expression",
        "- Strain: E. coli BL21(DE3); medium: LB or auto-induction (ZYM-5052)",
        "- Induction: 0.5 mM IPTG, 18 °C overnight (favors soluble folding)",
        "",
    ]

    # 3. Testing (Adaptyv: express + characterize)
    lines += [
        "## 3. Testing",
        f"- Platform: {assay['platform']}",
        f"- Screen: {assay['screen']}",
        "- Lead characterization:",
        *[f"  - {a}" for a in assay["lead_characterization"]],
        "",
    ]

    # 5. Controls
    lines += [
        "## 5. Controls",
        "- Positive: a known binder of the target (if available)",
        "- Negative: scrambled-sequence binder + target-only (no binder)",
        "",
    ]

    # 6. Design list
    lines += [
        "## 6. Selected designs",
        "",
        "| Rank | ID | Length | MW (kDa) | pI | ε₂₈₀ |",
        "|---|---|---|---|---|---|",
    ]
    for i, d in enumerate(selected, 1):
        did = d.get("binder_id") or d.get("id") or f"design_{i}"
        props = sequence_properties(d.get("sequence", ""))
        lines.append(
            f"| {i} | {did} | {props['length']} | {props['molecular_weight'] / 1000:.1f} | "
            f"{props['isoelectric_point']} | {props['extinction_280']:,} |"
        )
    lines.append("")
    lines.append("### FASTA")
    lines.append("```")
    for i, d in enumerate(selected, 1):
        did = d.get("binder_id") or d.get("id") or f"design_{i}"
        lines.append(f">{did}")
        lines.append(str(d.get("sequence", "")))
    lines.append("```")

    if cfg.notes:
        lines += ["", "## Notes", *[f"- {note}" for note in cfg.notes]]

    return "\n".join(lines) + "\n"
