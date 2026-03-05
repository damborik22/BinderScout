# Phase 2 — Wiring RFAA + PXDesign into Installer, Configurator, and Evaluator

## Overview

Phase 1 (complete) created standalone adapter modules in `bindmaster/tools/rfaa/` and
`bindmaster/tools/pxdesign/`, install scripts in `scripts/`, and a unified scoring layer
in `bindmaster/scoring/`. All behind feature flags, all inert.

Phase 2 wires these into the three existing BindMaster integration points so users can
install, configure, and evaluate RFAA and PXDesign through the normal `bindmaster` CLI.

**Guiding principle:** Follow existing patterns exactly. Every tool addition touches
the same N locations in the same way. No architectural changes.

---

## Design Decisions (resolved)

1. **RFAA weights location:** Inside the cloned repo (`rf_diffusion_all_atom/weights/`).
2. **PXDesign MSA handling:** Run script warns about MSA computation time. No prompt for pre-computed MSA.
3. **RFAA in run_all.sh:** RFAA step is a two-stage pipeline: RFAA (backbones) -> LigandMPNN (sequences).
   The combined step produces sequences that can be refolded and scored like any other tool.
4. **PXDesign commit pin:** Pin to a specific commit (like BindCraft/BoltzGen/Mosaic).
5. **Evaluator metrics:** Refolded metrics only (ipsae_min, iptm from Boltz-2/AF2 refolding).
   PXDesign native metrics are not normalized — our refolding provides the canonical scores.

---

## LigandMPNN Integration

### Why LigandMPNN is required

RFAA outputs backbone PDBs **without sequences**. LigandMPNN is the standard downstream
tool that designs sequences for RFAA backbones while respecting ligand contacts. Without
LigandMPNN, RFAA output cannot participate in the evaluation pipeline.

### Architecture

LigandMPNN is NOT a separate BindMaster tool. It is installed into the `bindmaster_rfaa`
conda env and runs as the second stage of the RFAA pipeline:

```
RFAA step in run_all.sh:
  1. Run RFAA           -> backbone PDBs (rfaa/outputs/sample_*.pdb)
  2. Run LigandMPNN     -> sequences (rfaa/ligandmpnn/sample_*/seqs/*.fasta)
  3. Collect sequences   -> rfaa/sequences.csv (ready for evaluator)
```

To the user, configurator, and evaluator: this is all just the "RFAA" tool.

### LigandMPNN key facts

- **Repository:** https://github.com/dauparas/LigandMPNN
- **PyPI:** `pip install ligandmpnn`
- **Python:** 3.11 (compatible with RFAA env)
- **Key dependency:** PyTorch 2.2+ (already in RFAA env)
- **Weights:** Downloaded via `get_model_params.sh` (~150 MB)
- **Input:** PDB file (RFAA backbone with HETATM ligand records)
- **Output:** FASTA files with confidence scores in headers:
  ```
  >sample_0_111 T=0.1 seed=111 overall_confidence=0.87 ligand_confidence=0.92 seq_recovery=0.45
  MAEVKLSYVLGKKGD...
  ```
- **Key args:**
  - `--pdb_path` — input backbone PDB
  - `--out_folder` — output directory
  - `--ligand_mpnn_use_side_chain_context 1` — use ligand atom context
  - `--temperature 0.1` — sampling temperature (lower = more conservative)
  - `--number_of_batches 5` — sequences per backbone
  - `--seed` — reproducibility
- **Existing bridge code:** `bindmaster/tools/rfaa/postprocess.py` already has
  `prepare_ligandmpnn_input()` and `extract_ligand_contact_residues()`

---

## Critical Differences Between the Two Tools

| Aspect | RFAA (RFDiffusionAA + LigandMPNN) | PXDesign |
|--------|-------------------------------------|----------|
| **Output type** | Backbone PDB -> LigandMPNN sequences | Full designs with sequences + scores |
| **Pipeline** | Two-stage (RFAA -> LigandMPNN) | Single-stage |
| **Existing support** | None | Partial (import-only in configurator) |
| **Conda env name** | `bindmaster_rfaa` (includes LigandMPNN) | `bindmaster_pxdesign` |
| **Evaluator fit** | Good after LigandMPNN (has sequences) | Good (has `summary.csv` with sequences) |
| **Unique config** | ligand CCD code, contig string, LMPNN temperature | preset, n_samples, binder_length, hotspots, crop |

**PXDesign upgrade path:** Currently treated as "import external results". Phase 2
upgrades it to "run locally OR import", keeping backward compatibility.

---

## Part A — Installer (`install/install.sh`)

### What changes

8 locations in `install/install.sh` need updates, all following the existing pattern:

### A.1 — Constants (after line ~25)

```bash
# Add after MOSAIC_COMMIT
RFAA_REPO="https://github.com/baker-laboratory/rf_diffusion_all_atom.git"
RFAA_DIR="${BINDMASTER_DIR}/rf_diffusion_all_atom"
LIGANDMPNN_REPO="https://github.com/dauparas/LigandMPNN.git"
LIGANDMPNN_DIR="${BINDMASTER_DIR}/LigandMPNN"
PXDESIGN_REPO="https://github.com/bytedance/PXDesign.git"
PXDESIGN_COMMIT="XXXXXXX"  # Pin to specific commit (determine at implementation time)
PXDESIGN_DIR="${BINDMASTER_DIR}/PXDesign"
```

### A.2 — Per-tool flags (after line ~49)

```bash
# Add after DO_EVALUATOR=false
DO_RFAA=false
DO_PXDESIGN=false
```

### A.3 — Argument parser `--tool` case (line ~52-68)

Add to the case statement:
```bash
all)
    DO_BINDCRAFT=true; DO_BOLTZGEN=true; DO_MOSAIC=true
    DO_EVALUATOR=true; DO_RFAA=true; DO_PXDESIGN=true ;;
rfaa)
    DO_RFAA=true ;;
pxdesign)
    DO_PXDESIGN=true ;;
```

Update the error message to include `rfaa, pxdesign`.

### A.4 — Status check functions (after line ~307)

Follow the `is_bindcraft_installed()` / `is_boltzgen_installed()` pattern:

```bash
is_rfaa_installed() {
    [[ -d "$RFAA_DIR" ]] && env_exists bindmaster_rfaa
}

is_pxdesign_installed() {
    [[ -d "$PXDESIGN_DIR" ]] && env_exists bindmaster_pxdesign
}
```

Add `rfaa` and `pxdesign` to the `TOOLS` array used by `print_tool_status()`.

### A.5 — Interactive menu (line ~330-412)

Add two more tool entries to the selection arrays:
- Index 4: `RFAA (RFDiffusionAA + LigandMPNN)` — "All-atom diffusion for ligand binder design"
- Index 5: `PXDesign` — "Protenix-based de novo binder design"

Update loop bounds from `0 1 2 3` to `0 1 2 3 4 5`.
Add toggle cases, flag assignments, and summary display lines.

### A.6 — Install functions (after line ~937, before uninstall)

Two new functions following the **conda-based tool pattern**:

**`install_rfaa()`:**
1. Clone `$RFAA_REPO` (no commit pin initially — RFAA has no tagged releases)
2. `git submodule init && git submodule update`
3. Generate arch-specific conda YAML (reuse the pattern from `scripts/install_rfaa.sh`)
4. `conda env create -f "$ENV_YAML" --force`
5. `conda run -n bindmaster_rfaa pip install -e "$RFAA_DIR/rf2aa/"`
6. Download RFAA weights (~600 MB) to `$RFAA_DIR/weights/`
7. **Install LigandMPNN into the same env:**
   ```bash
   git clone "$LIGANDMPNN_REPO" "$LIGANDMPNN_DIR"
   conda run -n bindmaster_rfaa pip install -e "$LIGANDMPNN_DIR"
   # Download LigandMPNN weights
   cd "$LIGANDMPNN_DIR" && bash get_model_params.sh "./model_params"
   ```
8. Smoke test:
   ```bash
   conda run -n bindmaster_rfaa python -c "import torch; import rf2aa; print('RFAA OK')"
   conda run -n bindmaster_rfaa python -c "import ligandmpnn; print('LigandMPNN OK')"
   ```
9. Write shortcut: `~/.local/bin/rfaa`

**`install_pxdesign()`:**
1. Clone `$PXDESIGN_REPO` at pinned commit
2. `git submodule init && git submodule update`
3. Clone CUTLASS v3.5.1 (if not present)
4. Generate arch-specific conda YAML (reuse `scripts/install_pxdesign.sh` pattern)
5. `conda env create -f "$ENV_YAML" --force`
6. `conda run -n bindmaster_pxdesign pip install -e "$PXDESIGN_DIR"`
7. Download tool weights: `bash download_tool_weights.sh`
8. Set `CUTLASS_PATH`, `CUTLASS_NVCC_ARCHS` in `~/.bashrc`
9. Smoke test: `conda run -n bindmaster_pxdesign python -c "import pxdesign; ..."`
10. Write shortcut: `~/.local/bin/pxdesign`

Both functions reuse the **architecture detection block** from Phase 1 install scripts.

### A.7 — Uninstall case (line ~941-997)

Add to the `uninstall_tool()` case statement:
```bash
rfaa)
    conda env remove -n bindmaster_rfaa -y 2>/dev/null
    rm -f ~/.local/bin/rfaa
    [[ -d "$RFAA_DIR" ]] && { confirm "Remove $RFAA_DIR?" && rm -rf "$RFAA_DIR"; }
    [[ -d "$LIGANDMPNN_DIR" ]] && { confirm "Remove $LIGANDMPNN_DIR?" && rm -rf "$LIGANDMPNN_DIR"; }
    ;;
pxdesign)
    conda env remove -n bindmaster_pxdesign -y 2>/dev/null
    rm -f ~/.local/bin/pxdesign
    [[ -d "$PXDESIGN_DIR" ]] && { confirm "Remove $PXDESIGN_DIR?" && rm -rf "$PXDESIGN_DIR"; }
    ;;
```

### A.8 — Main execution flow (line ~1057-1070)

Add to the tool counter and sequential install calls:
```bash
[[ "${DO_RFAA}" == true ]]     && ((total_tools++))
[[ "${DO_PXDESIGN}" == true ]] && ((total_tools++))
...
[[ "${DO_RFAA}" == true ]]     && { install_rfaa     || failed_installs+=("RFAA"); }
[[ "${DO_PXDESIGN}" == true ]] && { install_pxdesign  || failed_installs+=("PXDesign"); }
```

### A.9 — `.gitignore` update

Add to existing `.gitignore`:
```
rf_diffusion_all_atom/
LigandMPNN/
PXDesign/
```

### Safety notes
- All changes are additive (new cases, new functions)
- No existing function signatures change
- `--tool all` gains two more tools but existing tools behave identically
- LigandMPNN is bundled with RFAA install — not a separate tool to the user

---

## Part B — Configurator (`configurator/configurator.py`)

### What changes

The configurator needs updates in 11 locations. PXDesign already has partial support
(import-only). We upgrade it to support local runs AND keep import mode.

### B.1 — Constants (after line ~25)

```python
RFAA_DIR = BINDMASTER_DIR / "rf_diffusion_all_atom"
LIGANDMPNN_DIR = BINDMASTER_DIR / "LigandMPNN"
PXDESIGN_DIR = BINDMASTER_DIR / "PXDesign"
```

### B.2 — `detect_installs()` (line ~178)

Add detection for the two new conda envs:
```python
installed["rfaa"] = (CONDA_ENVS_DIR / "bindmaster_rfaa").is_dir() if CONDA_ENVS_DIR else False
installed["pxdesign_local"] = (CONDA_ENVS_DIR / "bindmaster_pxdesign").is_dir() if CONDA_ENVS_DIR else False
```

### B.3 — Tool selection (Step 5, line ~1346-1378)

**RFAA (new):** Add between BindCraft and PXDesign:
```python
print(f"  {BOLD}RFAA{RESET}      [{_tag('rfaa')}]")
use_rfaa = ask_yn("  Enable RFDiffusionAA (ligand binder design)?", default=False)
```

**PXDesign (upgrade):** Replace the current single prompt with a mode choice:
```python
print(f"  {BOLD}PXDesign{RESET}  [{_tag('pxdesign_local')}] / [external import]")
_, pxdesign_mode = ask_choice(
    "  PXDesign mode",
    ["Skip", "Run locally (requires install)", "Import external results"],
    default_index=0,
)
use_pxdesign = pxdesign_mode > 0
use_pxdesign_local = (pxdesign_mode == 1)
use_pxdesign_import = (pxdesign_mode == 2)
```

Update `tools_enabled`:
```python
tools_enabled = {
    ...existing...,
    "rfaa": use_rfaa,
    "pxdesign": use_pxdesign,
    "pxdesign_local": use_pxdesign_local,
    "pxdesign_import": use_pxdesign_import,
}
```

### B.4 — Per-tool configuration (Step 6, after line ~1499)

**Step 6e — RFAA + LigandMPNN settings (NEW):**
```python
if use_rfaa:
    print_step("Step 6e -- RFDiffusionAA + LigandMPNN settings")
    print("  RFAA designs all-atom backbones for ligand-binding proteins.")
    print("  LigandMPNN then designs sequences for each backbone.")

    cfg["rfaa_ligand"] = ask(
        "  Ligand CCD code (3 letters, e.g. OQO, HEM, ATP; blank=protein-only)",
        default="",
        validator=lambda s: True if s == "" else (
            True if len(s.strip()) == 3 and s.strip().isalpha()
            else "Must be exactly 3 letters (CCD code) or blank"
        ),
    ).strip().upper() or None

    cfg["rfaa_contigs"] = ask(
        "  Contig string (e.g. '150-150' for 150-residue binder)",
        default=f"{cfg['min_length']}-{cfg['max_length']}",
    )

    cfg["rfaa_n_designs"] = int(ask(
        "  Number of backbone designs",
        default=cfg["n_designs"],
        validator=validate_int(min_val=1, max_val=1000),
    ))

    cfg["rfaa_diffusion_steps"] = int(ask(
        "  Diffusion steps (T)",
        default=100,
        validator=validate_int(min_val=10, max_val=500),
    ))

    # LigandMPNN settings
    print()
    print(f"  {BOLD}LigandMPNN sequence design{RESET}")

    cfg["lmpnn_seqs_per_backbone"] = int(ask(
        "  Sequences per backbone",
        default=5,
        validator=validate_int(min_val=1, max_val=100),
    ))

    cfg["lmpnn_temperature"] = float(ask(
        "  Sampling temperature (0.05=conservative, 0.3=diverse)",
        default=0.1,
        validator=validate_float(min_val=0.01, max_val=2.0),
    ))
```

**Step 6d — PXDesign settings (UPGRADED):**

Keep existing import mode AND add local-run mode:
```python
if use_pxdesign_local:
    print_step("Step 6d -- PXDesign settings (local run)")
    cfg["pxdesign_binder_length"] = int(ask(
        "  Binder length (amino acids)",
        default=80,
        validator=validate_int(min_val=30, max_val=300),
    ))

    cfg["pxdesign_n_samples"] = int(ask(
        "  Number of design samples",
        default=1000,
        validator=validate_int(min_val=10, max_val=10000),
    ))

    _, preset_idx = ask_choice(
        "  PXDesign preset",
        ["preview (fast, ~5 min)", "extended (production, ~2 hrs)"],
        default_index=0,
    )
    cfg["pxdesign_preset"] = ["preview", "extended"][preset_idx]

    # Warn about MSA for extended preset
    if cfg["pxdesign_preset"] == "extended":
        print_warn("  Extended preset requires MSA computation (~10-20 min extra).")

    # Hotspots -- reuse existing hotspot value from Step 3
    if cfg.get("hotspots"):
        print_ok(f"  Using hotspots from Step 3: {cfg['hotspots']}")
    else:
        cfg["pxdesign_hotspots"] = ask(
            "  PXDesign hotspot residues (blank=none)",
            default="",
            validator=validate_hotspots,
        )

    cfg["pxdesign_chains"] = ask(
        "  Target chains to include (e.g. 'A' or 'A,B')",
        default=cfg.get("chains", "A"),
        validator=validate_chains,
    )

elif use_pxdesign_import:
    # Existing import-only behavior (unchanged)
    print_step("Step 6d -- PXDesign settings (import)")
    print("  PXDesign results are imported from a local directory containing")
    print("  summary.csv (downloaded from protenix-server.com).")
    cfg["pxdesign_output_dir"] = ask(
        "  PXDesign output directory",
        default="",
        validator=lambda x: True if x.strip() else "path required",
    )
```

### B.5 — Config writer for PXDesign local run (NEW function)

```python
def write_pxdesign_yaml(path: Path, cfg: dict):
    """Write PXDesign input YAML for local run."""
    chains_str = cfg.get("pxdesign_chains", cfg.get("chains", "A"))
    chain_ids = [c.strip() for c in chains_str.split(",")]
    hotspots_str = cfg.get("pxdesign_hotspots", cfg.get("hotspots", ""))
    hotspot_list = parse_hotspots(hotspots_str) if hotspots_str else []

    # Write as YAML (stdlib-only: no PyYAML, write manually)
    lines = [
        f"binder_length: {cfg['pxdesign_binder_length']}",
        "target:",
        f"  file: {cfg['target_pdb']}",
        "  chains:",
    ]
    for cid in chain_ids:
        if hotspot_list:
            hs = ", ".join(str(h) for h in hotspot_list)
            lines.append(f"    {cid}:")
            lines.append(f"      hotspots: [{hs}]")
        else:
            lines.append(f"    {cid}: all")

    path.write_text("\n".join(lines) + "\n")
```

> **Note:** The configurator is stdlib-only (no PyYAML). The YAML must be written
> manually. This follows the BoltzGen YAML generation pattern already in the configurator.

### B.6 — Run script writers (NEW functions)

**`write_run_rfaa(path, cfg):`**

Two-stage script: RFAA backbones -> LigandMPNN sequences.
Follow the conda activation pattern from `write_run_bindcraft()`:

```bash
#!/usr/bin/env bash
# Run RFDiffusionAA + LigandMPNN for {name}
set -euo pipefail

RFAA_DIR="{RFAA_DIR}"
LIGANDMPNN_DIR="{LIGANDMPNN_DIR}"
OUTPUT_DIR="{run_dir}/rfaa/outputs"
LMPNN_DIR="{run_dir}/rfaa/ligandmpnn"
TARGET_PDB="{target_pdb}"

mkdir -p "$OUTPUT_DIR" "$LMPNN_DIR"

# Robust conda init (same 7-location loop)
set +u
... conda init loop ...
conda activate bindmaster_rfaa
set -u

# ============================================================
# Stage 1: RFDiffusionAA — generate backbone PDBs
# ============================================================
echo "=== Stage 1: RFDiffusionAA ==="
cd "$RFAA_DIR"

python run_inference.py \
    inference.input_pdb="$TARGET_PDB" \
    inference.output_prefix="$OUTPUT_DIR/sample" \
    inference.num_designs={n_designs} \
    {ligand_override} \
    diffuser.T={T} \
    contigmap.contigs="['{contigs}']"

BACKBONE_COUNT=$(find "$OUTPUT_DIR" -name "*.pdb" | wc -l)
echo "  -> $BACKBONE_COUNT backbone PDBs generated"

if [[ "$BACKBONE_COUNT" -eq 0 ]]; then
    echo "ERROR: RFAA produced no backbone PDBs"
    exit 1
fi

# ============================================================
# Stage 2: LigandMPNN — design sequences for each backbone
# ============================================================
echo ""
echo "=== Stage 2: LigandMPNN (sequence design) ==="
cd "$LIGANDMPNN_DIR"

SEED=111
for PDB_FILE in "$OUTPUT_DIR"/*.pdb; do
    BASENAME=$(basename "$PDB_FILE" .pdb)
    LMPNN_OUT="$LMPNN_DIR/$BASENAME"
    mkdir -p "$LMPNN_OUT"

    echo "  Designing sequences for $BASENAME..."
    python run.py \
        --seed "$SEED" \
        --pdb_path "$PDB_FILE" \
        --out_folder "$LMPNN_OUT" \
        --model_type "ligand_mpnn" \
        --ligand_mpnn_use_side_chain_context 1 \
        --temperature {lmpnn_temperature} \
        --number_of_batches {lmpnn_seqs_per_backbone}

    SEED=$((SEED + 1))
done

# ============================================================
# Stage 3: Collect sequences into summary CSV
# ============================================================
echo ""
echo "=== Collecting sequences ==="
python -c "
import csv, re, sys
from pathlib import Path

lmpnn_dir = Path('$LMPNN_DIR')
rows = []
for fasta in sorted(lmpnn_dir.rglob('seqs/*.fasta')):
    with open(fasta) as f:
        for line in f:
            if line.startswith('>'):
                header = line.strip()
                seq = next(f).strip()
                # Parse header fields
                conf_m = re.search(r'overall_confidence=([0-9.]+)', header)
                lig_m = re.search(r'ligand_confidence=([0-9.]+)', header)
                name = header.split()[0].lstrip('>')
                rows.append({
                    'design_id': name,
                    'sequence': seq,
                    'length': len(seq),
                    'overall_confidence': conf_m.group(1) if conf_m else '',
                    'ligand_confidence': lig_m.group(1) if lig_m else '',
                    'backbone_pdb': fasta.parent.parent.name,
                    'source': 'rfaa',
                })

if not rows:
    print('WARNING: No sequences found in LigandMPNN output', file=sys.stderr)
    sys.exit(0)

out_csv = Path('$LMPNN_DIR').parent / 'sequences.csv'
with open(out_csv, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f'  -> {len(rows)} sequences written to {out_csv}')
"

echo ""
echo "=== RFAA + LigandMPNN complete ==="
echo "Backbone PDBs:  $OUTPUT_DIR/"
echo "Sequences:      $(dirname "$LMPNN_DIR")/sequences.csv"
```

**`write_run_pxdesign(path, cfg):`**

```bash
#!/usr/bin/env bash
# Run PXDesign for {name}
set -euo pipefail

PXDESIGN_DIR="{PXDESIGN_DIR}"
INPUT_YAML="{run_dir}/pxdesign/input.yaml"
OUTPUT_DIR="{run_dir}/pxdesign/outputs"

# Robust conda init
set +u
... conda init loop ...
conda activate bindmaster_pxdesign
set -u

echo "=== Running PXDesign for {name} ==="

# Validate YAML
pxdesign check-input --yaml "$INPUT_YAML"

# Note: extended preset includes MSA computation (~10-20 min)
pxdesign pipeline \
    --preset {preset} \
    --N_sample {n_samples} \
    --dtype bf16 \
    {fast_ln_flag} \
    -i "$INPUT_YAML" \
    -o "$OUTPUT_DIR"
```

### B.7 — `generate()` function (line ~1149)

Add directory creation and file generation:
```python
if tools_enabled.get("rfaa"):
    (run_dir / "rfaa" / "outputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "rfaa" / "ligandmpnn").mkdir(parents=True, exist_ok=True)
    write_run_rfaa(run_dir / "run_rfaa.sh", cfg)

if tools_enabled.get("pxdesign_local"):
    (run_dir / "pxdesign" / "outputs").mkdir(parents=True, exist_ok=True)
    write_pxdesign_yaml(run_dir / "pxdesign" / "input.yaml", cfg)
    write_run_pxdesign(run_dir / "run_pxdesign.sh", cfg)
```

### B.8 — `write_run_all()` (line ~993)

Add RFAA and PXDesign to the orchestrator, after BindCraft and before Evaluator:
```python
if tools_enabled.get("rfaa"):
    lines += [
        'echo "=== Step: RFAA + LigandMPNN ==="',
        '"$RUN_DIR/run_rfaa.sh"',
        'check_outputs "$RUN_DIR/rfaa/sequences.csv" "RFAA"',
        "",
    ]

if tools_enabled.get("pxdesign_local"):
    lines += [
        'echo "=== Step: PXDesign ==="',
        '"$RUN_DIR/run_pxdesign.sh"',
        'check_outputs "$RUN_DIR/pxdesign/outputs" "PXDesign"',
        "",
    ]
```

### B.9 — `write_run_evaluate()` (line ~1057)

Add PXDesign local outputs to design_dirs collection:
```python
if tools_enabled.get("pxdesign_local"):
    design_dirs.append(("--pxdesign", str(run_dir / "pxdesign" / "outputs")))
```

RFAA outputs are passed via the rfaa/sequences.csv path (evaluator handles this).

### B.10 — `run_pipeline()` (line ~1207)

Add execution blocks for both tools:
```python
if tools_enabled.get("rfaa"):
    print_step("Running RFAA + LigandMPNN")
    rc = subprocess.run(["bash", str(run_dir / "run_rfaa.sh")]).returncode
    ...

if tools_enabled.get("pxdesign_local"):
    print_step("Running PXDesign")
    rc = subprocess.run(["bash", str(run_dir / "run_pxdesign.sh")]).returncode
    ...
```

### B.11 — `print_tree()` (line ~701)

Add RFAA and PXDesign to the ASCII directory tree display.

### Safety notes
- PXDesign import mode is preserved exactly as-is (backward compatible)
- RFAA is completely new — no existing behavior changes
- The configurator is stdlib-only; PXDesign YAML is written manually (no PyYAML)
- All new cfg keys use tool-prefixed names (`rfaa_*`, `pxdesign_*`, `lmpnn_*`)

---

## Part C — Evaluator (`evaluator/evaluator.py`)

### What changes

The lightweight evaluator needs two new parser functions.

### C.1 — New parser: `_parse_pxdesign()` (after line ~435)

```python
def _parse_pxdesign(run_dir: Path) -> list:
    """Read PXDesign summary.csv from pxdesign/ or pxdesign/outputs/."""
    # Check multiple possible locations
    candidates = [
        run_dir / "pxdesign" / "outputs" / "summary.csv",  # local run
        run_dir / "pxdesign" / "summary.csv",               # import mode
    ]
    # Also search subdirectories (PXDesign nests under design_outputs/<task>/)
    pxd_dir = run_dir / "pxdesign" / "outputs"
    if pxd_dir.exists():
        candidates.extend(sorted(pxd_dir.rglob("summary.csv")))
    pxd_dir = run_dir / "pxdesign"
    if pxd_dir.exists():
        candidates.extend(sorted(pxd_dir.rglob("summary.csv")))

    csv_path = None
    for c in candidates:
        if c.exists():
            csv_path = c
            break
    if csv_path is None:
        return []

    rows = _read_csv(csv_path)
    for row in rows:
        row["source"] = "pxdesign"
        row.setdefault("sequence", "")
    if rows:
        _print_ok(f"PXDesign: {len(rows)} designs from {csv_path.name}")
    return rows
```

### C.2 — New parser: `_parse_rfaa()` (after PXDesign parser)

RFAA now produces sequences via LigandMPNN. The parser reads `rfaa/sequences.csv`:

```python
def _parse_rfaa(run_dir: Path) -> list:
    """Read RFAA + LigandMPNN output sequences.csv.

    The RFAA pipeline produces backbone PDBs (stage 1) and then runs
    LigandMPNN to design sequences (stage 2). The combined output is
    collected in rfaa/sequences.csv with columns:
        design_id, sequence, length, overall_confidence,
        ligand_confidence, backbone_pdb, source
    """
    csv_path = run_dir / "rfaa" / "sequences.csv"
    if not csv_path.exists():
        # Fall back: check for backbone PDBs without sequences
        outputs_dir = run_dir / "rfaa" / "outputs"
        if outputs_dir.exists():
            pdb_count = len(list(outputs_dir.glob("*.pdb")))
            if pdb_count:
                _print_warn(
                    f"RFAA: {pdb_count} backbone PDB(s) found but no sequences.csv. "
                    "Run LigandMPNN first (included in run_rfaa.sh)."
                )
        return []

    rows = _read_csv(csv_path)
    for row in rows:
        row["source"] = "rfaa"
        row.setdefault("sequence", "")
    # Filter out rows with no sequence (shouldn't happen after LigandMPNN, but be safe)
    rows = [r for r in rows if r.get("sequence")]
    if rows:
        _print_ok(f"RFAA: {len(rows)} sequences (via LigandMPNN)")
    return rows
```

### C.3 — Wire into main parse block (line ~727-732)

Add after `_parse_bindcraft`:
```python
all_rows.extend(_parse_pxdesign(run_dir))
all_rows.extend(_parse_rfaa(run_dir))
```

### C.4 — Update "no outputs" error message (line ~734-739)

Add the two new expected paths:
```python
print(f"    {run_dir}/pxdesign/outputs/summary.csv (or pxdesign/summary.csv)")
print(f"    {run_dir}/rfaa/sequences.csv")
```

### Safety notes
- Existing parsers are NOT modified
- New parsers follow identical pattern: check dir -> read CSV -> set source -> return list
- RFAA sequences come from LigandMPNN and can be refolded like any other tool

---

## Part D — Evaluator Package (`Evaluator/binder_comparison/`)

### What changes

The full Evaluator package already has `PXDesignExtractor`. Only RFAA needs a new extractor.

### D.1 — Update `SourceTool` type (schema.py line 10)

```python
SourceTool = Literal["bindcraft", "boltzgen", "mosaic", "pxdesign", "rfaa", "unknown"]
```

### D.2 — New `RFAAExtractor` class

Create `Evaluator/binder_comparison/extractors/rfaa.py`:

```python
"""RFAA sequence extractor.

Reads sequences from the RFAA+LigandMPNN combined pipeline output.
Expected input: directory containing sequences.csv (produced by run_rfaa.sh).

If sequences.csv is not found, falls back to listing backbone PDBs
(with empty sequences and a warning).
"""
class RFAAExtractor(SequenceExtractor):
    @property
    def tool_name(self) -> str:
        return "rfaa"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        # Primary: read sequences.csv (LigandMPNN output)
        csv_path = input_dir / "sequences.csv"
        if not csv_path.exists():
            csv_path = input_dir.parent / "sequences.csv"
        if csv_path.exists():
            return self._from_csv(csv_path)
        # Fallback: list backbone PDBs with empty sequences
        return self._from_backbone_pdbs(input_dir)
```

### D.3 — Register in `extractors/__init__.py`

```python
from .rfaa import RFAAExtractor
```

### D.4 — Add `--rfaa` CLI flag to `cli/extract.py`

```python
p.add_argument("--rfaa", metavar="DIR", help="RFAA output directory")
```

And in `run()`:
```python
if args.rfaa:
    print(f"[extract] RFAA: {args.rfaa}")
    extracted = RFAAExtractor().extract(args.rfaa)
    print(f"  -> {len(extracted)} sequences")
    all_binders.extend(extracted)
```

### Safety notes
- PXDesignExtractor is NOT modified (already working)
- New RFAAExtractor follows the exact same pattern as other extractors
- SourceTool literal update is backward-compatible (existing values unchanged)

---

## Implementation Order

```
Step 1: Part C + D -- Evaluator changes (lowest risk, most testable)
         Add _parse_pxdesign(), _parse_rfaa() to evaluator.py
         Add RFAAExtractor to Evaluator package
         Update SourceTool type
         Write tests

Step 2: Part B -- Configurator changes
         Add RFAA wizard steps (including LigandMPNN settings)
         Upgrade PXDesign to local+import modes
         Add run script generators (RFAA two-stage, PXDesign)
         Update generate(), run_pipeline(), run_all
         Write tests (mock-based)

Step 3: Part A -- Installer changes
         Add tool flags, menu entries, install functions
         LigandMPNN installed as part of RFAA
         Add uninstall cases
         Test with --tool rfaa / --tool pxdesign
```

Each step is independently committable and testable.

---

## Run Directory Structure (after Phase 2)

```
runs/<name>/
|-- target/
|   |-- <name>.pdb
|   +-- <name>.cif            (if input was CIF)
|-- mosaic/                    (if enabled)
|   |-- hallucinate.py
|   +-- designs.csv
|-- boltzgen/                  (if enabled)
|   |-- config.yaml
|   +-- outputs/*.csv
|-- bindcraft/                 (if enabled)
|   |-- target_settings.json
|   +-- outputs/*.csv
|-- rfaa/                      (if enabled) <-- NEW
|   |-- outputs/
|   |   |-- sample_0.pdb       (backbone PDB from RFAA)
|   |   |-- sample_1.pdb
|   |   +-- ...
|   |-- ligandmpnn/
|   |   |-- sample_0/
|   |   |   +-- seqs/sample_0_111.fasta
|   |   +-- sample_1/
|   |       +-- seqs/sample_1_111.fasta
|   +-- sequences.csv          (collected from all FASTA files)
|-- pxdesign/                  (if enabled) <-- NEW/UPGRADED
|   |-- input.yaml             (local mode)
|   +-- outputs/
|       |-- design_outputs/<task>/summary.csv
|       +-- design_outputs/<task>/passing-*/
|-- evaluate/                  (if evaluator enabled)
|   |-- sequences.fasta
|   +-- comparison_report/
|-- run_mosaic.sh
|-- run_boltzgen.sh
|-- run_bindcraft.sh
|-- run_rfaa.sh                <-- NEW (two-stage: RFAA + LigandMPNN)
|-- run_pxdesign.sh            <-- NEW (local mode only)
|-- run_evaluate.sh
+-- run_all.sh                 (chains all enabled tools)
```
