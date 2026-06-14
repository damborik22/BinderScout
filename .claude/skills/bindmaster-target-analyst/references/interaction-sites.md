# Interaction & functional sites

> **Scaffold.** Taxonomy + evidence sources are listed; `TODO:` add residue-mapping recipes,
> ranking rubric, and how the chosen site becomes hotspots.

Turn the research brief (`literature-research.md`) + geometry (`binder-compare analyze-target`)
into a **ranked list of candidate binding sites**, each with evidence and residue numbers.

## Site taxonomy (target the right one)

| Site type | What it is | Where to find it | Design implication |
|---|---|---|---|
| **Catalytic / active** | enzyme active site, cofactor pocket | UniProt features; ChEMBL `get_mechanism`; literature | block function; usually deep/conserved → easier to grip |
| **Allosteric** | regulatory pocket away from the active site | literature; allosteric-modulator drugs (ChEMBL) | functional modulation; may be shallow |
| **Protein–protein interface (PPI)** | the surface it uses to bind a partner/receptor | PDB complexes; literature | block signaling; often **flat/shallow → harder** |
| **Epitope** | a known antibody-binding patch | antibody-complex PDBs; literature | proven bindable surface; good hotspot prior |
| **PTM / glyco** | modified residues | UniProt features | avoid (glycans block binders) — a difficulty flag |

## From site → residues → hotspots

1. Map each candidate site to **residue numbers** on the target chain (UniProt features are
   1-indexed on the canonical sequence; reconcile with the PDB numbering of the actual file).
   `TODO:` numbering-reconciliation recipe (auth vs label seq id).
2. Cross-check against `analyze-target`'s geometric pockets — a site that is *both*
   biologically important *and* a geometric pocket is the strongest candidate.
3. Pick **hotspots** on the chosen site (3–6 residues lining the pocket). `TODO:` selection
   rubric; the BindCraft caveat — scattered hotspots across distant SSEs break AF2 hallucination
   (orchestrator `learnings.md` #2), so prefer hotspots clustered on **one** face.

## Ranking the candidate sites

`TODO:` rubric combining evidence strength (structure > drug-mechanism > literature claim),
druggability (pocket depth from geometry), and campaign goal (block function vs. block PPI).
Output the ranked list into the dossier.
