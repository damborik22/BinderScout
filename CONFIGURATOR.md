# BindMaster Configurator

Interactive CLI wizard that sets up a protein binder design run in one session.
It asks a series of questions, then writes a self-contained folder under
`~/BindMaster/runs/<name>/` with all config files and ready-to-run shell
scripts for whichever tools you enable.

---

## Prerequisites

The configurator works at any time, but the generated run scripts can only
execute once the relevant tools are installed. Run `install.sh` first:

```bash
bash ~/BindMaster/install.sh          # interactive menu
bash ~/BindMaster/install.sh --tool bindcraft
bash ~/BindMaster/install.sh --tool boltzgen
bash ~/BindMaster/install.sh --tool mosaic
```

The wizard detects which tools are installed and labels them at Step 5.

---

## Running the wizard

```bash
bindmaster-config
```

Or directly:

```bash
python ~/BindMaster/configurator.py
```

---

## Wizard walkthrough

### Step 1 — Project name

```
  Target name: PDL1
```

Used as the run folder name (`~/BindMaster/runs/PDL1/`) and as the
`binder_name` in BindCraft's config. Letters, digits, underscores, hyphens only.

---

### Step 2 — Target structure

```
  [1] PDB file path  (default)
  [2] Amino acid sequence (requires structure prediction first)
```

**Option 1** — enter the path to any existing `.pdb` file.

**Option 2** — the wizard prints ColabFold instructions, then prompts for
the predicted `.pdb` once you have it.

---

### Step 3 — Target details

```
  Chain(s) to target (e.g. A or A,B) [A]:
  Hotspot residues (e.g. 56 or 1-10,20, blank=auto) []:
```

After this step the wizard automatically extracts the target sequence from
the primary chain's CA atoms (needed for Mosaic):

```
  Auto-extracted sequence for chain A: MNIFEMLRIDEG... (278 aa)
```

**Hotspot formats accepted:**
- single residue: `56`
- range: `1-10`
- mix: `1-10,20,45`
- blank → tool decides

---

### Step 4 — Binder settings

```
  Minimum binder length [65]:
  Maximum binder length [150]:
  Number of top/final designs [10]:
```

`n_designs` maps to the **final output count** for every tool:

| Tool | How it is used |
|------|---------------|
| BindCraft | `number_of_final_designs` in `target_settings.json` |
| BoltzGen | `--budget` (final diversity-optimised set) |
| Mosaic | `TOP_K` (designs to refold and export as PDB) |

---

### Step 5 — Tool selection

```
  Mosaic    [installed]
  Enable Mosaic? [y/N]:

  BoltzGen  [installed]
  Enable BoltzGen? [y/N]:

  BindCraft [installed]
  Enable BindCraft? [Y/n]:
```

Each tool shows its current installation status.

---

### Step 6 — Per-tool settings

Only shown for enabled tools.

**BindCraft (6a)**

```
  Filter preset:
    [1] default_filters  (default)
    [2] no_filters
    [3] peptide_filters
    ...

  Advanced preset:
    [1] betasheet_4stage_multimer
    [2] default_4stage_multimer  (default)
    ...
```

Preset lists are read live from `~/BindMaster/BindCraft/settings_filters/`
and `settings_advanced/`. The chosen JSON files are **copied** into the run
folder so the run is self-contained.

**BoltzGen (6b)**

```
  Binder type:
    [1] protein-anything — de-novo protein binder (default)
    [2] nanobody — redesign CDR loops of four scaffold nanobodies

  Final designs (--budget):    10  [from Step 4]
  Intermediate designs (--num_designs, min 10 000) [10000]:
```

**protein-anything (default)** — designs a new protein chain of random length
within your min/max range.

**nanobody** — starts from four real nanobody scaffolds (caplacizumab 7eow,
vobarilizumab 7xl0, 8coh, 8z8v) and redesigns their CDR H1/H2/H3 loops to
bind your target. The scaffold YAML and CIF files are copied into
`boltzgen/nanobody_scaffolds/` and referenced from `config.yaml`.

BoltzGen generates a large pool of intermediate designs, then diversity-filters
them down to `--budget` final designs. The minimum meaningful pool is 10 000.

**Mosaic (6c)**

```
  Top designs (TOP_K):  10  [from Step 4]
  Sequence (278 aa): MNIFEMLRIDEG...
  Use this sequence? [Y/n]:
```

If the auto-extraction failed, you will be asked to paste the sequence manually.
Everything else (optimizer steps, loss weights) is handled interactively by
the script itself at run time.

---

### Step 7 — Preview

```
  Run folder:    ~/BindMaster/runs/PDL1
  Target PDB:    /path/to/PDL1.pdb
  Chains:        A  |  Hotspots: 56
  Binder length: 65–150  |  Top designs: 10
  Tools:         boltzgen, bindcraft
  BoltzGen:      10,000 intermediate → 10 final
  BindCraft:     filters=default_filters  advanced=default_4stage_multimer

  PDL1/
  ├── target/
  │   └── <target>.pdb
  ├── boltzgen/
  │   ├── config.yaml
  │   └── outputs/
  ├── bindcraft/
  │   ├── target_settings.json
  │   ├── filters.json
  │   ├── advanced.json
  │   └── outputs/
  ├── run_boltzgen.sh
  ├── run_bindcraft.sh
  └── run_all.sh

Generate configs and scripts now? [Y/n]:
```

Nothing is written until you confirm here.

---

## Generated run folder

```
~/BindMaster/runs/<name>/
├── target/
│   └── <name>.pdb              ← copy of your input PDB
│
├── mosaic/                     ← if Mosaic was enabled
│   └── hallucinate.py          ← copy of hallucinate_Version7.py with
│                                  TARGET_SEQUENCE, TOP_K, MIN/MAX_LENGTH
│                                  injected; run interactively
│
├── boltzgen/                   ← if BoltzGen was enabled
│   ├── config.yaml             ← design spec: binder length range, target
│   │                              PDB + chain + optional binding site
│   └── outputs/
│
├── bindcraft/                  ← if BindCraft was enabled
│   ├── target_settings.json    ← target, chains, hotspots, lengths, n_designs
│   ├── filters.json            ← copy of chosen filter preset
│   ├── advanced.json           ← copy of chosen advanced preset
│   └── outputs/
│
├── run_mosaic.sh
├── run_boltzgen.sh
├── run_bindcraft.sh
└── run_all.sh
```

---

## Running the generated scripts

```bash
bash ~/BindMaster/runs/PDL1/run_mosaic.sh      # interactive prompts at start
bash ~/BindMaster/runs/PDL1/run_boltzgen.sh
bash ~/BindMaster/runs/PDL1/run_bindcraft.sh

bash ~/BindMaster/runs/PDL1/run_all.sh         # full pipeline in sequence
```

`run_all.sh` checks that each tool produced output before moving to the next
step and stops with a warning if it did not.

---

## Tool-specific details

### Mosaic

`hallucinate.py` is a copy of `hallucinate_Version7.py` with three values
pre-filled as module-level constants:

```python
TOP_K = 10                         # designs to refold and export PDB
TARGET_SEQUENCE = "MNIFEMLRID..."  # used as default in the interactive prompt
MIN_LENGTH = 65                    # used as the low end of the length-scan default
MAX_LENGTH = 150                   # used as the high end of the length-scan default
```

When you run `run_mosaic.sh`, the script activates the Mosaic uv venv, `cd`s
to the `mosaic/` directory, and launches `hallucinate.py` interactively.
You will still be prompted for:
- binder length(s) — default range is `MIN_LENGTH–MAX_LENGTH step 20`
- number of intermediate designs
- optional hotspot residues (0-based indices)
- optional resume checkpoint

Mosaic writes its outputs directly into `mosaic/`:
- `designs.txt` / `designs.csv` — all candidates with metrics
- `structures_<len>aa_<n>_top<k>/` — PDB, PAE, pLDDT files for top designs

### BoltzGen

`config.yaml` uses the [BoltzGen design spec format](https://github.com/HannesStark/boltzgen).

**protein-anything mode:**
- Binder: chain B, random length in `min_length..max_length`
- Target: loaded from the copied PDB with the specified chain(s)
- Hotspots (if set): `binding_types` block with comma-expanded residue numbers

**nanobody mode:**
- Binder: `- file: path: [nanobody_scaffolds/7eow.yaml, ...]` — four CDR-redesign scaffolds
- The `boltzgen/nanobody_scaffolds/` folder is populated with 4 × YAML + CIF copied from `BoltzGen/example/nanobody_scaffolds/`
- Target specification and hotspots work identically to protein-anything mode
- Binder length settings from Step 4 are ignored (CDR lengths are defined in the scaffolds)

`run_boltzgen.sh` invokes:
```bash
boltzgen run config.yaml \
    --output outputs/ \
    --protocol protein-anything \
    --num_designs 10000 \
    --budget 10
```

### BindCraft

`target_settings.json` follows the standard BindCraft schema. `filters.json`
and `advanced.json` are independent copies of the chosen presets.

`run_bindcraft.sh` activates the `BindCraft` conda env, `cd`s to
`~/BindMaster/BindCraft`, and runs `bindcraft.py` with absolute paths to
all three config files.

---

## Environment details

| Tool | Runtime | Activated by |
|------|---------|-------------|
| BindCraft | conda env `BindCraft` | `conda activate BindCraft` |
| BoltzGen | conda env `BoltzGen` | `conda activate BoltzGen` |
| Mosaic | uv venv `~/BindMaster/Mosaic/.venv/` | venv python called directly |

---

## Re-running the wizard for the same target

If `~/BindMaster/runs/<name>/` already exists, the wizard warns you and asks
whether to overwrite. Answering `n` exits without writing anything.
