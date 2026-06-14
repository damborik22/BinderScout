# Target dossier template

> **Scaffold.** The structure is here; `TODO:` fill worked examples and the dossier→kickoff
> field mapping.

The analyst's deliverable: a markdown dossier for humans + a JSON sidecar of campaign params
for the orchestrator/autosize. Save to `CLUSTER/<TARGET>_DOSSIER.md` (+ `.json`).

## Markdown dossier

```markdown
# <TARGET> — Target Dossier
**Resolved:** <name> · UniProt <acc> · gene <GENE> · PDB <ids>
**Prepared:** <date>

## 1. Function & disease context
<one paragraph, cited>

## 2. Known binders (modality | potency | binding site | source)
<table from ChEMBL/drugs/antibodies>

## 3. Candidate binding sites (ranked)
| Rank | Site | Type | Residues | Evidence | Geometric pocket? |
|------|------|------|----------|----------|-------------------|

## 4. Chosen site & hotspots
<which site, why, the 3–6 hotspot residues — clustered on one face>

## 5. Difficulty
<geometry score + literature flags (flexibility / glycosylation / shallow PPI) → band>

## 6. Recommended campaign
<per-tool N, gate tier, tools, binder-length range, hotspot config>
```

## JSON sidecar (→ orchestrator / autosize)

```json
{
  "target": "...", "chain": "A",
  "difficulty": 0.0, "difficulty_band": "easy|medium|hard",
  "hotspots": ["A37", "A39", "A49"],
  "n_target": 0, "gate_tier": "permissive|default|strict",
  "tools": ["..."], "binder_length": [60, 120]
}
```

`TODO:` reconcile the geometric `analyze-target` JSON with the literature-chosen site; document
the override rules (literature beats geometry on *where*, geometry informs *difficulty* and
*length*). `TODO:` the exact mapping into the orchestrator kickoff doc + each tool's hotspot field.
