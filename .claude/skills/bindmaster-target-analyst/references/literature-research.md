# Literature & database research playbook

> **Scaffold.** The tool list and query intents are real; `TODO:` marks where to add worked
> query templates, extraction recipes, and trust/caveat notes.

Goal: assemble "what is known about this target" with citations, ending in a list of
**candidate binding sites with evidence** (consumed by `interaction-sites.md`).

## Available research tools (this session)

| Source | Tool(s) | Use for |
|---|---|---|
| **UniProt** | WebFetch `https://rest.uniprot.org/uniprotkb/<acc>.txt` (or `.json`) | identity, function, domains, **feature table** (active/binding sites, PTM, glyco, disulfide), sequence |
| **RCSB PDB** | WebFetch `https://www.rcsb.org/structure/<id>`, `https://data.rcsb.org/rest/v1/core/entry/<id>` | apo + **complex** structures (complexes show binding sites), resolution, ligands |
| **PDBsum** | local [PDBsum1](https://github.com/RomanLas/PDBsum1) on a PDB; web `https://www.ebi.ac.uk/pdbsum/<id>` | **interface residues, clefts/pockets, ligand contacts, active sites** — the richest per-structure site source (see `interaction-sites.md`) |
| **PubMed** | `mcp__PubMed__search_articles`, `get_article_metadata`, `get_full_text_article`, `find_related_articles` | function, disease relevance, epitopes, PPI partners, flexibility/glycosylation notes |
| **ChEMBL** | `target_search`, `get_bioactivity`, `drug_search`, `get_mechanism`, `compound_search` | known ligands/drugs and **their binding site / mechanism** |
| **bioRxiv/medRxiv** | `mcp__bioRxiv__search_preprints`, `search_published_preprints` | recent, not-yet-indexed findings |
| **ClinicalTrials** | `mcp__Clinical_Trials__search_trials`, `search_by_sponsor` | clinical-stage modalities against the target |

## Research order (cheap → specific)

0. **Resolve identity** — name → UniProt accession → gene → PDB ids. `TODO:` resolution recipe.
1. **Function & family** — UniProt + ChEMBL `target_search`. One-paragraph summary + family.
2. **Disease / why-a-target** — PubMed `search_articles` (target + "therapeutic"/"inhibitor"/
   "antibody"); ClinicalTrials. `TODO:` query templates + how many to read.
3. **Known binders & their sites** — ChEMBL `target_search` → `get_bioactivity`
   (`min_pchembl>=7` for potent), `drug_search`, **`get_mechanism`** (binding-site/mechanism
   field names the pocket). This is often the fastest route to *where things bind*.
4. **Structures** — list PDB entries; flag **complexes** (with antibodies, peptides, partners,
   ligands) — these directly reveal interface residues. `TODO:` how to pull interface residues
   from a complex (or defer to `analyze-target` on that PDB).
5. **Recent** — bioRxiv for the last 1–2 years.

## Output of this step

A short, **cited** brief: function; disease context; table of known binders (modality, potency,
binding site, source); list of relevant PDB structures (apo vs complex); and any flags for
difficulty (flexible / disordered / heavily glycosylated / shallow interface). Feed sites into
`interaction-sites.md`, flags into the dossier's difficulty rationale.

`TODO:` citation format; how to reconcile conflicting reports; when literature is too thin and
geometry must lead.
