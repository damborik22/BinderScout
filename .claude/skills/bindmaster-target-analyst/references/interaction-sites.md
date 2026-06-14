# Interaction & functional sites

> **Scaffold.** Taxonomy + evidence sources are listed; `TODO:` add residue-mapping recipes,
> ranking rubric, and how the chosen site becomes hotspots.

Turn the research brief (`literature-research.md`) + structural annotation (PDBsum) + geometry
(`binder-compare analyze-target`) into a **ranked list of candidate binding sites**, each with
evidence and residue numbers.

## Structural annotation — PDBsum (primary site source from a structure)

[PDBsum1](https://github.com/RomanLas/PDBsum1) (Roman Laskowski, EMBL-EBI) — the **standalone,
local** version of PDBsum Generate — is the best per-structure source of *important spots*. Run
it on the target PDB (or any complex PDB) and it computes:

- **protein–protein / protein–DNA interface residues** (which residues a partner actually contacts → PPI sites, epitopes)
- **clefts / pockets** (SURFNET-style — real concave pockets, much richer than `analyze-target`'s Cα-density proxy)
- **ligand-contact residues** (LigPlot — where a known ligand/drug binds → candidate hotspot site)
- **active sites**, secondary structure + topology

It is **local** (no API; works offline on Spark) — install from the repo's per-platform
executables + `data.tar.gz`; usage is in its `docs.tar.gz` (`install.html`). `TODO:` pin the
exact run command + parse its interface/cleft/ligand outputs into our residue lists once
installed. `TODO:` decide PDBsum (rich, needs install) vs `analyze-target` (built-in, crude) per
campaign — prefer PDBsum for clefts/interfaces when available; `analyze-target` is the always-on
fallback + difficulty score. The EBI web PDBsum (`https://www.ebi.ac.uk/pdbsum/`) is a quick
per-PDB-id lookup when a local run isn't set up.

## Site taxonomy (target the right one)

| Site type | What it is | Where to find it | Design implication |
|---|---|---|---|
| **Catalytic / active** | enzyme active site, cofactor pocket | **PDBsum active sites**; UniProt features; ChEMBL `get_mechanism` | block function; usually deep/conserved → easier to grip |
| **Allosteric** | regulatory pocket away from the active site | **PDBsum clefts**; allosteric-modulator drugs (ChEMBL); literature | functional modulation; may be shallow |
| **Protein–protein interface (PPI)** | the surface it uses to bind a partner/receptor | **PDBsum interface residues** (from complexes); literature | block signaling; often **flat/shallow → harder** |
| **Epitope** | a known antibody-binding patch | **PDBsum interface residues** of antibody complexes; literature | proven bindable surface; good hotspot prior |
| **Ligand pocket** | where a known small-molecule/drug binds | **PDBsum ligand contacts** (LigPlot); ChEMBL | druggable pocket → strong hotspot prior |
| **PTM / glyco** | modified residues | UniProt features; PDBsum modified residues | avoid (glycans block binders) — a difficulty flag |

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
