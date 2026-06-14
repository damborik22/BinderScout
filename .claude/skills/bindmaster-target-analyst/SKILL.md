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

### 2a. Sequence-driven discovery (the common case)

A bare sequence is usually all we get. Every downstream step needs a structure, so from the
sequence do three things before §3 — **find the right PDB, build the MSA, fold only if needed**:

1. **Find the right PDB** — search the sequence against the PDB and pick the best *experimental*
   structure: high identity (≥ ~95 % = the same protein), good resolution, and **prefer a
   relevant complex over apo** (complexes reveal interfaces). A high-identity PDB beats any model —
   use it and skip folding.
   - RCSB sequence service: POST a sequence query to `https://search.rcsb.org/rcsbsearch/v2/query`
     (returns scored PDB ids). `TODO:` pin the exact JSON query + a small helper.
2. **Build the MSA** — reuse the repo's `get_target_msa(seq)`
   (`Evaluator/binder_comparison/refolding/target_msa.py`): queries the ColabFold MMseqs2 server,
   returns an A3M, **cached** (`~/.cache/bindmaster/target_msa/`). The MSA gives:
   homologs/family (*what is this target*), **conservation** (per-column entropy → conserved
   surface residues = functional/binding sites; see `interaction-sites.md`), and it is **reused**
   downstream by folding + the evaluator's AF3/ESMFold2 refold (same cache — generate once).
   `TODO:` expose as `binder-compare target-msa` so the skill / `analyze-target` call it cleanly.
3. **Fold only if needed** — no good experimental PDB (novel / low-identity) → predict a model
   *with the MSA*:
   ```bash
   Mosaic/.venv/bin/python configurator/predict_structure.py "<SEQUENCE>" runs/<name>/target/<name>.pdb
   ```
   (Boltz-2 + MSA; prints mean pLDDT.) Then run `analyze-target` + PDBsum on the model.

**Which folding engine?** For an *unsolved target* (a natural protein), **MSA-based AF-class
prediction is best** — accuracy matters because every site/difficulty call rides on the model:
- **AF3** (`binder-eval-af3`, big-VRAM) — highest accuracy when available.
- **Boltz-2 + MSA** (`predict_structure.py`, already wired) — AF3-class, the practical default.
- **AF2 / ColabFold** (via the BindCraft env) — gold-standard monomer accuracy with a deep MSA.
- **ESMFold2** — MSA-free, fast, good for a first pass, but **weaker on novel / low-homology**
  folds — use it only as a quick proxy, not the model the dossier commits to.
(This is the opposite of *binder* refolding, where de novo binders have no MSA — here the target
is natural and has homologs, so feed the MSA.)

**pLDDT = confidence + disorder:** low-pLDDT regions are disordered and their pockets unreliable.
AF/Boltz write pLDDT into the PDB B-factor column, so pass it straight through —
`binder-compare analyze-target --target model.pdb --plddt-from-bfactor` computes a real
`disorder_fraction` that raises the difficulty band (do **not** use the flag on experimental
structures — those B-factors are crystallographic).

**Caveats:** a *monomer model* has no real partner, so PDBsum PPI-interface detection won't apply
(cleft / ligand-pocket detection still does) — for a PPI target you need the partner or a
predicted complex.

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

Turn the research + structure into a list of candidate binding sites, each with **evidence** —
combine several signals (details + caveats in `interaction-sites.md`):
- **PDBsum** ([PDBsum1](https://github.com/RomanLas/PDBsum1), local) → interface residues (PPI /
  epitopes), clefts/pockets, ligand contacts, active sites. Primary per-structure source.
- **HotSpot Wizard** ([HSW3](https://loschmidt.chemi.muni.cz/hotspotwizard/), Loschmidt; PDB *or*
  sequence) → functional hotspots = active-site-pocket + access-tunnel residues (CASTp/CAVER) for
  enzyme/pocket targets. Use its pocket *location*, not its mutability ranking; pocket-centric (not PPI).
- **Conservation** (from the MSA, §2a) — conserved + surface patch = functional site.
- **Surface hydrophobicity** — accessible hydrophobic clusters = binding-prone patches.
- **UniProt** feature table (active/binding sites, glyco, disulfide, PTM); literature epitopes.
- `TODO:` PDBsum + HSW submit/parse recipes; the conservation calc. (Surface hydrophobicity +
  pLDDT-disorder are now emitted by `analyze-target` — see 3c.)

### 3c. Geometric analysis  →  `binder-compare analyze-target`

```bash
binder-compare analyze-target --target runs/<name>/target/<t>.pdb --chain A \
    --n-hotspots 6 [--plddt-from-bfactor] -o target_geometry.json
```
Profile JSON: a 0–1 `difficulty` (+ band), Cα-density pocket `candidate_hotspots`,
`flat_surface_fraction`, `surface_hydrophobicity`, `disorder_fraction` (real when
`--plddt-from-bfactor` is set on a predicted model), and suggested `n_target` / gate-tier / tools /
binder-length. The **difficulty score** is the main use here; for *where to bind*, prefer PDBsum /
HSW / conservation (3b) — the Cα-density pockets are the always-on fallback. **Advisory** —
reconcile with 3b, don't replace it. `TODO:` map literature/PDBsum/HSW sites to residue numbers and
cross-check the geometric pockets.

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
- **External tools:**
  - [PDBsum1](https://github.com/RomanLas/PDBsum1) — local structural annotation (interfaces /
    clefts / ligand contacts / active sites). Per-platform executables + `data.tar.gz`, not
    pip-installable; `TODO:` worker pre-flight setup note.
  - [HotSpot Wizard 3](https://loschmidt.chemi.muni.cz/hotspotwizard/) — Loschmidt functional
    pocket/tunnel hotspots + conservation (CASTp / CAVER / Rate4Site); web server, lab access.
  - MSA via the repo's `get_target_msa` (`Evaluator/binder_comparison/refolding/target_msa.py`,
    ColabFold MMseqs2, cached); folding via `configurator/predict_structure.py` (Boltz-2).
- Sibling skills: `bindmaster-orchestrator` (consumes the dossier), `bindmaster-evaluator`, `bindmaster-wetlab`.
- CLI: `binder-compare analyze-target` (`Evaluator/binder_comparison/cli/analyze_target.py`).
