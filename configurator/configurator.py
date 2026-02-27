#!/usr/bin/env python3
"""
BindMaster Configurator — interactive CLI wizard for setting up
protein binder design runs (Mosaic → BoltzGen → BindCraft).

Usage:
    bindmaster configure        # via unified CLI
    bindmaster-config           # via legacy shortcut
    python configurator/configurator.py  # directly
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ─── Colors ──────────────────────────────────────────────────────────────────

RED    = '\033[0;31m'
GREEN  = '\033[0;32m'
YELLOW = '\033[1;33m'
CYAN   = '\033[0;36m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

def print_step(msg): print(f"\n{CYAN}{BOLD}▶ {msg}{RESET}")
def print_ok(msg):   print(f"{GREEN}✓ {msg}{RESET}")
def print_warn(msg): print(f"{YELLOW}⚠ {msg}{RESET}")
def print_fail(msg): print(f"{RED}✗ {msg}{RESET}")

# ─── Runtime detection ────────────────────────────────────────────────────────

def _find_conda_base() -> Path | None:
    """Find conda/mamba base directory. Prefers mamba (faster installs)."""
    for cmd in ("mamba", "conda"):
        try:
            result = subprocess.run(
                [cmd, "info", "--base"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    for candidate in [
        Path.home() / "miniforge3",
        Path.home() / "mambaforge",
        Path.home() / "miniconda3",
        Path.home() / "anaconda3",
        Path.home() / "conda",
        Path("/opt/conda"),
        Path("/opt/miniforge3"),
        Path("/opt/miniconda3"),
        Path("/opt/anaconda3"),
    ]:
        if (candidate / "etc" / "profile.d" / "conda.sh").exists():
            return candidate
    return None


def _find_bindmaster_dir() -> Path:
    """
    Find the BindMaster repo root (the one containing install/install.sh
    and the cloned tool subdirectories).

    Search order:
      1. BINDMASTER_DIR environment variable
      2. Parent of this script (new layout: configurator/configurator.py)
      3. This script's own dir (legacy: configurator.py at repo root)
      4. Sibling / standard locations
      5. Fallback: parent of this script
    """
    if env := os.environ.get("BINDMASTER_DIR"):
        return Path(env).expanduser()
    script_parent = Path(__file__).resolve().parent
    # New layout: configurator lives in configurator/ subdir
    if (script_parent.parent / "bindmaster.py").exists():
        return script_parent.parent
    if (script_parent.parent / "install" / "install.sh").exists():
        return script_parent.parent
    # Legacy: configurator at repo root
    if (script_parent / "install.sh").exists():
        return script_parent
    if (script_parent / "install" / "install.sh").exists():
        return script_parent
    for candidate in [
        script_parent.parent / "BindMaster-installator",
        script_parent.parent / "BindMaster",
        Path.home() / "BindMaster-installator",
        Path.home() / "BindMaster",
    ]:
        if (candidate / "install" / "install.sh").exists():
            return candidate
        if (candidate / "install.sh").exists():
            return candidate
    return script_parent.parent  # best-effort fallback


# ─── Paths ───────────────────────────────────────────────────────────────────

CONDA_BASE     = _find_conda_base()
CONDA_ENVS_DIR = (CONDA_BASE / "envs") if CONDA_BASE else None

BINDMASTER_DIR = _find_bindmaster_dir()
BINDCRAFT_DIR  = BINDMASTER_DIR / "BindCraft"
BOLTZGEN_DIR   = BINDMASTER_DIR / "BoltzGen"
MOSAIC_DIR     = BINDMASTER_DIR / "Mosaic"
RUNS_DIR       = BINDMASTER_DIR / "runs"
FILTERS_DIR    = BINDCRAFT_DIR / "settings_filters"
ADVANCED_DIR   = BINDCRAFT_DIR / "settings_advanced"
MOSAIC_VENV    = MOSAIC_DIR / ".venv"
MOSAIC_HALLUCINATE_SRC = (
    MOSAIC_DIR / "examples" / "bindmaster_example" / "hallucinate_bindmaster.py"
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
    def _env_exists(name: str) -> bool:
        if CONDA_ENVS_DIR is None:
            return False
        return (CONDA_ENVS_DIR / name).is_dir()

    return {
        "bindcraft": _env_exists("BindCraft"),
        "boltzgen":  _env_exists("BoltzGen"),
        "mosaic":    (MOSAIC_VENV / "bin" / "python").exists(),
    }

# ─── Helpers ─────────────────────────────────────────────────────────────────

def banner():
    print()
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  BindMaster Configurator{RESET}")
    print(f"  Protein Binder Design Pipeline Setup Wizard")
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"  {CYAN}Tools dir{RESET} : {BINDMASTER_DIR}")
    if CONDA_BASE:
        print(f"  {CYAN}Conda base{RESET}: {CONDA_BASE}")
    else:
        print(f"  {CYAN}Conda base{RESET}: {RED}not found — install Miniconda/Mambaforge{RESET}")
    print()
    if CONDA_BASE is None:
        print_warn("conda/mamba not found. Install detection will be disabled.")
        print()
    if not (BINDMASTER_DIR / "install" / "install.sh").exists():
        print_warn(f"install/install.sh not found in {BINDMASTER_DIR}")
        print(f"  Set {YELLOW}BINDMASTER_DIR{RESET} env var to the correct path if tools are elsewhere.")
        print()


def ask(prompt, default=None, validator=None):
    """Prompt the user for input with optional default and validator."""
    if default is not None and str(default) != "":
        display = f"{CYAN}{prompt}{RESET} {YELLOW}[{default}]{RESET}: "
    else:
        display = f"{CYAN}{prompt}{RESET}: "
    while True:
        raw = input(display).strip()
        if raw == "" and default is not None:
            raw = str(default)
        if raw == "" and default is None:
            print(f"  {RED}(required — please enter a value){RESET}")
            continue
        if validator:
            result = validator(raw)
            if result is not True:
                print(f"  {RED}{result}{RESET}")
                continue
        return raw


def ask_yn(prompt, default=True):
    """Prompt for yes/no, returns bool."""
    hint = f"{GREEN}Y{RESET}/n" if default else f"y/{GREEN}N{RESET}"
    while True:
        raw = input(f"{CYAN}{prompt}{RESET} [{hint}]: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(f"  {RED}Please enter y or n.{RESET}")


def ask_choice(prompt, choices, default_index=0):
    """Present a numbered list; returns (index, choice_string)."""
    print(f"\n{BOLD}{prompt}{RESET}")
    for i, c in enumerate(choices):
        if i == default_index:
            print(f"  {GREEN}[{i+1}]{RESET} {c} {YELLOW}(default){RESET}")
        else:
            print(f"  {CYAN}[{i+1}]{RESET} {c}")
    while True:
        raw = input(
            f"  {YELLOW}Choice [1-{len(choices)}]{RESET} (default {default_index+1}): "
        ).strip()
        if raw == "":
            return default_index, choices[default_index]
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return idx, choices[idx]
        print(f"  {RED}Please enter a number between 1 and {len(choices)}.{RESET}")


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
    seen: dict = {}
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
    """Print a colored ASCII tree of what will be created."""
    name = run_dir.name
    print(f"\n  {BOLD}{name}/{RESET}")
    print(f"  ├── {CYAN}target/{RESET}")
    print(f"  │   └── <target>.pdb")
    if tools_enabled.get("mosaic"):
        print(f"  ├── {CYAN}mosaic/{RESET}")
        print(f"  │   └── hallucinate.py")
    if tools_enabled.get("boltzgen"):
        nanobody = cfg and cfg.get("boltzgen_mode") == "nanobody"
        print(f"  ├── {CYAN}boltzgen/{RESET}")
        if nanobody:
            print(f"  │   ├── nanobody_scaffolds/  ← 4 × .yaml + .cif")
        print(f"  │   ├── config.yaml")
        print(f"  │   └── outputs/")
    if tools_enabled.get("bindcraft"):
        print(f"  ├── {CYAN}bindcraft/{RESET}")
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
        print(f"  {prefix} {GREEN}{s}{RESET}")
    print()


# ─── Config writers ───────────────────────────────────────────────────────────

def write_bindcraft_target(path: Path, cfg: dict):
    settings = {
        "design_path": str(cfg["run_dir"] / "bindcraft" / "outputs") + "/",
        "binder_name": cfg["name"],
        "starting_pdb": str(cfg["target_pdb"]),
        "chains": cfg["chains"],
        "target_hotspot_residues": cfg["hotspots"] if cfg["hotspots"] else None,
        "lengths": [cfg.get("bindcraft_min_length", cfg["min_length"]),
                    cfg.get("bindcraft_max_length", cfg["max_length"])],
        "number_of_final_designs": cfg.get("bindcraft_n_designs", cfg["n_designs"]),
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
        f"#       --budget {cfg.get('boltzgen_budget', cfg['n_designs'])}",
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
            f"      sequence: {cfg.get('boltzgen_min_length', cfg['min_length'])}..{cfg.get('boltzgen_max_length', cfg['max_length'])}",
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
    example directory into dest_dir.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in NANOBODY_SCAFFOLD_NAMES:
        for ext in (".yaml", ".cif"):
            src = NANOBODY_SCAFFOLDS_SRC / f"{name}{ext}"
            shutil.copy2(src, dest_dir / f"{name}{ext}")


def write_mosaic_hallucinate(path: Path, cfg: dict):
    """
    Copy hallucinate_bindmaster.py and inject run parameters into the
    BINDMASTER PARAMETERS block at the top of the file.
    """
    content = MOSAIC_HALLUCINATE_SRC.read_text()

    old_block = (
        'TARGET_SEQUENCE = "REPLACE_ME"   # target protein sequence\n'
        'N_DESIGNS       = 100            # Stage 1: how many designs to generate per length\n'
        'TOP_K           = 5              # Stage 2: how many top designs to refold and export PDB\n'
        'MIN_LENGTH      = 65             # minimum binder length (aa)\n'
        'MAX_LENGTH      = 100            # maximum binder length (aa)\n'
        'LENGTH_STEP     = 5              # step between scanned lengths; set MIN=MAX for a single length'
    )
    new_block = (
        f'TARGET_SEQUENCE = {repr(cfg["target_sequence"])}   # target protein sequence\n'
        f'N_DESIGNS       = {cfg.get("mosaic_n_designs", 100):<6}           # Stage 1: how many designs to generate per length\n'
        f'TOP_K           = {cfg.get("mosaic_top_k", cfg["n_designs"]):<6}           # Stage 2: how many top designs to refold and export PDB\n'
        f'MIN_LENGTH      = {cfg.get("mosaic_min_length", cfg["min_length"]):<6}           # minimum binder length (aa)\n'
        f'MAX_LENGTH      = {cfg.get("mosaic_max_length", cfg["max_length"]):<6}           # maximum binder length (aa)\n'
        f'LENGTH_STEP     = {cfg.get("mosaic_length_step", 5):<6}           # step between scanned lengths; set MIN=MAX for a single length'
    )

    if old_block in content:
        content = content.replace(old_block, new_block)
    else:
        print_warn("Could not inject parameters block — please edit hallucinate.py manually.")

    path.write_text(content)


def write_run_bindcraft(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    conda_base = str(CONDA_BASE) if CONDA_BASE else ""
    content = f"""\
#!/usr/bin/env bash
# Run BindCraft for {cfg['name']}
# Generated by BindMaster Configurator
set -euo pipefail

BINDCRAFT_DIR="{BINDCRAFT_DIR}"
SETTINGS="{run_dir}/bindcraft/target_settings.json"
FILTERS="{run_dir}/bindcraft/filters.json"
ADVANCED="{run_dir}/bindcraft/advanced.json"

# Robust conda init — works in non-interactive shells (no conda on PATH by default)
# set +u: conda activate.d scripts (e.g. binutils) may reference unbound variables
set +u
_conda_found=false
for _conda_sh in \\
    "{conda_base}/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniforge3/etc/profile.d/conda.sh" \\
    "${{HOME}}/mambaforge/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniconda3/etc/profile.d/conda.sh" \\
    "${{HOME}}/anaconda3/etc/profile.d/conda.sh" \\
    "/opt/conda/etc/profile.d/conda.sh" \\
    "/opt/miniforge3/etc/profile.d/conda.sh"; do
    [[ -f "$_conda_sh" ]] && {{ source "$_conda_sh"; _conda_found=true; break; }}
done
[[ "$_conda_found" == true ]] || {{ echo "ERROR: conda not found — install Miniconda or Miniforge first." >&2; exit 1; }}
conda activate BindCraft
set -u

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
    conda_base = str(CONDA_BASE) if CONDA_BASE else ""
    content = f"""\
#!/usr/bin/env bash
# Run BoltzGen for {cfg['name']}
# Generated by BindMaster Configurator
set -euo pipefail

CONFIG="{run_dir}/boltzgen/config.yaml"
OUTPUT_DIR="{run_dir}/boltzgen/outputs"

# Robust conda init — works in non-interactive shells (no conda on PATH by default)
# set +u: conda activate.d scripts may reference unbound variables
set +u
_conda_found=false
for _conda_sh in \\
    "{conda_base}/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniforge3/etc/profile.d/conda.sh" \\
    "${{HOME}}/mambaforge/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniconda3/etc/profile.d/conda.sh" \\
    "${{HOME}}/anaconda3/etc/profile.d/conda.sh" \\
    "/opt/conda/etc/profile.d/conda.sh" \\
    "/opt/miniforge3/etc/profile.d/conda.sh"; do
    [[ -f "$_conda_sh" ]] && {{ source "$_conda_sh"; _conda_found=true; break; }}
done
[[ "$_conda_found" == true ]] || {{ echo "ERROR: conda not found — install Miniconda or Miniforge first." >&2; exit 1; }}
conda activate BoltzGen
set -u

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
    echo "Run: bindmaster install --tool mosaic  (or: bash {BINDMASTER_DIR}/install/install.sh --tool mosaic)" >&2
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
            '# Mosaic is interactive — run it separately before the pipeline:',
            '#   bash "$RUN_DIR/run_mosaic.sh"',
            '# Then re-run this script. It will skip Mosaic if designs.csv already exists.',
            'echo "=== Step: Mosaic ==="',
            'if [[ -f "$RUN_DIR/mosaic/designs.csv" ]]; then',
            '    echo "  Mosaic designs.csv found — skipping interactive run."',
            'else',
            '    echo "  Mosaic requires interactive input. Run run_mosaic.sh first, then re-run run_all.sh." >&2',
            '    exit 1',
            'fi',
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

    (run_dir / "target").mkdir(parents=True, exist_ok=True)
    if tools_enabled.get("mosaic"):
        (run_dir / "mosaic").mkdir(parents=True, exist_ok=True)
    if tools_enabled.get("boltzgen"):
        (run_dir / "boltzgen" / "outputs").mkdir(parents=True, exist_ok=True)
    if tools_enabled.get("bindcraft"):
        (run_dir / "bindcraft" / "outputs").mkdir(parents=True, exist_ok=True)

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


# ─── Pipeline runner ──────────────────────────────────────────────────────────

def run_pipeline(cfg: dict, tools_enabled: dict):
    """Run the enabled tools in sequence with live terminal output."""
    run_dir = cfg["run_dir"]
    failed  = []

    if tools_enabled.get("mosaic"):
        print_step("Running Mosaic  (interactive — you will be prompted below)")
        rc = subprocess.run(["bash", str(run_dir / "run_mosaic.sh")]).returncode
        if rc == 0:
            print_ok("Mosaic completed")
        else:
            print_fail(f"Mosaic failed (exit code {rc})")
            failed.append("Mosaic")

    if tools_enabled.get("boltzgen"):
        print_step("Running BoltzGen")
        rc = subprocess.run(["bash", str(run_dir / "run_boltzgen.sh")]).returncode
        if rc == 0:
            print_ok("BoltzGen completed")
        else:
            print_fail(f"BoltzGen failed (exit code {rc})")
            failed.append("BoltzGen")

    if tools_enabled.get("bindcraft"):
        print_step("Running BindCraft")
        rc = subprocess.run(["bash", str(run_dir / "run_bindcraft.sh")]).returncode
        if rc == 0:
            print_ok("BindCraft completed")
        else:
            print_fail(f"BindCraft failed (exit code {rc})")
            failed.append("BindCraft")

    print()
    if not failed:
        print_ok("Pipeline complete!")
    else:
        print_fail(f"Pipeline finished with failures: {', '.join(failed)}")


# ─── Shortcut installer ───────────────────────────────────────────────────────

def install_shortcut():
    """
    Write ~/.local/bin/bindmaster-config pointing at this script.
    Silent no-op if the shortcut already exists and is up to date.
    """
    shortcuts_dir = Path.home() / ".local" / "bin"
    shortcut = shortcuts_dir / "bindmaster-config"
    script = Path(__file__).resolve()
    target_line = f'exec python3 "{script}" "$@"\n'

    if shortcut.exists() and shortcut.read_text().endswith(target_line):
        return

    shortcuts_dir.mkdir(parents=True, exist_ok=True)
    shortcut.write_text(
        f"#!/usr/bin/env bash\n"
        f"# BindMaster Configurator shortcut — auto-generated\n"
        f"{target_line}"
    )
    shortcut.chmod(0o755)
    print_ok(f"Shortcut installed: {shortcut}")


# ─── Wizard ───────────────────────────────────────────────────────────────────

def wizard():
    install_shortcut()
    banner()

    # ── Step 1: Project name ──────────────────────────────────────────────────
    print_step("Step 1 — Project name")
    print(f"  Used as binder name. Run folder path can be customised below.")
    name = ask("  Target name", validator=validate_name)
    run_dir = Path(ask(
        "  Run folder",
        default=str(RUNS_DIR / name),
    )).expanduser()

    if run_dir.exists():
        print()
        print_warn(f"Run folder already exists: {run_dir}")
        if not ask_yn("  Overwrite?", default=False):
            print("  Aborted.")
            sys.exit(0)

    # ── Step 2: Target structure ──────────────────────────────────────────────
    print_step("Step 2 — Target structure")
    _, input_type = ask_choice(
        "How will you provide the target structure?",
        ["PDB file path", "Amino acid sequence (requires structure prediction first)"],
        default_index=0,
    )

    if "sequence" in input_type.lower():
        print()
        print_warn("You need to predict the structure first.")
        print(f"  Recommended: ColabFold")
        print(f"    1. Paste your sequence into the AlphaFold2 ColabFold notebook")
        print(f"    2. Download the best-ranked .pdb file")
        print(f"    3. Come back and provide the .pdb path below")
        print()

    target_pdb_src = ask("  Path to target .pdb file", validator=validate_pdb_path)

    # ── Step 3: Target details ────────────────────────────────────────────────
    print_step("Step 3 — Target details")
    chains = ask("  Chain(s) to target (e.g. A or A,B)", default="A",
                 validator=validate_chains)
    hotspots = ask(
        "  Hotspot residues (e.g. 56 or 1-10,20, blank=auto)",
        default="",
        validator=validate_hotspots,
    )

    primary_chain = chains.split(",")[0].strip()
    target_sequence = extract_sequence_from_pdb(target_pdb_src, primary_chain)
    if target_sequence:
        preview = target_sequence[:50] + ("..." if len(target_sequence) > 50 else "")
        print_ok(f"Auto-extracted sequence for chain {primary_chain}: "
                 f"{preview} ({len(target_sequence)} aa)")

    # ── Step 4: Binder settings ───────────────────────────────────────────────
    print_step("Step 4 — Binder settings (global defaults)")
    print(f"  These apply to all tools — you can override per-tool in Step 6.")
    min_length = int(ask("  Minimum binder length", default=65,
                         validator=validate_int(min_val=10, max_val=500)))
    max_length = int(ask("  Maximum binder length", default=150,
                         validator=validate_int(min_val=10, max_val=500)))
    if max_length < min_length:
        print_warn("max length < min length — swapping values.")
        min_length, max_length = max_length, min_length
    n_designs = int(ask("  Number of top/final designs", default=10,
                        validator=validate_int(min_val=1)))

    # ── Step 5: Tool selection ────────────────────────────────────────────────
    print_step("Step 5 — Tool selection")
    installed = detect_installs()

    def _tag(key):
        if installed[key]:
            return f"{GREEN}installed{RESET}"
        return f"{RED}NOT installed — run: bindmaster install{RESET}"

    print(f"  {BOLD}Mosaic{RESET}    [{_tag('mosaic')}]")
    use_mosaic = ask_yn("  Enable Mosaic?", default=False)
    print(f"  {BOLD}BoltzGen{RESET}  [{_tag('boltzgen')}]")
    use_boltzgen = ask_yn("  Enable BoltzGen?", default=False)
    print(f"  {BOLD}BindCraft{RESET} [{_tag('bindcraft')}]")
    use_bindcraft = ask_yn("  Enable BindCraft?", default=True)

    tools_enabled = {
        "mosaic": use_mosaic,
        "boltzgen": use_boltzgen,
        "bindcraft": use_bindcraft,
    }

    if not any(tools_enabled.values()):
        print_warn("No tools enabled — nothing to generate. Exiting.")
        sys.exit(0)

    # ── Step 6: Per-tool settings ─────────────────────────────────────────────
    cfg: dict = {
        "name": name,
        "run_dir": run_dir,
        "target_pdb_src": target_pdb_src,
        "target_pdb": None,
        "target_sequence": target_sequence or "",
        "chains": chains,
        "hotspots": hotspots.strip() if hotspots.strip() else None,
        "min_length": min_length,
        "max_length": max_length,
        "n_designs": n_designs,
        "filter_preset": "default_filters",
        "advanced_preset": "default_4stage_multimer",
        "boltzgen_mode": "protein",
        "boltzgen_intermediate": 10000,
    }

    if use_bindcraft:
        print_step("Step 6a — BindCraft settings")
        filter_presets = list_presets(FILTERS_DIR)
        if filter_presets:
            default_fi = (filter_presets.index("default_filters")
                          if "default_filters" in filter_presets else 0)
            _, cfg["filter_preset"] = ask_choice(
                "Filter preset:", filter_presets, default_index=default_fi)
        else:
            print_warn(f"No filter presets found in {FILTERS_DIR}")

        advanced_presets = list_presets(ADVANCED_DIR)
        if advanced_presets:
            default_ai = (advanced_presets.index("default_4stage_multimer")
                          if "default_4stage_multimer" in advanced_presets else 0)
            _, cfg["advanced_preset"] = ask_choice(
                "Advanced preset:", advanced_presets, default_index=default_ai)
        else:
            print_warn(f"No advanced presets found in {ADVANCED_DIR}")

        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["bindcraft_min_length"] = int(ask(
            "  Min binder length", default=min_length,
            validator=validate_int(min_val=1, max_val=500)))
        cfg["bindcraft_max_length"] = int(ask(
            "  Max binder length", default=max_length,
            validator=validate_int(min_val=1, max_val=500)))
        cfg["bindcraft_n_designs"] = int(ask(
            "  Number of final designs", default=n_designs,
            validator=validate_int(min_val=1)))

    if use_boltzgen:
        print_step("Step 6b — BoltzGen settings")
        _, mode_choice = ask_choice(
            "Binder type:",
            ["protein-anything — de-novo protein binder",
             "nanobody — redesign CDR loops of four scaffold nanobodies"],
            default_index=0,
        )
        cfg["boltzgen_mode"] = "nanobody" if "nanobody" in mode_choice else "protein"
        if cfg["boltzgen_mode"] == "nanobody":
            print(f"  Scaffolds: {CYAN}{', '.join(NANOBODY_SCAFFOLD_NAMES)}{RESET}")
            print(f"  (will be copied to boltzgen/nanobody_scaffolds/)")
        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["boltzgen_budget"] = int(ask(
            "  Final designs (--budget)", default=n_designs,
            validator=validate_int(min_val=1)))
        cfg["boltzgen_min_length"] = int(ask(
            "  Min binder length", default=min_length,
            validator=validate_int(min_val=1, max_val=500)))
        cfg["boltzgen_max_length"] = int(ask(
            "  Max binder length", default=max_length,
            validator=validate_int(min_val=1, max_val=500)))
        cfg["boltzgen_intermediate"] = int(ask(
            "  Intermediate designs (--num_designs, recommended: 10 000)", default=10000,
            validator=validate_int(min_val=1)))

    if use_mosaic:
        print_step("Step 6c — Mosaic settings")
        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["mosaic_n_designs"] = int(ask(
            "  Designs to generate (Stage 1)",
            default=100,
            validator=validate_int(min_val=1)))
        cfg["mosaic_top_k"] = int(ask(
            "  Top designs to refold (TOP_K)", default=n_designs,
            validator=validate_int(min_val=0)))
        cfg["mosaic_min_length"] = int(ask(
            "  Min binder length", default=min_length,
            validator=validate_int(min_val=1, max_val=500)))
        cfg["mosaic_max_length"] = int(ask(
            "  Max binder length", default=max_length,
            validator=validate_int(min_val=1, max_val=500)))
        cfg["mosaic_length_step"] = int(ask(
            "  Length scan step (1 = every aa, set min=max to skip scan)", default=5,
            validator=validate_int(min_val=1)))
        if not target_sequence:
            print_warn("Could not auto-extract target sequence from PDB.")
            cfg["target_sequence"] = ask(
                f"  Target amino-acid sequence (chain {primary_chain})",
                validator=validate_sequence)
        else:
            seq_preview = target_sequence[:60] + ("..." if len(target_sequence) > 60 else "")
            print(f"  Sequence ({len(target_sequence)} aa): {CYAN}{seq_preview}{RESET}")
            if not ask_yn("  Use this sequence?", default=True):
                cfg["target_sequence"] = ask(
                    "  Enter target sequence", validator=validate_sequence)

    # ── Step 7: Preview ───────────────────────────────────────────────────────
    print_step("Step 7 — Preview")
    print(f"  {CYAN}Run folder{RESET}:    {run_dir}")
    print(f"  {CYAN}Target PDB{RESET}:    {target_pdb_src}")
    print(f"  {CYAN}Chains{RESET}:        {chains}  |  "
          f"{CYAN}Hotspots{RESET}: {hotspots or '(auto)'}")
    print(f"  {CYAN}Binder length{RESET}: {min_length}–{max_length}  |  "
          f"{CYAN}Top designs{RESET}: {n_designs}")
    enabled_list = [t for t, v in tools_enabled.items() if v]
    print(f"  {CYAN}Tools{RESET}:         {', '.join(enabled_list)}")
    if use_bindcraft:
        bc_min = cfg.get("bindcraft_min_length", min_length)
        bc_max = cfg.get("bindcraft_max_length", max_length)
        bc_n   = cfg.get("bindcraft_n_designs", n_designs)
        print(f"  {CYAN}BindCraft{RESET}:     "
              f"filters={cfg['filter_preset']}  advanced={cfg['advanced_preset']}")
        print(f"             length={bc_min}–{bc_max}  final_designs={bc_n}")
    if use_boltzgen:
        bg_min = cfg.get("boltzgen_min_length", min_length)
        bg_max = cfg.get("boltzgen_max_length", max_length)
        bg_n   = cfg.get("boltzgen_budget", n_designs)
        mode_label = "nanobody CDR redesign" if cfg["boltzgen_mode"] == "nanobody" else "de-novo protein"
        print(f"  {CYAN}BoltzGen{RESET}:      {mode_label}  |  "
              f"length={bg_min}–{bg_max}  budget={bg_n}  "
              f"intermediate={cfg['boltzgen_intermediate']:,}")
    if use_mosaic:
        mo_min = cfg.get("mosaic_min_length", min_length)
        mo_max = cfg.get("mosaic_max_length", max_length)
        mo_n   = cfg.get("mosaic_n_designs", 100)
        mo_k   = cfg.get("mosaic_top_k", n_designs)
        seq = cfg["target_sequence"]
        print(f"  {CYAN}Mosaic{RESET}:        length={mo_min}–{mo_max}  "
              f"generate={mo_n}  refold(TOP_K)={mo_k}")
        print(f"  {CYAN}Mosaic seq{RESET}:    "
              f"{seq[:50]}{'...' if len(seq) > 50 else ''} ({len(seq)} aa)")

    print_tree(run_dir, tools_enabled, cfg)

    if not ask_yn("Generate configs and scripts now?", default=True):
        print("  Aborted. No files were written.")
        sys.exit(0)

    # ── Step 8: Generate ──────────────────────────────────────────────────────
    print_step("Generating run folder")
    generate(cfg, tools_enabled)
    print_ok(f"Run folder ready: {run_dir}")

    # ── Step 9: Run now? ──────────────────────────────────────────────────────
    print()
    if use_mosaic:
        print_warn("Mosaic requires interactive input and will run first.")
    if use_boltzgen:
        print_warn("BoltzGen downloads ~6 GB of weights on first run.")

    if ask_yn("Run the pipeline now?", default=True):
        run_pipeline(cfg, tools_enabled)
    else:
        print()
        print_warn("To run later:")
        step = 1
        if use_mosaic:
            print(f"  {step}. bash {run_dir}/run_mosaic.sh")
            step += 1
        if use_boltzgen:
            print(f"  {step}. bash {run_dir}/run_boltzgen.sh")
            step += 1
        if use_bindcraft:
            print(f"  {step}. bash {run_dir}/run_bindcraft.sh")
            step += 1
        if len(enabled_list) > 1:
            print(f"  Or run the full pipeline:  bash {run_dir}/run_all.sh")
        print()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        wizard()
    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}Interrupted.{RESET} No files were written.")
        sys.exit(1)
