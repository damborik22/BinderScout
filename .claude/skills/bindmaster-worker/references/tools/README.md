# Worker Tool Playbooks — Index

Per-tool operational reference for the worker. **Operational means:** where progress shows up, common errors, packaging, kill criteria, OOM thresholds, source-of-truth files.

For engine principles, knobs, and "when to pick this tool" — see `bindmaster-orchestrator/references/tools/<tool>.md`. The two `tools/` folders complement each other:

| Layer | Audience | Content |
|---|---|---|
| `bindmaster-orchestrator/references/tools/` | orchestrator | engine, principle, native metrics, when to pick, cross-method bias |
| `bindmaster-worker/references/tools/` (this folder) | worker | where progress shows up, common errors, OOM thresholds, packaging |

Same tool name, different layer of knowledge.

## Files in this folder

| File | Tool | Env |
|---|---|---|
| `bindcraft.md` | BindCraft | conda `BindCraft` |
| `boltzgen.md` | BoltzGen | conda `BoltzGen` |
| `mosaic.md` | Mosaic | uv venv `Mosaic/.venv` |
| `protein-hunter.md` | Protein-Hunter | conda `bindmaster_protein_hunter` |
| `pxdesign.md` | PXDesign | conda `bindmaster_pxdesign` |
| `proteina-complexa.md` | Proteina-Complexa | uv venv `Proteina-Complexa/.venv` |
| `rfd3.md` | RFD3 | conda `bindmaster_rfd3` |

## Common entry-template fields

Every tool playbook has the same structure:

```markdown
# <Tool> — Worker Operations

**Env:**  conda env / venv name
**Run-script template:** path under bindmaster_examples/
**Engine reference:** link to orchestrator-side tools/<tool>.md

## Source-of-truth files
- Which file/directory tells you "real progress" (not directory listings)
- Per-stage signals to monitor

## Pre-flight specific to <tool>
- Tool-specific cache verification
- Tool-specific env quirks
- Tool-specific aarch64 / platform notes

## OOM / hardware limits
- Per-GPU-class table

## Common errors
- Linked to troubleshooting.md anchors where applicable

## Wedge / kill criteria
- When to kill (independent of assignment-specific kill criteria)

## Packaging recipe
- Tar command for full + _final variants

## Reporting back
- Template for the PROGRESS.md Worker updates completion entry
```

## How the worker consults these

When an assignment comes in for a specific tool, the worker reads:

1. `../../SKILL.md` — overall lifecycle (skim if not first time)
2. `<this folder>/<tool>.md` — tool-specific operational quirks
3. `../pre-flight.md` — generic pre-flight protocol
4. `../packaging.md` — output handoff convention
5. `../troubleshooting.md` only when symptoms arise

The orchestrator's `tools/<tool>.md` is consulted only for context (why this tool was chosen) — not for execution.
