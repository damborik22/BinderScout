---
name: bindmaster-target-analyst
description: Use this skill at the START of a binder-design campaign to research and characterize a target before any compute is committed. It (1) researches the literature and databases for what is known about the target — function, disease relevance, known binders / inhibitors / antibodies, existing structures; (2) identifies the important spots — catalytic/active sites, allosteric pockets, protein–protein interaction interfaces, known epitopes, PTM and glycosylation sites; (3) runs `binder-compare analyze-target` for geometric difficulty + pocket detection; and (4) synthesizes a target dossier with recommended hotspots and campaign parameters (per-tool N, gate tier, tools, binder-length range). Triggers include "analyze the target", "research <target>", "what's known about <target>", "where should the binder bind", "find the interaction sites / epitopes / active site", "how hard is <target>", "propose a campaign for <target>", "what should we run on <target>". It hands the dossier to `bindmaster-orchestrator`; it does NOT run design tools.
---

# BindMaster Target Analyst — SKILL base

> **Status: scaffold.** Basic structure to polish section by section. `TODO:` marks the spots
> that need fleshing out with real recipes/examples.

**Audience:** an AI agent characterizing a binder-design target before a campaign. The job:
**research → find the important spots → assess difficulty → recommend a campaign**, captured
as a *target dossier* the orchestrator turns into per-tool assignments.

**When you read this:** at the very start of a campaign, before `bindmaster-orchestrator`
allocates compute — or whenever someone asks "what do we know about this target / where
should the binder bind / how hard is it."

**What this skill is NOT:**
- Not a design runner (that's `bindmaster-worker`) or an allocator (that's `bindmaster-orchestrator`).
- Not a structure predictor — it consumes an existing target structure (PDB/mmCIF). `TODO:`
  note the AF2/ESMFold fallback if no experimental structure exists.
- Not an oracle — the geometric difficulty score and auto-hotspots are **advisory**; literature
  evidence overrides geometry when they disagree.

---

## 1. Mental model

A target has two kinds of "important spots", and a good campaign targets the right one:

- **Functional sites** — catalytic/active site, cofactor/substrate pocket, allosteric sites.
- **Interaction sites** — the protein–protein interface(s) it uses in vivo, known antibody
  epitopes, receptor-binding motifs.

The analyst's value is **reconciling literature-grounded sites with geometry**: the literature
says *where it matters biologically*; `analyze-target` says *where a binder can physically grip*.
The dossier ranks candidate sites by combined evidence and turns the chosen one into hotspots.

---

## 2. Inputs

A target reference in any of these forms — resolve to the others as step 0:
- Protein/gene name (e.g. "PD-L1", "CALCA")
- UniProt accession
- PDB id(s) — apo and/or in complex
- A local structure file (`runs/<name>/target/*.pdb|*.cif`)
- **A bare amino-acid sequence** (very common) — handle via §2a.

`TODO:` document the resolution recipe (name → UniProt → gene → PDB) using WebFetch on
UniProt/PDB.

### 2a. Sequence-only targets (no structure / no id)

Every downstream step needs a structure (`analyze-target`, PDBsum). When the input is just a
sequence, **fold it first**, in parallel with identifying it:

1. **Identify** — the sequence may be a known protein. Search UniProt by sequence
   (`https://rest.uniprot.org/uniprotkb/search?query=<seq>` / BLAST), or it may be named in the
   request. If identified → pull literature + *experimental* structures as usual (prefer a real
   PDB over a model).
2. **Fold** — if there is no experimental structure (novel/engineered target, or just to move
   fast), predict one with the repo's helper:
   ```bash
   Mosaic/.venv/bin/python configurator/predict_structure.py "<SEQUENCE>" runs/<name>/target/<name>.pdb
   ```
   It folds with Boltz-2 and prints **mean pLDDT**. Then run `analyze-target` + PDBsum on the model.
3. **Use pLDDT as a confidence + disorder signal** — low-pLDDT regions are disordered (raise the
   difficulty band) and their pockets/clefts are unreliable (down-weight sites there). A
   well-folded high-pLDDT core is where a binder should grip.

**Caveats:** a *monomer model* has no real partner, so PDBsum PPI-interface detection won't apply
(cleft/ligand-pocket detection still does) — for a PPI target you need the partner or a predicted
complex. `TODO:` code enhancement — let `analyze-target` ingest per-residue pLDDT to compute its
`disorder_fraction` directly (today it is hardcoded 0); also an ESMFold2/AF2 alt-folder option.

---

## 3. Workflow

### 3a. Literature & database research  →  see `references/literature-research.md`

Build the "what's known" picture. Tools available in-session: **PubMed**, **ChEMBL**,
**bioRxiv/medRxiv**, **ClinicalTrials**, and **WebFetch** (UniProt, RCSB PDB, InterPro).

1. **Identity & function** — resolve UniProt; pull function, domains, family. (UniProt via
   WebFetch; ChEMBL `target_search`.)
2. **Disease & clinical context** — why is this a target? (PubMed `search_articles`;
   ClinicalTrials `search_trials` by the target/intervention.)
3. **Known binders** — small molecules, drugs, antibodies, and *their binding sites*. (ChEMBL
   `target_search` → `get_bioactivity` for potent compounds, `drug_search`, `get_mechanism` —
   the mechanism/binding-site field is gold.)
4. **Existing structures** — apo + complexes in the PDB. Complexes literally show where things
   bind. (RCSB via WebFetch.)
5. **Recent / preprint** — `bioRxiv search_preprints`, `search_published_preprints`.

`TODO:` per-tool query templates + how to dedupe/cite; how much to trust each source.

### 3b. Structural annotation + interaction-site ID  →  see `references/interaction-sites.md`

Turn the research + structure into a list of candidate binding sites, each with **evidence**:
- **PDBsum** ([PDBsum1](https://github.com/RomanLas/PDBsum1), local) on the target/complex PDBs →
  interface residues (PPI / epitopes), clefts/pockets, ligand-contact residues, active sites.
  This is the primary per-structure source — richer than the geometric pocket proxy in 3c.
- UniProt feature table (active site, binding site, glyco, disulfide, PTM).
- Epitopes / hotspots from the literature.
- `TODO:` taxonomy (catalytic / allosteric / PPI / epitope / ligand) and how to evidence each;
  PDBsum install + output-parsing recipe.

### 3c. Geometric analysis  →  `binder-compare analyze-target`

```bash
binder-compare analyze-target --target runs/<name>/target/<t>.pdb --chain A \
    --n-hotspots 6 -o target_geometry.json
```
Gives a 0–1 difficulty score, Cα-density pocket hotspots, and suggested `n_target` / gate-tier /
tools / binder-length. The **difficulty score** is the main use here; for *where to bind*, prefer
PDBsum's clefts/interfaces (3b) — `analyze-target`'s Cα-density pockets are the always-on fallback
when PDBsum isn't installed. **Advisory** — reconcile with 3b, don't replace it. `TODO:` how to
map literature/PDBsum sites to residue numbers and cross-check the geometric pockets.

### 3d. Synthesis → the dossier  →  see `references/dossier-template.md`

Reconcile 3a–3c into a single dossier: a ranked list of candidate sites (with evidence),
recommended hotspots for the chosen site, a difficulty assessment (geometry **+** literature
signals like flexibility / glycosylation / shallow interface), and campaign parameters. `TODO:`
the merge rules when literature and geometry disagree.

---

## 4. Output — the target dossier

A markdown dossier (and a JSON sidecar of the campaign params). Sections in
`references/dossier-template.md`. Headline fields: target identity, function, known binders,
**ranked candidate sites + chosen hotspots**, difficulty + rationale, and suggested
`n_target` / gate-tier / tools / binder-length for `autosize`.

---

## 5. Handoff

→ **`bindmaster-orchestrator`**: the dossier's campaign params seed the per-tool assignments.
The chosen hotspots flow into each tool's config; the difficulty band sets per-tool N and the
gate tier. `TODO:` exact field mapping dossier → kickoff doc.

---

## 6. References

- `references/literature-research.md` — the PubMed/ChEMBL/bioRxiv/ClinicalTrials/UniProt/PDB playbook.
- `references/interaction-sites.md` — site taxonomy + PDBsum structural annotation + how to evidence each.
- `references/dossier-template.md` — the output dossier structure + the params handed to the orchestrator.
- **Tooling:** [PDBsum1](https://github.com/RomanLas/PDBsum1) — local structural annotation
  (interfaces / clefts / ligand contacts / active sites). `TODO:` add to the worker pre-flight / a
  setup note; it is per-platform executables + `data.tar.gz`, not pip-installable.
- Sibling skills: `bindmaster-orchestrator` (consumes the dossier), `bindmaster-evaluator`, `bindmaster-wetlab`.
- CLI: `binder-compare analyze-target` (`Evaluator/binder_comparison/cli/analyze_target.py`).
