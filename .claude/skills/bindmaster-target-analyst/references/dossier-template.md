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

## Merge rules (literature/PDBsum vs. geometry)

- **Where to bind** → evidence wins: take `hotspots` from the top-ranked site in
  `interaction-sites.md` (PDBsum / complex / literature), **not** from `analyze-target`'s
  Cα-density pockets. Use the geometric pockets only as a fallback when there is no
  structural/literature site, or as a confirmation signal.
- **Difficulty** → blend: start from `analyze-target`'s geometric `difficulty`, then **raise the
  band** for literature flags (disorder, heavy glycosylation, flat/shallow PPI, no apo structure).
  Document the rationale.
- **Binder length** → `analyze-target`'s `suggested_binder_length`, widened toward the longer end
  for shallow-PPI targets.
- **n_target / gate_tier / tools** → from the (possibly raised) difficulty band via
  `suggest_campaign`; harder → smaller N, more permissive gate, more diverse tools.

## Into the orchestrator kickoff

The JSON sidecar maps onto the campaign the orchestrator drives:
- `hotspots` → each tool's hotspot field (BindCraft `target_hotspot_residues`, PXDesign / PC /
  PH / RFD3 hotspot configs) — kept clustered on one face (see `interaction-sites.md`).
- `n_target` + `gate_tier` → `binder-compare autosize --n-target --tier` (per tool, equal-N).
- `tools` → which design tools the orchestrator assigns.
- `binder_length` → each tool's length range.

`TODO:` finalize the exact field names once the orchestrator's `autosize.md` is polished.
