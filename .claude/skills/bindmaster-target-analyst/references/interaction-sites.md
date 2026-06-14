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

## HotSpot Wizard (Loschmidt — functional pocket/tunnel residues)

[HotSpot Wizard 3](https://loschmidt.chemi.muni.cz/hotspotwizard/) (our lab) takes a **PDB or a
sequence** and integrates pocket detection (**CASTp**), access tunnels (**CAVER**), catalytic
sites (Catalytic Site Atlas), and conservation (**Rate4Site**) into hotspot lists. Its
**functional hotspots** — residues lining the **active-site pocket** and **access tunnels** — are
exactly the residues a binder targeting that pocket should engage, so for an **enzyme / deep-pocket
target** HSW directly yields the candidate binding-site residues, sequence-input and all (fits
SKILL §2a).

**Use it for the pocket *location*, not its mutability ranking.** HSW ranks residues by how good
they are to *mutate* (it favours highly *variable* positions for engineering); for *binding* we
want the residues that *define/line* the pocket, regardless of mutability. So take HSW's
pocket/tunnel residue **set** as the candidate site, then pick clustered, accessible hotspots from
it as below.

**Caveats:** HSW is **pocket/tunnel-centric** (CASTp/CAVER) — great for active-site/cryptic-pocket
binders, but it does **not** find flat **protein–protein interface** patches; those still come from
PDBsum complexes + conservation. It's a Loschmidt **web server** (lab access; automation may need
the lab instance). `TODO:` pin the submit/parse recipe (or its API) during polish.

## Conservation (from the MSA)

The target MSA (`get_target_msa`, SKILL §2a) is a second, sequence-based site signal:
**conserved surface residues are usually functional** (active sites, binding patches stay
conserved while the rest of the surface drifts). Compute per-column conservation (e.g. Shannon
entropy / a ConSurf-style score) over the A3M, map it onto the structure, and treat a **conserved
+ surface-accessible patch that coincides with a PDBsum cleft/interface** as a high-confidence
functional site. Conservation alone (buried conserved core) is *not* a binding site — require
surface accessibility. `TODO:` pin the conservation calc + the mapping recipe.

## Surface hydrophobicity (binding-patch signal)

Protein–protein and pocket binding patches are frequently **hydrophobic**, so a third site signal
is **surface hydrophobicity**: per-residue hydrophobicity weighted by exposure. Compute residue
hydrophobicity (Kyte-Doolittle — the repo already ships the table in
`Evaluator/binder_comparison/comparison/wetlab.py:_KD_HYDROPATHY`, or the Eisenberg scale /
hydrophobic moment for amphipathicity) × surface accessibility (SASA / the Cα-density proxy), and
look for **accessible hydrophobic clusters**. An accessible hydrophobic patch that overlaps a
PDBsum cleft / conserved surface = a strong binding-site candidate. Tools beyond the built-in
table: molecular hydrophobicity potential (MHP), PyMOL `color_h`.

**Flip side — binder developability:** the same metric on the *binder* surface flags aggregation
risk (large exposed hydrophobic patches). That's a QC/developability concern → see
`bindmaster-wetlab` and `bindmaster-evaluator` (`qc.md`), not target analysis. `TODO:` a small
`analyze-target` enhancement could emit a per-residue surface-hydrophobicity track for free (it
already has coords + the KD table is one import away).

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

1. **Map every site to the PDB file's own residue numbering** — that is what the design tools'
   hotspot fields use. UniProt features are 1-indexed on the canonical sequence; the PDB file
   uses author numbering (`auth_seq_id`), which can differ (His-tags, construct cropping, missing
   loops). Reconcile via **SIFTS** (`https://www.ebi.ac.uk/pdbe/api/mappings/<pdbid>`) or by
   aligning the PDB chain sequence to UniProt. PDBsum and RCSB both report author numbering, so
   they already match the structure file `analyze-target` reads.
2. **Cross-check against geometry** — a site that is *both* biologically important (literature /
   PDBsum interface or cleft) *and* a real pocket (`analyze-target` Cα-density or, better, a
   PDBsum cleft) is the strongest candidate. Disagreement is a flag, not a veto.
3. **Pick hotspots (3–6 residues) on ONE contiguous patch.** Prefer residues that line the chosen
   cleft/interface (PDBsum contact residues), are solvent-accessible, and **cluster on a single
   face**. Hard rule from `bindmaster-orchestrator/references/learnings.md` #2: hotspots scattered
   across distant secondary-structure elements break BindCraft's AF2 hallucination (10/10 failed
   trajectories on 2VDY). When a site is large, pick the centroid contact residue + its nearest
   lining residues rather than the extremes.

## Ranking the candidate sites

Score each candidate site, output the ranked list to the dossier:

| Factor | Strong → weak |
|---|---|
| **Evidence** | experimental complex (partner/antibody bound) > PDBsum cleft/ligand contacts > ChEMBL `get_mechanism` site > bare literature claim |
| **Druggability** | deep, well-defined PDBsum cleft (or confirmed geometric pocket) > shallow/flat patch |
| **Campaign fit** | matches the goal: *block function* → active/allosteric site; *block signaling* → the PPI interface; *proven bindable* → a known epitope |
| **Risk** | clean surface > glycosylated/PTM-adjacent (down-weight or avoid) |

The top-ranked site's clustered hotspots + accessibility become the dossier's recommended
hotspots; carry the runners-up so the orchestrator can A/B two sites if the budget allows.
