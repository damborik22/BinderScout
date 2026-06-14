# Literature & database research playbook

Goal: assemble "what is known about this target" with citations, ending in a list of
**candidate binding sites with evidence** (consumed by `interaction-sites.md`). All tools below
are live in-session; use real queries, cite what you use.

## Available research tools

| Source | Tool(s) | Use for |
|---|---|---|
| **UniProt** | WebFetch `https://rest.uniprot.org/uniprotkb/<acc>.txt` (or `.json`) | identity, function, domains, **feature table** (active/binding sites, PTM, glyco, disulfide), sequence + numbering |
| **RCSB PDB** | WebFetch `https://data.rcsb.org/rest/v1/core/entry/<id>`; `https://www.rcsb.org/structure/<id>` | apo + **complex** structures, resolution, bound ligands/partners |
| **PDBsum** | local [PDBsum1](https://github.com/RomanLas/PDBsum1); web `https://www.ebi.ac.uk/pdbsum/<id>` | interface residues, clefts, ligand contacts, active sites (richest per-structure — see `interaction-sites.md`) |
| **PubMed** | `mcp__PubMed__search_articles`, `get_article_metadata`, `get_full_text_article`, `find_related_articles` | function, disease relevance, epitopes, PPI partners, flexibility/glycosylation notes |
| **ChEMBL** | `target_search`, `get_bioactivity`, `get_mechanism`, `drug_search` | known ligands/drugs and **their binding site / mechanism** |
| **bioRxiv/medRxiv** | `mcp__bioRxiv__search_preprints` | recent, not-yet-indexed findings |
| **ClinicalTrials** | `mcp__Clinical_Trials__search_trials` | clinical-stage modalities against the target |

## Step 0 — resolve identity (name → UniProt → gene → PDB)

> **Sequence-only input?** First identify it: UniProt sequence search
> (`https://rest.uniprot.org/uniprotkb/search?query=<seq>&format=json`) or BLAST. If it matches a
> known protein, proceed below. If it's novel/engineered (no hit), skip to folding (SKILL §2a) —
> there's no literature, so geometry on the predicted model leads.

1. `mcp__ChEMBL__target_search(gene_symbol="<GENE>", organism="Homo sapiens", target_type="SINGLE PROTEIN")`
   → returns the target's components incl. **UniProt accession** + `target_chembl_id` (keep both).
2. WebFetch UniProt `.../uniprotkb/<acc>.txt` → canonical sequence, gene, domains, and the
   **feature table** (the authoritative residue-level site list).
3. WebFetch RCSB `.../core/entry/<pdbid>` for each PDB the target appears in → note **complexes**
   (antibody / partner / ligand bound) — these are where the real binding sites are.

## Step-by-step research order (cheap → specific)

1. **Function & family** — UniProt + ChEMBL `target_search`. One-paragraph cited summary.
2. **Disease / why-a-target** —
   `mcp__PubMed__search_articles(query="<TARGET> AND (inhibitor OR antibody OR binder)[Title/Abstract]", sort="relevance", max_results=20)`;
   `mcp__Clinical_Trials__search_trials(...)`. Read the top 3–5 abstracts.
3. **Known binders & their sites** —
   `mcp__ChEMBL__get_bioactivity(target_chembl_id="<id>", min_pchembl=7)` (potent compounds);
   `mcp__ChEMBL__get_mechanism(target_chembl_id="<id>")` — the `binding_site_name` /
   `molecular_mechanism` fields **name the pocket** (active vs allosteric);
   `mcp__ChEMBL__drug_search(indication="<disease>")` for approved/clinical modalities.
   Fastest route to *where things bind*.
4. **Structures** — list PDB entries; flag complexes; queue them for PDBsum (`interaction-sites.md`).
5. **Recent** — `mcp__bioRxiv__search_preprints(category="biochemistry", recent_days=730)` then filter to the target.

## Output of this step — the research brief

A short, **cited** brief that feeds `interaction-sites.md` + the dossier:
- Function + family; disease context (with PMIDs).
- Table of known binders: modality | potency (pChEMBL) | binding site | source.
- PDB entries: apo vs complex (partner/ligand), resolution.
- **Difficulty flags**: disordered / flexible / heavily glycosylated / shallow interface / no
  apo structure — each cited; these feed the dossier's difficulty rationale.

## Trust & caveats
- Prefer **structural evidence** (PDB complex / PDBsum / ChEMBL mechanism) over a bare literature
  claim when they disagree about *where* a binder should go.
- ChEMBL potency ≠ a binder-design target per se — it tells you the *druggable pocket*, which is
  a strong hotspot prior.
- `TODO:` citation format to standardize across dossiers.
