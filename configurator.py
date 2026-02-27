#!/usr/bin/env python3
"""
BindMaster Configurator — interactive CLI wizard for setting up
protein binder design runs (Mosaic → BoltzGen → BindCraft).

Usage:
    python configurator.py
    bindmaster-config          # via shortcut
"""

import json
import re
import shutil
import sys
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────

BINDMASTER_DIR = Path.home() / "BindMaster"
BINDCRAFT_DIR  = BINDMASTER_DIR / "BindCraft"
BOLTZGEN_DIR   = BINDMASTER_DIR / "BoltzGen"
MOSAIC_DIR     = BINDMASTER_DIR / "Mosaic"
RUNS_DIR       = BINDMASTER_DIR / "runs"
FILTERS_DIR    = BINDCRAFT_DIR / "settings_filters"
ADVANCED_DIR   = BINDCRAFT_DIR / "settings_advanced"
CONDA_ENVS_DIR = Path.home() / "miniconda3" / "envs"
MOSAIC_VENV    = MOSAIC_DIR / ".venv"
MOSAIC_HALLUCINATE_SRC = (
    MOSAIC_DIR / "examples" / "bindmaster_example" / "hallucinate_Version7.py"
)
NANOBODY_SCAFFOLDS_SRC = BOLTZGEN_DIR / "example" / "nanobody_scaffolds"
NANOBODY_SCAFFOLD_NAMES = ["7eow", "7xl0", "8coh", "8z8v"]

# ─── Amino-acid 3→1 mapping ──────────────────────────────────────────────────

AA3TO1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    # common non-standard aliases
    "MSE": "M", "HSD": "H", "HSE": "H", "HSP": "H",
    "SEC": "U", "PYL": "O",
}

# ─── Install detection ───────────────────────────────────────────────────────

def detect_installs() -> dict:
    """
    BindCraft / BoltzGen: check for their conda env directory.
    Mosaic: check for the uv venv python binary.
    """
    return {
        "bindcraft": (CONDA_ENVS_DIR / "BindCraft").is_dir(),
        "boltzgen":  (CONDA_ENVS_DIR / "BoltzGen").is_dir(),
        "mosaic":    (MOSAIC_VENV / "bin" / "python").exists(),
    }

# ─── Helpers ─────────────────────────────────────────────────────────────────

def banner():
    print()
    print("=" * 60)
    print("  BindMaster Configurator")
    print("  Protein Binder Design Pipeline Setup Wizard")
    print("=" * 60)
    print()


def ask(prompt, default=None, validator=None):
    """Prompt the user for input with optional default and validator."""
    display = f"{prompt}"
    if default is not None:
        display += f" [{default}]"
    display += ": "
    while True:
        raw = input(display).strip()
        if raw == "" and default is not None:
            raw = str(default)
        if raw == "" and default is None:
            print("  (required — please enter a value)")
            continue
        if validator:
            result = validator(raw)
            if result is not True:
                print(f"  {result}")
                continue
        return raw


def ask_yn(prompt, default=True):
    """Prompt for yes/no, returns bool."""
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{hint}]: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def ask_choice(prompt, choices, default_index=0):
    """Present a numbered list; returns (index, choice_string)."""
    print(f"\n{prompt}")
    for i, c in enumerate(choices):
        marker = " (default)" if i == default_index else ""
        print(f"  [{i+1}] {c}{marker}")
    while True:
        raw = input(f"  Choice [1-{len(choices)}] (default {default_index+1}): ").strip()
        if raw == "":
            return default_index, choices[default_index]
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return idx, choices[idx]
        print(f"  Please enter a number between 1 and {len(choices)}.")


# ─── Validators ──────────────────────────────────────────────────────────────

def validate_name(s):
    if re.fullmatch(r"[A-Za-z0-9_\-]+", s):
        return True
    return "Name must contain only letters, digits, underscores, and hyphens (no spaces)."


def validate_int(min_val=None, max_val=None):
    def _v(s):
        if not s.isdigit():
            return "Please enter a whole number."
        n = int(s)
        if min_val is not None and n < min_val:
            return f"Value must be at least {min_val}."
        if max_val is not None and n > max_val:
            return f"Value must be at most {max_val}."
        return True
    return _v


def validate_hotspots(s):
    if s == "":
        return True
    pattern = r"^(\d+(-\d+)?)(\s*,\s*(\d+(-\d+)?))*$"
    if re.fullmatch(pattern, s.replace(" ", "")):
        return True
    return "Use format like: 56  or  1-10,20  or leave blank for auto."


def validate_chains(s):
    if re.fullmatch(r"[A-Za-z,]+", s):
        return True
    return "Chains should be letter(s), e.g. A or A,B"


def validate_pdb_path(s):
    p = Path(s).expanduser()
    if not p.exists():
        return f"File not found: {p}"
    if p.suffix.lower() != ".pdb":
        return "File must have a .pdb extension."
    return True


def validate_sequence(s):
    valid = set("ACDEFGHIKLMNPQRSTVWY")
    bad = set(s.upper()) - valid
    if bad:
        return f"Invalid amino acid characters: {''.join(sorted(bad))}"
    if len(s) < 5:
        return "Sequence seems too short (< 5 residues)."
    return True


# ─── PDB / hotspot utilities ─────────────────────────────────────────────────

def extract_sequence_from_pdb(pdb_path: str, chain_id: str) -> str | None:
    """
    Extract the amino-acid sequence for chain_id from a PDB file using CA atoms.
    Returns a 1-letter string, or None on failure.
    """
    seen: dict = {}   # (resSeq, iCode) → 1-letter, insertion-order
    try:
        with open(Path(pdb_path).expanduser()) as f:
            for line in f:
                if line[:4] != "ATOM":
                    continue
                if line[12:16].strip() != "CA":
                    continue
                if line[21].strip().upper() != chain_id.upper():
                    continue
                res_name = line[17:20].strip().upper()
                key = (line[22:26].strip(), line[26].strip())
                if key not in seen:
                    seen[key] = AA3TO1.get(res_name, "X")
    except OSError:
        return None
    return "".join(seen.values()) if seen else None


def parse_hotspots(hotspot_str: str) -> list:
    """Parse '1-10,20' → [1, 2, ..., 10, 20]. Returns [] for blank."""
    if not hotspot_str:
        return []
    result = []
    for part in hotspot_str.replace(" ", "").split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            result.extend(range(int(lo), int(hi) + 1))
        else:
            result.append(int(part))
    return result


def hotspots_to_boltzgen_str(hotspot_str: str) -> str:
    """Expand '1-10,20' → '1,2,3,4,5,6,7,8,9,10,20' for BoltzGen YAML."""
    return ",".join(str(n) for n in parse_hotspots(hotspot_str))


# ─── Directory / preset helpers ───────────────────────────────────────────────

def list_presets(directory, suffix=".json"):
    """Return sorted list of preset stem names in a directory."""
    d = Path(directory)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob(f"*{suffix}"))


def print_tree(run_dir: Path, tools_enabled: dict, cfg: dict | None = None):
    """Print an ASCII tree of what will be created."""
    name = run_dir.name
    print(f"\n  {name}/")
    print(f"  ├── target/")
    print(f"  │   └── <target>.pdb")
    if tools_enabled.get("mosaic"):
        print(f"  ├── mosaic/")
        print(f"  │   └── hallucinate.py")
    if tools_enabled.get("boltzgen"):
        nanobody = cfg and cfg.get("boltzgen_mode") == "nanobody"
        print(f"  ├── boltzgen/")
        if nanobody:
            print(f"  │   ├── nanobody_scaffolds/  ← 4 × .yaml + .cif")
        print(f"  │   ├── config.yaml")
        print(f"  │   └── outputs/")
    if tools_enabled.get("bindcraft"):
        print(f"  ├── bindcraft/")
        print(f"  │   ├── target_settings.json")
        print(f"  │   ├── filters.json")
        print(f"  │   ├── advanced.json")
        print(f"  │   └── outputs/")
    scripts = []
    if tools_enabled.get("mosaic"):
        scripts.append("run_mosaic.sh")
    if tools_enabled.get("boltzgen"):
        scripts.append("run_boltzgen.sh")
    if tools_enabled.get("bindcraft"):
        scripts.append("run_bindcraft.sh")
    scripts.append("run_all.sh")
    for i, s in enumerate(scripts):
        prefix = "└──" if i == len(scripts) - 1 else "├──"
        print(f"  {prefix} {s}")
    print()


# ─── Config writers ───────────────────────────────────────────────────────────

def write_bindcraft_target(path: Path, cfg: dict):
    settings = {
        "design_path": str(cfg["run_dir"] / "bindcraft" / "outputs") + "/",
        "binder_name": cfg["name"],
        "starting_pdb": str(cfg["target_pdb"]),
        "chains": cfg["chains"],
        "target_hotspot_residues": cfg["hotspots"] if cfg["hotspots"] else None,
        "lengths": [cfg["min_length"], cfg["max_length"]],
        "number_of_final_designs": cfg["n_designs"],
    }
    path.write_text(json.dumps(settings, indent=4))


def copy_bindcraft_preset(src_dir: Path, stem: str, dest: Path):
    shutil.copy2(src_dir / f"{stem}.json", dest)


def write_boltzgen_yaml(path: Path, cfg: dict):
    """
    Generate a BoltzGen design-specification YAML.

    protein mode  — designed protein chain with a length range (default)
    nanobody mode — four CDR-redesign scaffold YAMLs instead of a free chain
    """
    target_pdb = str(cfg["target_pdb"])
    chain_ids  = [c.strip() for c in cfg["chains"].split(",") if c.strip()]
    nanobody   = cfg.get("boltzgen_mode") == "nanobody"

    lines = [
        f"# BoltzGen design specification for {cfg['name']}",
        f"# Mode: {'nanobody scaffold CDR redesign' if nanobody else 'de-novo protein binder'}",
        f"# Generated by BindMaster Configurator",
        f"#",
        f"# Run with:",
        f"#   boltzgen run config.yaml \\",
        f"#       --output outputs/ \\",
        f"#       --protocol protein-anything \\",
        f"#       --num_designs {cfg['boltzgen_intermediate']} \\",
        f"#       --budget {cfg['n_designs']}",
        f"",
        f"entities:",
    ]

    if nanobody:
        lines += [
            f"  # Nanobody scaffolds: CDR loops (H1/H2/H3) will be redesigned",
            f"  - file:",
            f"      path:",
        ]
        for n in NANOBODY_SCAFFOLD_NAMES:
            lines.append(f"        - nanobody_scaffolds/{n}.yaml")
    else:
        lines += [
            f"  # Designed binder chain: uniform random length in the given range",
            f"  - protein:",
            f"      id: B",
            f"      sequence: {cfg['min_length']}..{cfg['max_length']}",
        ]

    lines += [
        f"",
        f"  # Target protein loaded from the copied PDB",
        f"  - file:",
        f"      path: \"{target_pdb}\"",
        f"      include:",
    ]

    for c in chain_ids:
        lines.append(f"        - chain:")
        lines.append(f"            id: {c}")

    if cfg["hotspots"]:
        binding_str = hotspots_to_boltzgen_str(cfg["hotspots"])
        lines.append(f"      binding_types:")
        for c in chain_ids:
            lines.append(f"        - chain:")
            lines.append(f"            id: {c}")
            lines.append(f"            binding: {binding_str}")

    lines.append(f"      structure_groups: \"all\"")
    lines.append("")

    path.write_text("\n".join(lines))


def copy_nanobody_scaffolds(dest_dir: Path):
    """
    Copy the four nanobody scaffold pairs (YAML + CIF) from the BoltzGen
    example directory into dest_dir.  The scaffold YAMLs reference their
    CIF files with bare filenames, so both must sit in the same folder.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in NANOBODY_SCAFFOLD_NAMES:
        for ext in (".yaml", ".cif"):
            src = NANOBODY_SCAFFOLDS_SRC / f"{name}{ext}"
            shutil.copy2(src, dest_dir / f"{name}{ext}")


def write_mosaic_hallucinate(path: Path, cfg: dict):
    """
    Copy hallucinate_Version7.py and inject run parameters:
      - TARGET_SEQUENCE → used as default in the interactive sequence prompt
      - TOP_K           → number of top designs to refold
      - MIN_LENGTH / MAX_LENGTH → default binder length range
    """
    content = MOSAIC_HALLUCINATE_SRC.read_text()

    # 1. Replace TOP_K and inject constants block
    old_top_k = "TOP_K = 5  # how many designs to refold and export PDB for"
    new_top_k = (
        f"TOP_K = {cfg['n_designs']}  # how many designs to refold and export PDB for\n"
        f"\n"
        f"# ── Injected by BindMaster Configurator ──────────────────────────────────\n"
        f"TARGET_SEQUENCE = {repr(cfg['target_sequence'])}\n"
        f"MIN_LENGTH = {cfg['min_length']}\n"
        f"MAX_LENGTH = {cfg['max_length']}\n"
        f"# ──────────────────────────────────────────────────────────────────────────"
    )
    if old_top_k in content:
        content = content.replace(old_top_k, new_top_k)
    else:
        print("  WARNING: could not inject TOP_K block — please edit hallucinate.py manually.")

    # 2. Set TARGET_SEQUENCE as default in the interactive sequence prompt
    old_seq = (
        '    target_sequence = _read_sequence(\n'
        '        "Target protein sequence:",\n'
        '    )'
    )
    new_seq = (
        '    target_sequence = _read_sequence(\n'
        '        "Target protein sequence:",\n'
        '        default=TARGET_SEQUENCE,\n'
        '    )'
    )
    if old_seq in content:
        content = content.replace(old_seq, new_seq)
    else:
        print("  WARNING: could not inject default sequence — please edit hallucinate.py manually.")

    # 3. Set MIN/MAX_LENGTH as the default binder length range
    old_len = "        default_range=(40, 100, 20),"
    new_len = "        default_range=(MIN_LENGTH, MAX_LENGTH, 20),"
    if old_len in content:
        content = content.replace(old_len, new_len)
    else:
        print("  WARNING: could not inject length range — please edit hallucinate.py manually.")

    path.write_text(content)


def write_run_bindcraft(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    content = f"""\
#!/usr/bin/env bash
# Run BindCraft for {cfg['name']}
# Generated by BindMaster Configurator
set -euo pipefail

CONDA_BASE="$HOME/miniconda3"
BINDCRAFT_DIR="{BINDCRAFT_DIR}"
SETTINGS="{run_dir}/bindcraft/target_settings.json"
FILTERS="{run_dir}/bindcraft/filters.json"
ADVANCED="{run_dir}/bindcraft/advanced.json"

source "${{CONDA_BASE}}/etc/profile.d/conda.sh"
conda activate BindCraft
cd "$BINDCRAFT_DIR"

echo "=== Running BindCraft for {cfg['name']} ==="
python -u ./bindcraft.py \\
    --settings "$SETTINGS" \\
    --filters  "$FILTERS" \\
    --advanced "$ADVANCED"
"""
    path.write_text(content)
    path.chmod(0o755)


def write_run_boltzgen(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    content = f"""\
#!/usr/bin/env bash
# Run BoltzGen for {cfg['name']}
# Generated by BindMaster Configurator
set -euo pipefail

CONDA_BASE="$HOME/miniconda3"
CONFIG="{run_dir}/boltzgen/config.yaml"
OUTPUT_DIR="{run_dir}/boltzgen/outputs"

source "${{CONDA_BASE}}/etc/profile.d/conda.sh"
conda activate BoltzGen

echo "=== Running BoltzGen for {cfg['name']} ==="
boltzgen run "$CONFIG" \\
    --output "$OUTPUT_DIR" \\
    --protocol protein-anything \\
    --num_designs {cfg['boltzgen_intermediate']} \\
    --budget {cfg['n_designs']}
"""
    path.write_text(content)
    path.chmod(0o755)


def write_run_mosaic(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    mosaic_python = MOSAIC_VENV / "bin" / "python"
    content = f"""\
#!/usr/bin/env bash
# Run Mosaic for {cfg['name']}
# Generated by BindMaster Configurator
set -euo pipefail

MOSAIC_PYTHON="{mosaic_python}"
MOSAIC_DIR="{run_dir}/mosaic"

if [[ ! -x "$MOSAIC_PYTHON" ]]; then
    echo "ERROR: Mosaic uv venv not found at $MOSAIC_PYTHON" >&2
    echo "Run: bash {BINDMASTER_DIR}/install.sh --tool mosaic" >&2
    exit 1
fi

echo "=== Running Mosaic for {cfg['name']} ==="
cd "$MOSAIC_DIR"
"$MOSAIC_PYTHON" hallucinate.py
"""
    path.write_text(content)
    path.chmod(0o755)


def write_run_all(path: Path, cfg: dict, tools_enabled: dict):
    run_dir = cfg["run_dir"]
    lines = [
        "#!/usr/bin/env bash",
        f"# Run all enabled tools for {cfg['name']} in order: Mosaic → BoltzGen → BindCraft",
        "# Generated by BindMaster Configurator",
        "set -euo pipefail",
        "",
        f'RUN_DIR="{run_dir}"',
        "",
        "check_outputs() {",
        '    local dir="$1" tool="$2"',
        '    if [ -z "$(ls -A "$dir" 2>/dev/null)" ]; then',
        '        echo "WARNING: $tool produced no output in $dir — stopping pipeline." >&2',
        "        exit 1",
        "    fi",
        "}",
        "",
    ]

    if tools_enabled.get("mosaic"):
        lines += [
            'echo "=== Step: Mosaic ==="',
            '"$RUN_DIR/run_mosaic.sh"',
            'if [[ ! -f "$RUN_DIR/mosaic/designs.csv" ]]; then',
            '    echo "WARNING: Mosaic produced no designs.csv — stopping pipeline." >&2',
            "    exit 1",
            "fi",
            "",
        ]

    if tools_enabled.get("boltzgen"):
        lines += [
            'echo "=== Step: BoltzGen ==="',
            '"$RUN_DIR/run_boltzgen.sh"',
            'check_outputs "$RUN_DIR/boltzgen/outputs" "BoltzGen"',
            "",
        ]

    if tools_enabled.get("bindcraft"):
        lines += [
            'echo "=== Step: BindCraft ==="',
            '"$RUN_DIR/run_bindcraft.sh"',
            'check_outputs "$RUN_DIR/bindcraft/outputs" "BindCraft"',
            "",
        ]

    lines += ['echo ""', 'echo "=== Pipeline complete! ==="']

    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o755)


# ─── Generation ───────────────────────────────────────────────────────────────

def generate(cfg: dict, tools_enabled: dict):
    run_dir: Path = cfg["run_dir"]

    # Create directories
    (run_dir / "target").mkdir(parents=True, exist_ok=True)
    if tools_enabled.get("mosaic"):
        (run_dir / "mosaic").mkdir(parents=True, exist_ok=True)
    if tools_enabled.get("boltzgen"):
        (run_dir / "boltzgen" / "outputs").mkdir(parents=True, exist_ok=True)
    if tools_enabled.get("bindcraft"):
        (run_dir / "bindcraft" / "outputs").mkdir(parents=True, exist_ok=True)

    # Copy target PDB
    src_pdb = Path(cfg["target_pdb_src"]).expanduser().resolve()
    dest_pdb = run_dir / "target" / f"{cfg['name']}.pdb"
    shutil.copy2(src_pdb, dest_pdb)
    cfg["target_pdb"] = dest_pdb

    if tools_enabled.get("bindcraft"):
        write_bindcraft_target(run_dir / "bindcraft" / "target_settings.json", cfg)
        copy_bindcraft_preset(FILTERS_DIR, cfg["filter_preset"],
                              run_dir / "bindcraft" / "filters.json")
        copy_bindcraft_preset(ADVANCED_DIR, cfg["advanced_preset"],
                              run_dir / "bindcraft" / "advanced.json")
        write_run_bindcraft(run_dir / "run_bindcraft.sh", cfg)

    if tools_enabled.get("boltzgen"):
        if cfg.get("boltzgen_mode") == "nanobody":
            copy_nanobody_scaffolds(run_dir / "boltzgen" / "nanobody_scaffolds")
        write_boltzgen_yaml(run_dir / "boltzgen" / "config.yaml", cfg)
        write_run_boltzgen(run_dir / "run_boltzgen.sh", cfg)

    if tools_enabled.get("mosaic"):
        write_mosaic_hallucinate(run_dir / "mosaic" / "hallucinate.py", cfg)
        write_run_mosaic(run_dir / "run_mosaic.sh", cfg)

    write_run_all(run_dir / "run_all.sh", cfg, tools_enabled)


# ─── Wizard ───────────────────────────────────────────────────────────────────

def wizard():
    banner()

    # ── Step 1: Project name ──────────────────────────────────────────────────
    print("Step 1: Project name")
    print("  This will be used as the run folder name and binder name.")
    name = ask("  Target name", validator=validate_name)
    run_dir = RUNS_DIR / name

    if run_dir.exists():
        print(f"\n  WARNING: Run folder already exists: {run_dir}")
        if not ask_yn("  Overwrite existing run folder?", default=False):
            print("  Aborted.")
            sys.exit(0)

    # ── Step 2: Target structure ──────────────────────────────────────────────
    print("\nStep 2: Target structure")
    _, input_type = ask_choice(
        "How will you provide the target structure?",
        ["PDB file path", "Amino acid sequence (requires structure prediction first)"],
        default_index=0,
    )

    if "sequence" in input_type.lower():
        print()
        print("  To use an amino acid sequence, you first need to predict its structure.")
        print("  Recommended tool: ColabFold — https://colab.research.google.com/github/")
        print("    sokrypton/ColabFold/blob/main/AlphaFold2.ipynb")
        print()
        print("  Steps:")
        print("    1. Go to the ColabFold link above")
        print("    2. Paste your sequence in the 'query_sequence' field")
        print("    3. Run the notebook and download the best-ranked .pdb file")
        print("    4. Come back here and provide the .pdb path below")
        print()

    target_pdb_src = ask("  Path to target .pdb file", validator=validate_pdb_path)

    # ── Step 3: Target details ────────────────────────────────────────────────
    print("\nStep 3: Target details")
    chains = ask("  Chain(s) to target (e.g. A or A,B)", default="A",
                 validator=validate_chains)
    hotspots = ask(
        "  Hotspot residues (e.g. 56 or 1-10,20, blank=auto)",
        default="",
        validator=validate_hotspots,
    )

    # Auto-extract target sequence from the primary chain (needed for Mosaic)
    primary_chain = chains.split(",")[0].strip()
    target_sequence = extract_sequence_from_pdb(target_pdb_src, primary_chain)
    if target_sequence:
        print(f"  Auto-extracted sequence for chain {primary_chain}: "
              f"{target_sequence[:50]}{'...' if len(target_sequence) > 50 else ''} "
              f"({len(target_sequence)} aa)")

    # ── Step 4: Binder settings ───────────────────────────────────────────────
    print("\nStep 4: Binder settings")
    min_length = int(ask("  Minimum binder length", default=65,
                         validator=validate_int(min_val=10, max_val=500)))
    max_length = int(ask("  Maximum binder length", default=150,
                         validator=validate_int(min_val=10, max_val=500)))
    if max_length < min_length:
        print("  WARNING: max length < min length — swapping values.")
        min_length, max_length = max_length, min_length
    n_designs = int(ask("  Number of top/final designs", default=10,
                        validator=validate_int(min_val=1)))

    # ── Step 5: Tool selection ────────────────────────────────────────────────
    print("\nStep 5: Tool selection")
    installed = detect_installs()

    def _tag(key):
        return "installed" if installed[key] else "NOT installed — run install.sh first"

    print(f"  Mosaic    [{_tag('mosaic')}]")
    use_mosaic = ask_yn("  Enable Mosaic?", default=False)
    print(f"  BoltzGen  [{_tag('boltzgen')}]")
    use_boltzgen = ask_yn("  Enable BoltzGen?", default=False)
    print(f"  BindCraft [{_tag('bindcraft')}]")
    use_bindcraft = ask_yn("  Enable BindCraft?", default=True)

    tools_enabled = {
        "mosaic": use_mosaic,
        "boltzgen": use_boltzgen,
        "bindcraft": use_bindcraft,
    }

    if not any(tools_enabled.values()):
        print("\n  No tools enabled — nothing to generate. Exiting.")
        sys.exit(0)

    # ── Step 6: Per-tool settings ─────────────────────────────────────────────
    cfg: dict = {
        "name": name,
        "run_dir": run_dir,
        "target_pdb_src": target_pdb_src,
        "target_pdb": None,           # set in generate() after PDB copy
        "target_sequence": target_sequence or "",
        "chains": chains,
        "hotspots": hotspots.strip() if hotspots.strip() else None,
        "min_length": min_length,
        "max_length": max_length,
        "n_designs": n_designs,
        # tool-specific
        "filter_preset": "default_filters",
        "advanced_preset": "default_4stage_multimer",
        "boltzgen_mode": "protein",
        "boltzgen_intermediate": 10000,
    }

    if use_bindcraft:
        print("\nStep 6a: BindCraft settings")
        filter_presets = list_presets(FILTERS_DIR)
        if filter_presets:
            default_fi = (filter_presets.index("default_filters")
                          if "default_filters" in filter_presets else 0)
            _, cfg["filter_preset"] = ask_choice(
                "  Filter preset:", filter_presets, default_index=default_fi)
        else:
            print(f"  WARNING: No filter presets found in {FILTERS_DIR}")

        advanced_presets = list_presets(ADVANCED_DIR)
        if advanced_presets:
            default_ai = (advanced_presets.index("default_4stage_multimer")
                          if "default_4stage_multimer" in advanced_presets else 0)
            _, cfg["advanced_preset"] = ask_choice(
                "  Advanced preset:", advanced_presets, default_index=default_ai)
        else:
            print(f"  WARNING: No advanced presets found in {ADVANCED_DIR}")

    if use_boltzgen:
        print("\nStep 6b: BoltzGen settings")
        _, mode_choice = ask_choice(
            "  Binder type:",
            ["protein-anything — de-novo protein binder (default)",
             "nanobody — redesign CDR loops of four scaffold nanobodies"],
            default_index=0,
        )
        cfg["boltzgen_mode"] = "nanobody" if "nanobody" in mode_choice else "protein"
        if cfg["boltzgen_mode"] == "nanobody":
            print(f"  Scaffolds: {', '.join(NANOBODY_SCAFFOLD_NAMES)}")
            print(f"  (will be copied to boltzgen/nanobody_scaffolds/)")
        print(f"  Final designs (--budget):    {n_designs}  [from Step 4]")
        cfg["boltzgen_intermediate"] = int(ask(
            "  Intermediate designs (--num_designs, min 10 000)", default=10000,
            validator=validate_int(min_val=10000)))

    if use_mosaic:
        print("\nStep 6c: Mosaic settings")
        print(f"  Top designs (TOP_K):  {n_designs}  [from Step 4]")
        if not target_sequence:
            print("  Could not auto-extract target sequence from PDB.")
            cfg["target_sequence"] = ask(
                "  Target amino-acid sequence (chain {primary_chain})",
                validator=validate_sequence)
        else:
            seq_preview = target_sequence[:60] + ("..." if len(target_sequence) > 60 else "")
            print(f"  Sequence ({len(target_sequence)} aa): {seq_preview}")
            if not ask_yn("  Use this sequence?", default=True):
                cfg["target_sequence"] = ask(
                    "  Enter target sequence", validator=validate_sequence)

    # ── Step 7: Preview ───────────────────────────────────────────────────────
    print("\nStep 7: Preview")
    print(f"  Run folder:    {run_dir}")
    print(f"  Target PDB:    {target_pdb_src}")
    print(f"  Chains:        {chains}  |  Hotspots: {hotspots or '(auto)'}")
    print(f"  Binder length: {min_length}–{max_length}  |  Top designs: {n_designs}")
    enabled_list = [t for t, v in tools_enabled.items() if v]
    print(f"  Tools:         {', '.join(enabled_list)}")
    if use_bindcraft:
        print(f"  BindCraft:     filters={cfg['filter_preset']}  "
              f"advanced={cfg['advanced_preset']}")
    if use_boltzgen:
        mode_label = "nanobody CDR redesign" if cfg["boltzgen_mode"] == "nanobody" else "de-novo protein"
        print(f"  BoltzGen:      {mode_label}  |  "
              f"{cfg['boltzgen_intermediate']:,} intermediate → {n_designs} final")
    if use_mosaic:
        seq = cfg["target_sequence"]
        print(f"  Mosaic seq:    {seq[:50]}{'...' if len(seq) > 50 else ''} ({len(seq)} aa)")

    print_tree(run_dir, tools_enabled, cfg)

    if not ask_yn("Generate configs and scripts now?", default=True):
        print("  Aborted. No files were written.")
        sys.exit(0)

    # ── Step 8: Generate ──────────────────────────────────────────────────────
    print("\nGenerating...")
    generate(cfg, tools_enabled)

    print(f"\n  Done! Run folder: {run_dir}")
    print()
    print("  Next steps:")
    step = 1
    if use_mosaic:
        print(f"    {step}. {run_dir}/run_mosaic.sh")
        step += 1
    if use_boltzgen:
        print(f"    {step}. {run_dir}/run_boltzgen.sh")
        step += 1
    if use_bindcraft:
        print(f"    {step}. {run_dir}/run_bindcraft.sh")
        step += 1
    if len(enabled_list) > 1:
        print(f"    Or run the full pipeline:  {run_dir}/run_all.sh")
    print()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        wizard()
    except KeyboardInterrupt:
        print("\n\n  Interrupted. No files were written.")
        sys.exit(1)
