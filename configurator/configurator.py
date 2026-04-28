#!/usr/bin/env python3
"""
BindMaster Configurator — interactive CLI wizard for setting up
protein binder design runs (Mosaic → BoltzGen → BindCraft).

Usage:
    bindmaster configure        # via unified CLI
    bindmaster-config           # via legacy shortcut
    python configurator/configurator.py  # directly
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

# ─── Colors ──────────────────────────────────────────────────────────────────

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_step(msg):
    print(f"\n{CYAN}{BOLD}▶ {msg}{RESET}")


def print_ok(msg):
    print(f"{GREEN}✓ {msg}{RESET}")


def print_warn(msg):
    print(f"{YELLOW}⚠ {msg}{RESET}")


def print_fail(msg):
    print(f"{RED}✗ {msg}{RESET}")


# ─── Runtime detection ────────────────────────────────────────────────────────


def _find_conda_base() -> Path | None:
    """Find conda/mamba base directory. Prefers mamba (faster installs)."""
    # Check local standalone conda first (BindMaster/conda/)
    local_conda = Path(__file__).resolve().parent.parent / "conda"
    if (local_conda / "etc" / "profile.d" / "conda.sh").exists():
        return local_conda
    for cmd in ("mamba", "conda"):
        try:
            result = subprocess.run(
                [cmd, "info", "--base"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                base = result.stdout.strip()
                # mamba 2.x outputs "base environment : /path" instead of just "/path"
                if ":" in base:
                    base = base.rsplit(":", 1)[-1].strip()
                p = Path(base)
                if p.is_dir():
                    return p
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

CONDA_BASE = _find_conda_base()
CONDA_ENVS_DIR = (CONDA_BASE / "envs") if CONDA_BASE else None

BINDMASTER_DIR = _find_bindmaster_dir()
BINDCRAFT_DIR = BINDMASTER_DIR / "BindCraft"
BOLTZGEN_DIR = BINDMASTER_DIR / "BoltzGen"
MOSAIC_DIR = BINDMASTER_DIR / "Mosaic"
RUNS_DIR = BINDMASTER_DIR / "runs"
FILTERS_DIR = BINDCRAFT_DIR / "settings_filters"
ADVANCED_DIR = BINDCRAFT_DIR / "settings_advanced"
EVALUATOR_DIR = BINDMASTER_DIR / "Evaluator"
PXDESIGN_DIR = BINDMASTER_DIR / "PXDesign"
PROTEINA_COMPLEXA_DIR = BINDMASTER_DIR / "Proteina-Complexa"
PROTEINA_COMPLEXA_VENV = PROTEINA_COMPLEXA_DIR / ".venv"
PROTEIN_HUNTER_DIR = BINDMASTER_DIR / "Protein-Hunter"
FOUNDRY_WEIGHTS_DIR = BINDMASTER_DIR / "weights" / "foundry"
MOSAIC_VENV = MOSAIC_DIR / ".venv"
MOSAIC_HALLUCINATE_SRC = MOSAIC_DIR / "examples" / "bindmaster_examples" / "hallucinate_bindmaster.py"
NANOBODY_SCAFFOLDS_SRC = BOLTZGEN_DIR / "example" / "nanobody_scaffolds"
NANOBODY_SCAFFOLD_NAMES = ["7eow", "7xl0", "8coh", "8z8v"]

# ─── Amino-acid 3→1 mapping ──────────────────────────────────────────────────

AA3TO1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    # common non-standard aliases
    "MSE": "M",
    "HSD": "H",
    "HSE": "H",
    "HSP": "H",
    "SEC": "U",
    "PYL": "O",
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
        "boltzgen": _env_exists("BoltzGen"),
        "mosaic": (MOSAIC_VENV / "bin" / "python").exists(),
        "evaluator": ((EVALUATOR_DIR / "evaluate.sh").exists() and _env_exists("binder-eval")),
        "pxdesign_local": _env_exists("bindmaster_pxdesign"),
        "proteina_complexa": (PROTEINA_COMPLEXA_VENV / "bin" / "python").exists(),
        "rfd3": _env_exists("bindmaster_rfd3") and (FOUNDRY_WEIGHTS_DIR / "rfd3_latest.ckpt").exists(),
        "protein_hunter": _env_exists("bindmaster_protein_hunter") and PROTEIN_HUNTER_DIR.exists(),
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────


def banner():
    print()
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  BindMaster Configurator{RESET}")
    print("  Protein Binder Design Pipeline Setup Wizard")
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
            print(f"  {GREEN}[{i + 1}]{RESET} {c} {YELLOW}(default){RESET}")
        else:
            print(f"  {CYAN}[{i + 1}]{RESET} {c}")
    while True:
        raw = input(f"  {YELLOW}Choice [1-{len(choices)}]{RESET} (default {default_index + 1}): ").strip()
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


def validate_structure_path(s):
    p = Path(s).expanduser()
    if not p.exists():
        return f"File not found: {p}"
    if p.suffix.lower() not in (".pdb", ".cif", ".mmcif"):
        return "File must be .pdb, .cif, or .mmcif"
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


def _cif_tokenize(text: str) -> list:
    """Tokenize an mmCIF file into a flat list of string tokens.

    Pure-Python tokenizer (no external deps).  Handles semicolon-delimited
    multi-line values, single/double quoted strings, and # comments.
    Ported from Evaluator/binder_comparison/io/read.py.
    """
    tokens: list = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(";"):
            parts = [line[1:]]
            i += 1
            while i < len(lines) and not lines[i].startswith(";"):
                parts.append(lines[i])
                i += 1
            tokens.append("\n".join(parts).rstrip())
            i += 1
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        j = 0
        while j < len(stripped):
            if stripped[j].isspace():
                j += 1
                continue
            if stripped[j] == "#":
                break
            if stripped[j] in ('"', "'"):
                q = stripped[j]
                j += 1
                start = j
                while j < len(stripped) and stripped[j] != q:
                    j += 1
                tokens.append(stripped[start:j])
                if j < len(stripped):
                    j += 1
            else:
                start = j
                while j < len(stripped) and not stripped[j].isspace():
                    j += 1
                tokens.append(stripped[start:j])
        i += 1
    return tokens


def _cif_entity_poly_seq(text: str) -> str | None:
    """Extract the longest canonical one-letter sequence from _entity_poly."""
    tokens = _cif_tokenize(text)
    i = 0
    while i < len(tokens):
        if tokens[i].lower() != "loop_":
            i += 1
            continue
        i += 1
        cols: list = []
        while i < len(tokens) and tokens[i].startswith("_"):
            cols.append(tokens[i].lower())
            i += 1
        if not any(c.startswith("_entity_poly.") for c in cols):
            continue
        seq_col = None
        for preferred in (
            "_entity_poly.pdbx_seq_one_letter_code_can",
            "_entity_poly.pdbx_seq_one_letter_code",
        ):
            if preferred in cols:
                seq_col = cols.index(preferred)
                break
        if seq_col is None:
            continue
        n_cols = len(cols)
        seqs: list = []
        while i < len(tokens):
            tok = tokens[i]
            if tok.lower() == "loop_" or (tok.startswith("_") and "." in tok):
                break
            if i + n_cols > len(tokens):
                break
            row = tokens[i : i + n_cols]
            seq = re.sub(r"[^A-Za-z]", "", row[seq_col]).upper()
            if len(seq) >= 5:
                seqs.append(seq)
            i += n_cols
        if seqs:
            return max(seqs, key=len)
    return None


def _cif_atom_site_seq(text: str) -> str | None:
    """Fallback: extract sequence from _atom_site CA records."""
    tokens = _cif_tokenize(text)
    i = 0
    while i < len(tokens):
        if tokens[i].lower() != "loop_":
            i += 1
            continue
        i += 1
        cols: list = []
        while i < len(tokens) and tokens[i].startswith("_"):
            cols.append(tokens[i].lower())
            i += 1
        if not any(c.startswith("_atom_site.") for c in cols):
            continue
        col = {c.split(".", 1)[1]: idx for idx, c in enumerate(cols)}
        needed = {"label_atom_id", "label_comp_id", "label_asym_id", "label_seq_id"}
        if not needed.issubset(col):
            continue
        n_cols = len(cols)
        seen: dict = {}
        while i < len(tokens):
            if tokens[i].lower() == "loop_" or (tokens[i].startswith("_") and "." in tokens[i]):
                break
            if i + n_cols > len(tokens):
                break
            row = tokens[i : i + n_cols]
            if row[col["label_atom_id"]].strip("'\"") == "CA":
                chain = row[col["label_asym_id"]].strip("'\"")
                try:
                    resnum = int(row[col["label_seq_id"]])
                except ValueError:
                    i += n_cols
                    continue
                resname = row[col["label_comp_id"]].strip("'\"")
                key = (chain, resnum)
                if key not in seen:
                    seen[key] = AA3TO1.get(resname, "X")
            i += n_cols
        if seen:
            return "".join(seen[k] for k in sorted(seen))
    return None


def extract_sequence_from_cif(cif_path: str, chain_id: str) -> str | None:
    """Extract amino-acid sequence for chain_id from a CIF/mmCIF file.

    Returns a 1-letter string, or None on failure.
    """
    try:
        text = Path(cif_path).expanduser().read_text(errors="replace")
    except OSError:
        return None

    # Try canonical _entity_poly first (chain-agnostic, longest entity)
    seq = _cif_entity_poly_seq(text)
    if seq:
        return seq

    # Fallback: _atom_site CA records for requested chain
    tokens = _cif_tokenize(text)
    i = 0
    while i < len(tokens):
        if tokens[i].lower() != "loop_":
            i += 1
            continue
        i += 1
        cols: list = []
        while i < len(tokens) and tokens[i].startswith("_"):
            cols.append(tokens[i].lower())
            i += 1
        if not any(c.startswith("_atom_site.") for c in cols):
            continue
        col = {c.split(".", 1)[1]: idx for idx, c in enumerate(cols)}
        needed = {"label_atom_id", "label_comp_id", "label_asym_id", "label_seq_id"}
        if not needed.issubset(col):
            continue
        n_cols = len(cols)
        seen: dict = {}
        while i < len(tokens):
            if tokens[i].lower() == "loop_" or (tokens[i].startswith("_") and "." in tokens[i]):
                break
            if i + n_cols > len(tokens):
                break
            row = tokens[i : i + n_cols]
            if row[col["label_atom_id"]].strip("'\"") == "CA":
                ch = row[col["label_asym_id"]].strip("'\"")
                if ch.upper() != chain_id.upper():
                    i += n_cols
                    continue
                try:
                    resnum = int(row[col["label_seq_id"]])
                except ValueError:
                    i += n_cols
                    continue
                resname = row[col["label_comp_id"]].strip("'\"")
                key = (ch, resnum)
                if key not in seen:
                    seen[key] = AA3TO1.get(resname, "X")
            i += n_cols
        if seen:
            return "".join(seen[k] for k in sorted(seen))
    return None


def extract_sequence_from_structure(path: str, chain_id: str) -> str | None:
    """Dispatcher: extract sequence from PDB or mmCIF file."""
    p = Path(path).expanduser()
    if p.suffix.lower() in (".cif", ".mmcif"):
        return extract_sequence_from_cif(str(p), chain_id)
    return extract_sequence_from_pdb(str(p), chain_id)


def cif_to_pdb_atoms(cif_path: str, pdb_path: str) -> bool:
    """Convert mmCIF to a minimal PDB file using _atom_site records.

    Writes standard ATOM/HETATM records from parsed CIF data.
    Returns True on success, False if no atoms could be parsed.
    No external dependencies (no BioPython required).
    """
    try:
        text = Path(cif_path).expanduser().read_text(errors="replace")
    except OSError:
        return False

    tokens = _cif_tokenize(text)
    i = 0
    atom_lines: list = []
    while i < len(tokens):
        if tokens[i].lower() != "loop_":
            i += 1
            continue
        i += 1
        cols: list = []
        while i < len(tokens) and tokens[i].startswith("_"):
            cols.append(tokens[i].lower())
            i += 1
        if not any(c.startswith("_atom_site.") for c in cols):
            continue
        col = {c.split(".", 1)[1]: idx for idx, c in enumerate(cols)}
        needed = {
            "group_pdb",
            "label_atom_id",
            "label_comp_id",
            "label_asym_id",
            "label_seq_id",
            "cartn_x",
            "cartn_y",
            "cartn_z",
        }
        if not needed.issubset(col):
            continue
        n_cols = len(cols)
        serial = 1
        while i < len(tokens):
            if tokens[i].lower() == "loop_" or (tokens[i].startswith("_") and "." in tokens[i]):
                break
            if i + n_cols > len(tokens):
                break
            row = tokens[i : i + n_cols]
            group = row[col["group_pdb"]].strip("'\"")
            atom_name = row[col["label_atom_id"]].strip("'\"")
            comp_id = row[col["label_comp_id"]].strip("'\"")
            chain = row[col["label_asym_id"]].strip("'\"")
            try:
                seq_id = int(row[col["label_seq_id"]])
                x = float(row[col["cartn_x"]])
                y = float(row[col["cartn_y"]])
                z = float(row[col["cartn_z"]])
            except (ValueError, IndexError):
                i += n_cols
                continue
            # Element symbol (optional)
            elem = col.get("type_symbol")
            elem_str = row[elem].strip("'\"").upper()[:2] if elem is not None else atom_name[0]
            # B-factor / occupancy (optional)
            occ = 1.0
            bfac = 0.0
            if "occupancy" in col:
                try:
                    occ = float(row[col["occupancy"]])
                except ValueError:
                    pass
            if "b_iso_or_equiv" in col:
                try:
                    bfac = float(row[col["b_iso_or_equiv"]])
                except ValueError:
                    pass
            # PDB ATOM format
            record = "HETATM" if group == "HETATM" else "ATOM  "
            # Atom name alignment: 4 chars, left-padded for 1-3 char names
            if len(atom_name) < 4:
                atom_field = f" {atom_name:<3s}"
            else:
                atom_field = f"{atom_name:<4s}"
            line = (
                f"{record}{serial:5d} {atom_field}{comp_id:>3s} {chain[0]:1s}{seq_id:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}{occ:6.2f}{bfac:6.2f}          {elem_str:>2s}  "
            )
            atom_lines.append(line)
            serial += 1
            i += n_cols
        break  # only process first _atom_site block

    if not atom_lines:
        return False

    out = Path(pdb_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for line in atom_lines:
            f.write(line + "\n")
        f.write("END\n")
    return True


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
    is_cif = cfg and Path(cfg.get("target_pdb_src", "")).suffix.lower() in (".cif", ".mmcif")
    print(f"\n  {BOLD}{name}/{RESET}")
    print(f"  ├── {CYAN}target/{RESET}")
    if is_cif:
        print("  │   ├── <target>.cif")
        print("  │   └── <target>.pdb  (converted)")
    else:
        print("  │   └── <target>.pdb")
    if tools_enabled.get("mosaic"):
        print(f"  ├── {CYAN}mosaic/{RESET}")
        print("  │   └── hallucinate.py")
    if tools_enabled.get("boltzgen"):
        nanobody = cfg and cfg.get("boltzgen_mode") == "nanobody"
        print(f"  ├── {CYAN}boltzgen/{RESET}")
        if nanobody:
            print("  │   ├── nanobody_scaffolds/  ← 4 × .yaml + .cif")
        print("  │   ├── config.yaml")
        print("  │   └── outputs/")
    if tools_enabled.get("bindcraft"):
        print(f"  ├── {CYAN}bindcraft/{RESET}")
        print("  │   ├── target_settings.json")
        print("  │   ├── filters.json")
        print("  │   ├── advanced.json")
        print("  │   └── outputs/")
    if tools_enabled.get("pxdesign_local"):
        print(f"  ├── {CYAN}pxdesign/{RESET}")
        print("  │   ├── input.yaml")
        print("  │   └── outputs/")
    if tools_enabled.get("evaluator"):
        print(f"  ├── {CYAN}evaluate/{RESET}")
        print("  │   └── evaluate_report/")
    scripts = []
    if tools_enabled.get("mosaic"):
        scripts.append("run_mosaic.sh")
    if tools_enabled.get("boltzgen"):
        scripts.append("run_boltzgen.sh")
    if tools_enabled.get("bindcraft"):
        scripts.append("run_bindcraft.sh")
    if tools_enabled.get("pxdesign_local"):
        scripts.append("run_pxdesign.sh")
    if tools_enabled.get("evaluator"):
        scripts.append("run_evaluate.sh")
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
        "lengths": [
            cfg.get("bindcraft_min_length", cfg["min_length"]),
            cfg.get("bindcraft_max_length", cfg["max_length"]),
        ],
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
    chain_ids = [c.strip() for c in cfg["chains"].split(",") if c.strip()]
    nanobody = cfg.get("boltzgen_mode") == "nanobody"

    lines = [
        f"# BoltzGen design specification for {cfg['name']}",
        f"# Mode: {'nanobody scaffold CDR redesign' if nanobody else 'de-novo protein binder'}",
        "# Generated by BindMaster Configurator",
        "#",
        "# Run with:",
        "#   boltzgen run config.yaml \\",
        "#       --output outputs/ \\",
        "#       --protocol protein-anything \\",
        f"#       --num_designs {cfg['boltzgen_intermediate']} \\",
        f"#       --budget {cfg.get('boltzgen_budget', cfg['n_designs'])}",
        "",
        "entities:",
    ]

    if nanobody:
        lines += [
            "  # Nanobody scaffolds: CDR loops (H1/H2/H3) will be redesigned",
            "  - file:",
            "      path:",
        ]
        for n in NANOBODY_SCAFFOLD_NAMES:
            lines.append(f"        - nanobody_scaffolds/{n}.yaml")
    else:
        lines += [
            "  # Designed binder chain: uniform random length in the given range",
            "  - protein:",
            "      id: B",
            f"      sequence: {cfg.get('boltzgen_min_length', cfg['min_length'])}..{cfg.get('boltzgen_max_length', cfg['max_length'])}",
        ]

    lines += [
        "",
        "  # Target protein loaded from the copied PDB",
        "  - file:",
        f'      path: "{target_pdb}"',
        "      include:",
    ]

    for c in chain_ids:
        lines.append("        - chain:")
        lines.append(f"            id: {c}")

    if cfg["hotspots"]:
        binding_str = hotspots_to_boltzgen_str(cfg["hotspots"])
        lines.append("      binding_types:")
        for c in chain_ids:
            lines.append("        - chain:")
            lines.append(f"            id: {c}")
            lines.append(f"            binding: {binding_str}")

    lines.append('      structure_groups: "all"')
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

    target_pdb_path = str(cfg.get("target_pdb", ""))

    old_block = (
        'TARGET_SEQUENCE = "REPLACE_ME"  # target protein sequence\n'
        'TARGET_PDB = ""  # path to target PDB (used as structural template; blank = predict from sequence)\n'
        "N_DESIGNS = 100  # Stage 1: how many designs to generate per length\n"
        "TOP_K = 5  # Stage 2: how many top designs to refold and export PDB\n"
        "MIN_LENGTH = 65  # minimum binder length (aa)\n"
        "MAX_LENGTH = 100  # maximum binder length (aa)\n"
        "LENGTH_STEP = 5  # step between scanned lengths; set MIN=MAX for a single length"
    )
    new_block = (
        f"TARGET_SEQUENCE = {cfg['target_sequence']!r}  # target protein sequence\n"
        f"TARGET_PDB = {target_pdb_path!r}  # path to target PDB (structural template)\n"
        f"N_DESIGNS = {cfg.get('mosaic_n_designs', 100)}  # Stage 1: how many designs to generate per length\n"
        f"TOP_K = {cfg.get('mosaic_top_k', cfg['n_designs'])}  # Stage 2: how many top designs to refold and export PDB\n"
        f"MIN_LENGTH = {cfg.get('mosaic_min_length', cfg['min_length'])}  # minimum binder length (aa)\n"
        f"MAX_LENGTH = {cfg.get('mosaic_max_length', cfg['max_length'])}  # maximum binder length (aa)\n"
        f"LENGTH_STEP = {cfg.get('mosaic_length_step', 5)}  # step between scanned lengths; set MIN=MAX for a single length"
    )

    if old_block in content:
        content = content.replace(old_block, new_block)
    else:
        print_warn("Could not inject parameters block — please edit hallucinate.py manually.")

    path.write_text(content)


def write_run_bindcraft(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    conda_base = str(CONDA_BASE) if CONDA_BASE else ""
    bindmaster_dir = str(BINDMASTER_DIR)
    content = f"""\
#!/usr/bin/env bash
# Run BindCraft for {cfg["name"]}
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
    "{bindmaster_dir}/conda/etc/profile.d/conda.sh" \\
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

# aarch64/Blackwell: JAX CUDA backend may not support sm_121
if [[ "$(uname -m)" == "aarch64" ]]; then
    export JAX_PLATFORMS=cpu
fi

cd "$BINDCRAFT_DIR"

echo "=== Running BindCraft for {cfg["name"]} ==="
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
    bindmaster_dir = str(BINDMASTER_DIR)
    content = f"""\
#!/usr/bin/env bash
# Run BoltzGen for {cfg["name"]}
# Generated by BindMaster Configurator
set -euo pipefail

CONFIG="{run_dir}/boltzgen/config.yaml"
OUTPUT_DIR="{run_dir}/boltzgen/outputs"

# Robust conda init — works in non-interactive shells (no conda on PATH by default)
# set +u: conda activate.d scripts may reference unbound variables
set +u
_conda_found=false
for _conda_sh in \\
    "{bindmaster_dir}/conda/etc/profile.d/conda.sh" \\
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

# aarch64/Blackwell: set CUDA arch for Triton JIT compilation
if [[ "$(uname -m)" == "aarch64" ]]; then
    export TORCH_CUDA_ARCH_LIST="12.0"
fi

echo "=== Running BoltzGen for {cfg["name"]} ==="
boltzgen run "$CONFIG" \\
    --output "$OUTPUT_DIR" \\
    --protocol protein-anything \\
    --num_designs {cfg["boltzgen_intermediate"]} \\
    --budget {cfg["n_designs"]}
"""
    path.write_text(content)
    path.chmod(0o755)


def write_run_mosaic(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    mosaic_python = MOSAIC_VENV / "bin" / "python"
    content = f"""\
#!/usr/bin/env bash
# Run Mosaic for {cfg["name"]}
# Generated by BindMaster Configurator
set -euo pipefail

MOSAIC_PYTHON="{mosaic_python}"
MOSAIC_DIR="{run_dir}/mosaic"

if [[ ! -x "$MOSAIC_PYTHON" ]]; then
    echo "ERROR: Mosaic uv venv not found at $MOSAIC_PYTHON" >&2
    echo "Run: bindmaster install --tool mosaic  (or: bash {BINDMASTER_DIR}/install/install.sh --tool mosaic)" >&2
    exit 1
fi

echo "=== Running Mosaic for {cfg["name"]} ==="
cd "$MOSAIC_DIR"
"$MOSAIC_PYTHON" hallucinate.py
"""
    path.write_text(content)
    path.chmod(0o755)


def write_pxdesign_yaml(path: Path, cfg: dict):
    """Write PXDesign input YAML for local run (stdlib-only, no PyYAML)."""
    chains_str = cfg.get("pxdesign_chains", cfg.get("chains", "A"))
    chain_ids = [c.strip() for c in chains_str.split(",")]
    hotspots_str = cfg.get("pxdesign_hotspots", "") or cfg.get("hotspots", "") or ""
    hotspot_list = parse_hotspots(hotspots_str) if hotspots_str.strip() else []

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


def _pxdesign_conda_header(cfg: dict) -> str:
    """Return the common bash header for PXDesign run scripts (conda init + env vars)."""
    conda_base = str(CONDA_BASE) if CONDA_BASE else ""
    bindmaster_dir = str(BINDMASTER_DIR)
    return f"""\
#!/usr/bin/env bash
# Run PXDesign for {cfg["name"]}
# Generated by BindMaster Configurator
set -euo pipefail

PXDESIGN_DIR="{PXDESIGN_DIR}"

# Robust conda init
set +u
_conda_found=false
for _conda_sh in \\
    "{bindmaster_dir}/conda/etc/profile.d/conda.sh" \\
    "{conda_base}/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniforge3/etc/profile.d/conda.sh" \\
    "${{HOME}}/mambaforge/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniconda3/etc/profile.d/conda.sh" \\
    "${{HOME}}/anaconda3/etc/profile.d/conda.sh" \\
    "/opt/conda/etc/profile.d/conda.sh" \\
    "/opt/miniforge3/etc/profile.d/conda.sh"; do
    [[ -f "$_conda_sh" ]] && {{ source "$_conda_sh"; _conda_found=true; break; }}
done
[[ "$_conda_found" == true ]] || {{ echo "ERROR: conda not found." >&2; exit 1; }}
conda activate bindmaster_pxdesign
export CUDA_HOME="$CONDA_PREFIX"

# Surface CUDA dev headers + libs for PyTorch's JIT compiler.
# - cuda_runtime_api.h ships only under $CONDA_PREFIX/targets/x86_64-linux/include
#   (conda-forge cuda-cudart-dev layout), not under $CONDA_PREFIX/include.
# - cuBLAS / cuDNN / NCCL dev headers ship via the pip nvidia-*-cu12 wheels at
#   site-packages/nvidia/<lib>/include — needed by protenix's JIT layer-norm op.
# Without this, the first 'pxdesign pipeline' run dies with
#   "fatal error: cuda_runtime_api.h: No such file or directory"
# and "fatal error: cublas_v2.h: No such file or directory".
NVIDIA_DIR="$CONDA_PREFIX/lib/python3.11/site-packages/nvidia"
if [[ -d "$NVIDIA_DIR" ]]; then
    NVIDIA_INC=$(ls -d "$NVIDIA_DIR"/*/include 2>/dev/null | tr '\\n' ':' | sed 's/:$//')
    NVIDIA_LIB=$(ls -d "$NVIDIA_DIR"/*/lib 2>/dev/null | tr '\\n' ':' | sed 's/:$//')
    export CPATH="${{NVIDIA_INC}}:$CONDA_PREFIX/targets/x86_64-linux/include${{CPATH:+:$CPATH}}"
    export LIBRARY_PATH="${{NVIDIA_LIB}}:$CONDA_PREFIX/targets/x86_64-linux/lib${{LIBRARY_PATH:+:$LIBRARY_PATH}}"
    export LD_LIBRARY_PATH="${{NVIDIA_LIB}}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
fi
set -u

# aarch64/Blackwell: CUDA arch list and JAX CPU-only mode
if [[ "$(uname -m)" == "aarch64" ]]; then
    export TORCH_CUDA_ARCH_LIST="12.0"
    export JAX_PLATFORMS=cpu
fi

cd "$PXDESIGN_DIR"
"""


def _pxdesign_sequence_collector(run_dir: str, top_per_length: int = 0) -> str:
    """Return shell snippet that extracts binder sequences from PXDesign pipeline outputs.

    Preferred input: filtered_summary.csv from each per-length pipeline run.  This
    file is already ranked by PXDesign's pre_filter_extended (or pre_filter_preview),
    which assigns success buckets using both AF2 (af2_opt_success / af2_easy_success)
    and Protenix (ptx_success / ptx_basic_success) signals, then breaks ties by
    Protenix ipTM (extended) or AF2 unscaled_i_pAE (preview).  rank=1 is best.

    If top_per_length > 0, only the top K rows (by rank) per length are kept.

    Falls back to per-seed sample_level_output.csv (unranked) and finally to CIF
    parsing if neither summary CSV is present.
    """
    return f"""
# ============================================================
# Collect binder sequences from PXDesign pipeline outputs
# ============================================================
echo ""
echo "=== Collecting binder sequences ==="
python3 -c "
import csv, re, sys
from pathlib import Path

pxd_dir = Path('{run_dir}/pxdesign')
TOP_PER_LENGTH = {int(top_per_length)}
rows = []

def _to_float(v, default=float('-inf')):
    try:
        return float(str(v).strip('[]'))
    except (TypeError, ValueError):
        return default

def _row_from(r, slcsv, length_val):
    seq = r.get('sequence', '').strip()
    if not seq or set(seq) == {{'X'}}:
        return None
    name = r.get('name', r.get('design_id', slcsv.stem))
    return {{
        'design_id': f'pxdesign_{{name}}',
        'sequence': seq,
        'length': len(seq),
        'binder_length': length_val,
        'pxdesign_rank': r.get('rank', '').strip(),
        'pxdesign_bucket': r.get('bucket', '').strip(),
        'af2_iptm': r.get('i_pTM', r.get('af2_complex_ipTM', '')).strip('[]'),
        'af2_plddt': r.get('pLDDT', r.get('af2_complex_pLDDT_binder', '')).strip('[]'),
        'af2_ipae': r.get('unscaled_i_pAE', '').strip('[]'),
        'ptx_iptm': r.get('ptx_iptm', r.get('ptx_mini_iptm', '')).strip('[]'),
        'source': 'pxdesign',
    }}

# --- Strategy 1: PXDesign's own ranked output (preferred) ---
for slcsv in sorted(pxd_dir.rglob('filtered_summary.csv')):
    length_m = re.search(r'outputs_len(\\d+)', str(slcsv))
    length_val = length_m.group(1) if length_m else '?'
    per_length = []
    with open(slcsv) as f:
        reader = csv.DictReader(f)
        for r in reader:
            row = _row_from(r, slcsv, length_val)
            if row is not None:
                per_length.append(row)
    # rows are already sorted by rank ASC (best first); slice if asked.
    per_length.sort(key=lambda d: _to_float(d['pxdesign_rank'], default=float('inf')))
    if TOP_PER_LENGTH > 0 and len(per_length) > TOP_PER_LENGTH:
        kept = per_length[:TOP_PER_LENGTH]
        print(f'  length {{length_val}}: kept {{len(kept)}}/{{len(per_length)}} by pxdesign rank')
        rows.extend(kept)
    else:
        rows.extend(per_length)

# --- Strategy 2: per-seed sample_level_output.csv (only if no filtered_summary) ---
if not rows:
    print('  No filtered_summary.csv found — falling back to unranked sample CSVs')
    for slcsv in sorted(pxd_dir.rglob('sample_level_output.csv')):
        length_m = re.search(r'outputs_len(\\d+)', str(slcsv))
        length_val = length_m.group(1) if length_m else '?'
        per_length = []
        with open(slcsv) as f:
            reader = csv.DictReader(f)
            for r in reader:
                row = _row_from(r, slcsv, length_val)
                if row is not None:
                    per_length.append(row)
        if TOP_PER_LENGTH > 0 and len(per_length) > TOP_PER_LENGTH:
            # Fallback rank: by AF2 i_pTM only (proper composite needs ptx cols)
            per_length.sort(key=lambda d: _to_float(d['af2_iptm']), reverse=True)
            kept = per_length[:TOP_PER_LENGTH]
            print(f'  length {{length_val}}: kept {{len(kept)}}/{{len(per_length)}} by af2 i_pTM (fallback)')
            rows.extend(kept)
        else:
            rows.extend(per_length)

if rows:
    print(f'  Found {{len(rows)}} sequences from pipeline CSVs')
else:
    # --- Strategy 3: fall back to CIF entity_poly_seq parsing ---
    AA3TO1 = {{
        'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E',
        'GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F',
        'PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V','MSE':'M',
    }}
    def binder_seq_from_cif(cif_path):
        lines = Path(cif_path).read_text().splitlines()
        in_poly_seq = False
        residues = {{}}
        for line in lines:
            if line.startswith('_entity_poly_seq.'):
                in_poly_seq = True
                continue
            if in_poly_seq:
                if line.startswith('#') or line.startswith('_') or line.startswith('loop_'):
                    in_poly_seq = False
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    eid, mon, num = parts[0], parts[2], int(parts[3])
                    residues.setdefault(eid, []).append((num, AA3TO1.get(mon, 'X')))
        if '2' in residues:
            seq = ''.join(aa for _, aa in sorted(residues['2']))
            if set(seq) != {{'X'}}:
                return seq
        return None
    for cif in sorted(pxd_dir.rglob('predictions/*.cif')):
        seq = binder_seq_from_cif(cif)
        if seq:
            length_m = re.search(r'outputs_len(\\d+)', str(cif))
            rows.append({{
                'design_id': f'pxdesign_{{cif.stem}}',
                'sequence': seq,
                'length': len(seq),
                'binder_length': length_m.group(1) if length_m else '?',
                'source': 'pxdesign',
            }})
    if rows:
        print(f'  Found {{len(rows)}} sequences from CIF files (fallback)')

if not rows:
    print('WARNING: No binder sequences extracted', file=sys.stderr)
    sys.exit(0)

out_csv = pxd_dir / 'sequences.csv'
with open(out_csv, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f'  -> {{len(rows)}} binder sequences written to {{out_csv}}')
"
"""


def write_run_pxdesign(path: Path, cfg: dict):
    """Generate run_pxdesign.sh for local PXDesign execution."""
    run_dir = cfg["run_dir"]
    preset = cfg.get("pxdesign_preset", "preview")
    n_samples = cfg.get("pxdesign_n_samples", 1000)
    length_scan = cfg.get("pxdesign_length_scan", False)
    top_per_length = int(cfg.get("pxdesign_top_per_length", 0) or 0)

    header = _pxdesign_conda_header(cfg)

    if length_scan:
        min_len = cfg.get("pxdesign_min_length", 40)
        max_len = cfg.get("pxdesign_max_length", 140)
        step = cfg.get("pxdesign_length_step", 20)
        target_pdb = cfg["target_pdb"]
        chains_str = cfg.get("pxdesign_chains", cfg.get("chains", "A"))
        chain_ids = [c.strip() for c in chains_str.split(",")]
        hotspots_str = cfg.get("pxdesign_hotspots", "") or cfg.get("hotspots", "") or ""
        hotspot_list = parse_hotspots(hotspots_str) if hotspots_str.strip() else []

        # Build YAML chain lines
        chain_lines = ""
        for cid in chain_ids:
            if hotspot_list:
                hs = ", ".join(str(h) for h in hotspot_list)
                chain_lines += f"    {cid}:\\n      hotspots: [{hs}]\\n"
            else:
                chain_lines += f"    {cid}: all\\n"

        content = (
            header
            + f"""
RUN_DIR="{run_dir}"
TARGET_PDB="{target_pdb}"

MIN_LENGTH={min_len}
MAX_LENGTH={max_len}
LENGTH_STEP={step}
N_SAMPLES={n_samples}

echo "=== PXDesign Length Scan for {cfg["name"]} ==="
echo "  Lengths: ${{MIN_LENGTH}} to ${{MAX_LENGTH}} (step ${{LENGTH_STEP}})"
echo "  Samples per length: ${{N_SAMPLES}}"

TOTAL_DESIGNS=0

for LENGTH in $(seq "$MIN_LENGTH" "$LENGTH_STEP" "$MAX_LENGTH"); do
    echo ""
    echo "=================================================="
    echo "  Length: ${{LENGTH}} aa  |  ${{N_SAMPLES}} samples"
    echo "=================================================="

    OUTPUT_DIR="$RUN_DIR/pxdesign/outputs_len${{LENGTH}}"
    INPUT_YAML="$RUN_DIR/pxdesign/input_len${{LENGTH}}.yaml"

    # Generate per-length input YAML
    printf 'binder_length: %d\\ntarget:\\n  file: %s\\n  chains:\\n{chain_lines}' \\
        "$LENGTH" "$TARGET_PDB" > "$INPUT_YAML"

    pxdesign pipeline \\
        --preset {preset} \\
        --N_sample "$N_SAMPLES" \\
        --dtype bf16 \\
        -i "$INPUT_YAML" \\
        -o "$OUTPUT_DIR"

    N_DESIGNS=$(find "$OUTPUT_DIR" \\( -name "*.pdb" -o -name "*.cif" \\) 2>/dev/null | wc -l)
    TOTAL_DESIGNS=$((TOTAL_DESIGNS + N_DESIGNS))
    echo "  -> ${{N_DESIGNS}} designs at length ${{LENGTH}}"
done

echo ""
echo "=== Length Scan Complete ==="
echo "  Total designs: ${{TOTAL_DESIGNS}}"
"""
        )
    else:
        content = (
            header
            + f"""
INPUT_YAML="{run_dir}/pxdesign/input.yaml"
OUTPUT_DIR="{run_dir}/pxdesign/outputs"

echo "=== Running PXDesign for {cfg["name"]} ==="

pxdesign pipeline \\
    --preset {preset} \\
    --N_sample {n_samples} \\
    --dtype bf16 \\
    -i "$INPUT_YAML" \\
    -o "$OUTPUT_DIR"
"""
        )

    # Append sequence extraction step (common to both modes)
    content += _pxdesign_sequence_collector(run_dir, top_per_length=top_per_length)

    path.write_text(content)
    path.chmod(0o755)


def write_run_all(path: Path, cfg: dict, tools_enabled: dict):
    run_dir = cfg["run_dir"]
    lines = [
        "#!/usr/bin/env bash",
        f"# Run all enabled tools for {cfg['name']} in order: Mosaic → BoltzGen → BindCraft → PXDesign → Proteina-Complexa → RFD3 → Protein-Hunter → Evaluator",
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
            "# Mosaic is interactive — run it separately before the pipeline:",
            '#   bash "$RUN_DIR/run_mosaic.sh"',
            "# Then re-run this script. It will skip Mosaic if designs.csv already exists.",
            'echo "=== Step: Mosaic ==="',
            'if [[ -f "$RUN_DIR/mosaic/designs.csv" ]]; then',
            '    echo "  Mosaic designs.csv found — skipping interactive run."',
            "else",
            '    echo "  Mosaic requires interactive input. Run run_mosaic.sh first, then re-run run_all.sh." >&2',
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

    if tools_enabled.get("pxdesign_local"):
        lines += [
            'echo "=== Step: PXDesign ==="',
            '"$RUN_DIR/run_pxdesign.sh"',
            # In length-scan mode the script writes per-length outputs_lenN/ dirs
            # and aggregates into sequences.csv — pxdesign/outputs/ never exists.
            # Check the unified CSV like the other tools do.
            'check_outputs "$RUN_DIR/pxdesign/sequences.csv" "PXDesign"',
            "",
        ]

    if tools_enabled.get("proteina_complexa"):
        lines += [
            'echo "=== Step: Proteina-Complexa ==="',
            '"$RUN_DIR/run_proteina_complexa.sh"',
            'check_outputs "$RUN_DIR/proteina_complexa/sequences.csv" "Proteina-Complexa"',
            "",
        ]

    if tools_enabled.get("rfd3"):
        lines += [
            'echo "=== Step: RFD3 ==="',
            '"$RUN_DIR/run_rfd3.sh"',
            'check_outputs "$RUN_DIR/rfd3/sequences.csv" "RFD3"',
            "",
        ]

    if tools_enabled.get("protein_hunter"):
        lines += [
            'echo "=== Step: Protein-Hunter ==="',
            '"$RUN_DIR/run_protein_hunter.sh"',
            'check_outputs "$RUN_DIR/protein_hunter/sequences.csv" "Protein-Hunter"',
            "",
        ]

    if tools_enabled.get("evaluator"):
        lines += [
            'echo "=== Step: Evaluator ==="',
            '"$RUN_DIR/run_evaluate.sh"',
            "",
        ]

    lines += ['echo ""', 'echo "=== Pipeline complete! ==="']

    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o755)


def write_run_proteina_complexa(path: Path, cfg: dict):
    """Generate run_proteina_complexa.sh for Proteina-Complexa binder design."""
    run_dir = cfg["run_dir"]
    search_algo = cfg.get("complexa_search_algorithm", "best-of-n")
    replicas = cfg.get("complexa_replicas", 2)
    n_designs = cfg.get("complexa_n_designs", 100)
    min_len = cfg.get("complexa_min_length", cfg.get("min_length", 65))
    max_len = cfg.get("complexa_max_length", cfg.get("max_length", 150))
    chains_str = cfg.get("complexa_chains", cfg.get("chains", "A"))
    hotspots_str = cfg.get("complexa_hotspots", "") or cfg.get("hotspots", "") or ""
    target_pdb = cfg["target_pdb"]
    # Optional quality knobs (None = let Complexa default apply, no Hydra override)
    mcts_n_simulations = cfg.get("complexa_mcts_n_simulations")
    nres_nsamples = cfg.get("complexa_nres_nsamples")
    refinement = cfg.get("complexa_refinement")  # e.g. "sequence_hallucination" or None

    # Build the target YAML entry for Complexa
    chain_ids = [c.strip() for c in chains_str.split(",")]
    hotspot_list = parse_hotspots(hotspots_str) if hotspots_str.strip() else []

    target_input_lines = []
    for cid in chain_ids:
        target_input_lines.append(f"      {cid}:")
        if hotspot_list:
            hs = ", ".join(str(h) for h in hotspot_list)
            target_input_lines.append(f"        hotspot_residues: [{hs}]")

    target_input_yaml = "\n".join(target_input_lines)

    # Optional Hydra overrides (each ends with ` \\` so it sits on its own
    # continuation line in the heredoc).  Built outside the f-string to stay
    # py310-compatible (PEP 701 nested f-string escapes are 3.12+).
    extra_overrides = ""
    if mcts_n_simulations is not None:
        extra_overrides += f"\n    ++generation.search.mcts.n_simulations={mcts_n_simulations} \\"
    if nres_nsamples is not None:
        extra_overrides += f"\n    ++generation.dataloader.dataset.nres.nsamples={nres_nsamples} \\"
    if refinement:
        extra_overrides += f"\n    ++generation.refinement.algorithm={refinement} \\"

    content = f"""\
#!/usr/bin/env bash
# Run Proteina-Complexa for {cfg["name"]}
# Generated by BindMaster Configurator
set -euo pipefail

PROTEINA_COMPLEXA_DIR="{PROTEINA_COMPLEXA_DIR}"
RUN_DIR="{run_dir}"

# Activate Proteina-Complexa uv venv
source "${{PROTEINA_COMPLEXA_DIR}}/.venv/bin/activate"
cd "${{PROTEINA_COMPLEXA_DIR}}"

echo "=== Running Proteina-Complexa for {cfg["name"]} ==="

# Write custom target definition
TARGET_YAML="$RUN_DIR/proteina_complexa/target_bindmaster.yaml"
mkdir -p "$RUN_DIR/proteina_complexa"
cat > "$TARGET_YAML" << 'TARGETEOF'
target_dict_cfg:
  bindmaster_{cfg["name"]}:
    source: bindmaster
    target_filename: "{cfg["name"]}"
    target_path: "{target_pdb}"
    target_input:
{target_input_yaml}
    binder_length: [{min_len}, {max_len}]
    pdb_id: null
TARGETEOF

echo "  Target: {target_pdb}"
echo "  Chains: {chains_str}"
echo "  Binder length: {min_len}-{max_len}"
echo "  Search algorithm: {search_algo}"
echo "  Replicas: {replicas}"
echo "  Max designs: {n_designs}"
echo "  MCTS n_simulations: {mcts_n_simulations if mcts_n_simulations is not None else "(default)"}"
echo "  Length samples (nres.nsamples): {nres_nsamples if nres_nsamples is not None else "(default)"}"
echo "  Refinement: {refinement or "(none)"}"
echo ""

# Run Proteina-Complexa design pipeline
complexa design configs/search_binder_local_pipeline.yaml \\
    ++run_name="{cfg["name"]}" \\
    ++generation.task_name="bindmaster_{cfg["name"]}" \\
    ++generation.dataloader.dataset.nres.low={min_len} \\
    ++generation.dataloader.dataset.nres.high={max_len} \\
    ++generation.search.algorithm={search_algo} \\
    ++generation.search.best_of_n.replicas={replicas} \\
    ++generation.filter.filter_samples_limit={n_designs} \\{extra_overrides}
    ++targets_dict="$TARGET_YAML"

echo ""
echo "=== Proteina-Complexa design complete ==="

# Collect binder sequences from outputs
echo "=== Collecting binder sequences ==="
python3 -c "
import csv, glob, sys
from pathlib import Path

pc_dir = Path('$RUN_DIR/proteina_complexa')
run_name = '{cfg["name"]}'

# Find evaluation result CSVs from Complexa outputs
rows = []
eval_dir = Path('outputs') / run_name
if not eval_dir.exists():
    # Try finding in complexa's default output location
    for p in Path('.').rglob('evaluation_results'):
        if run_name in str(p):
            eval_dir = p
            break

# Strategy 1: Parse evaluation_results CSVs
for csv_path in sorted(eval_dir.rglob('*.csv')) if eval_dir.exists() else []:
    try:
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for r in reader:
                seq = r.get('sequence', '').strip()
                if not seq or set(seq) == {{'X'}}:
                    continue
                name = r.get('name', r.get('sample_id', csv_path.stem))
                ipae = r.get('self_complex_i_pAE', '')
                iptm = r.get('self_complex_i_pTM', '')
                plddt = r.get('self_complex_pLDDT', '')
                scrmsd = r.get('self_binder_scRMSD', '')
                rows.append({{
                    'design_id': f'complexa_{{name}}',
                    'sequence': seq,
                    'length': len(seq),
                    'iptm': iptm,
                    'plddt_binder_mean': plddt,
                    'pae_bt_mean': ipae,
                    'scrmsd_binder': scrmsd,
                    'source': 'proteina_complexa',
                }})
    except Exception as e:
        print(f'  Warning: could not parse {{csv_path}}: {{e}}', file=sys.stderr)

# Strategy 2: Fall back to PDB sequence extraction
if not rows:
    AA3TO1 = {{
        'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E',
        'GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F',
        'PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V','MSE':'M',
    }}
    for pdb_path in sorted(eval_dir.rglob('*.pdb')) if eval_dir.exists() else []:
        try:
            seen = {{}}
            with open(pdb_path) as f:
                for line in f:
                    if line[:4] != 'ATOM' or line[12:16].strip() != 'CA':
                        continue
                    if line[21].strip().upper() != 'B':
                        continue
                    res = line[17:20].strip().upper()
                    key = (line[22:26].strip(), line[26].strip())
                    if key not in seen:
                        seen[key] = AA3TO1.get(res, 'X')
            seq = ''.join(seen.values())
            if seq and set(seq) != {{'X'}}:
                rows.append({{
                    'design_id': f'complexa_{{pdb_path.stem}}',
                    'sequence': seq,
                    'length': len(seq),
                    'source': 'proteina_complexa',
                }})
        except Exception:
            pass
    if rows:
        print(f'  Found {{len(rows)}} sequences from PDB files (fallback)')

if not rows:
    print('WARNING: No binder sequences extracted from Proteina-Complexa', file=sys.stderr)
    sys.exit(0)

out_csv = pc_dir / 'sequences.csv'
with open(out_csv, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f'  -> {{len(rows)}} binder sequences written to {{out_csv}}')
"
"""

    path.write_text(content)
    path.chmod(0o755)


def write_run_rfd3(path: Path, cfg: dict):
    """Generate run_rfd3.sh — two-stage RFD3 (backbone diffusion) + ProteinMPNN (sequences).

    Mirrors bindmaster_examples/run_rfd3.sh.template (the canonical CALCA-validated
    pattern).  See CLAUDE.md "RFD3 / foundry runtime gotchas" for non-obvious bits:
      - rfd3 design writes .cif.gz with UNK residues (no real sequence)
      - chain IDs in output are A=target, B=binder (matches contig order)
      - sequence design CLI is `mpnn`, not `foundry mpnn`; needs --is_legacy_weights True
      - --designed_chains wants JSON, e.g. '["B"]'
      - FOUNDRY_CHECKPOINT_DIRS env var is plural
      - ProteinMPNN weights need `foundry install proteinmpnn` separately
      - mpnn writes N sequences per backbone in one .fa with sequence_recovery= header
        tags; best-of-N selection is post-processed (highest recovery, strip target prefix)
    """
    run_dir = cfg["run_dir"]
    target_pdb = Path(cfg["target_pdb"])
    primary_chain = cfg.get("chains", "A").split(",")[0].strip()
    target_seq = cfg.get("target_sequence", "")
    target_len = len(target_seq)
    if target_len == 0:
        # Fallback: count CA atoms on the primary chain.
        try:
            target_len = sum(
                1
                for line in target_pdb.read_text().splitlines()
                if line.startswith("ATOM") and line[12:16].strip() == "CA" and line[21] == primary_chain
            )
        except OSError:
            target_len = 0

    min_len = cfg.get("rfd3_min_length", cfg.get("min_length", 60))
    max_len = cfg.get("rfd3_max_length", cfg.get("max_length", 150))
    n_designs = cfg.get("rfd3_n_designs", cfg.get("n_designs", 50))
    batch_size = cfg.get("rfd3_batch_size", 8)
    # Round n_batches up so at least n_designs samples are produced.
    n_batches = max(1, -(-n_designs // batch_size))
    diffusion_steps = cfg.get("rfd3_diffusion_steps", 200)
    step_scale = cfg.get("rfd3_step_scale", 1.5)
    mpnn_samples = cfg.get("rfd3_mpnn_samples", 5)
    mpnn_temperature = cfg.get("rfd3_mpnn_temperature", 0.1)

    hotspots_str = cfg.get("rfd3_hotspots") or cfg.get("hotspots", "") or ""
    hotspot_list = parse_hotspots(hotspots_str) if hotspots_str.strip() else []
    # Build select_hotspots as a comma-separated component string ("A15,A18,...")
    # rfd3's parsing.canonicalize_() will treat each as a token-level hotspot.
    select_hotspots_str = ",".join(f"{primary_chain}{r}" for r in hotspot_list) if hotspot_list else ""

    name = cfg["name"]

    content = f"""\
#!/usr/bin/env bash
# Run RFdiffusion3 (foundry) + ProteinMPNN for {name}
# Generated by BindMaster Configurator (mirrors bindmaster_examples/run_rfd3.sh.template).
#
# Two-stage flow:
#   1. rfd3 design  → .cif.gz backbones (chain A=target, chain B=binder, UNK residues)
#   2. mpnn         → N=mpnn_samples ProteinMPNN sequences per backbone (best-of-N)
#
# See CLAUDE.md "RFD3 / foundry runtime gotchas" for the non-obvious pitfalls.
set -euo pipefail

RUN_DIR="{run_dir}"
RFD3_DIR="$RUN_DIR/rfd3"
TARGET_PDB="{target_pdb}"
TARGET_SEQ="{target_seq}"
DIFF_DIR="$RFD3_DIR/diffusion"
MPNN_DIR="$RFD3_DIR/mpnn"
INPUTS_YAML="$RFD3_DIR/binder_spec.yaml"
WEIGHTS_DIR="{FOUNDRY_WEIGHTS_DIR}"

mkdir -p "$DIFF_DIR" "$MPNN_DIR"

# Robust conda init
set +u
_conda_found=false
for _conda_sh in \\
    "{BINDMASTER_DIR}/conda/etc/profile.d/conda.sh" \\
    "{CONDA_BASE}/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniforge3/etc/profile.d/conda.sh" \\
    "${{HOME}}/mambaforge/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniconda3/etc/profile.d/conda.sh" \\
    "${{HOME}}/anaconda3/etc/profile.d/conda.sh" \\
    "/opt/conda/etc/profile.d/conda.sh" \\
    "/opt/miniforge3/etc/profile.d/conda.sh"; do
    # shellcheck disable=SC1090
    [[ -f "$_conda_sh" ]] && {{ source "$_conda_sh"; _conda_found=true; break; }}
done
[[ "$_conda_found" == true ]] || {{ echo "ERROR: conda not found." >&2; exit 1; }}
conda activate bindmaster_rfd3

# foundry's checkpoint registry reads FOUNDRY_CHECKPOINT_DIRS / FOUNDRY_CHECKPOINTS_DIR.
# Singular FOUNDRY_CHECKPOINT_DIR is silently ignored (rfd3 design then aborts with
# "Invalid checkpoint: rfd3" even with the .ckpt sitting in the weights dir).
export FOUNDRY_CHECKPOINT_DIRS="$WEIGHTS_DIR"
set -u

# ── Stage 1: backbone diffusion ─────────────────────────────────────────────
# Contig: target first (preserved residues), then chain break (/0), then binder
# length range. RFD3 labels the preserved chain as A and the designed chain as B.
cat > "$INPUTS_YAML" <<INPUTSEOF
{name}:
  input: $TARGET_PDB
  contig: "{primary_chain}1-{target_len},/0,{min_len}-{max_len}"
  infer_ori_strategy: hotspots{("  # COM falls back when select_hotspots is empty" if not select_hotspots_str else "")}{(chr(10) + '  select_hotspots: "' + select_hotspots_str + '"') if select_hotspots_str else ""}
INPUTSEOF

echo "=== RFD3 backbone diffusion for {name} ==="
echo "  Target:        $TARGET_PDB"
echo "  Contig:        {primary_chain}1-{target_len},/0,{min_len}-{max_len}"
echo "  Hotspots:      {select_hotspots_str or "(none)"}"
echo "  Designs:       {n_designs}  (batch_size={batch_size} x n_batches={n_batches} = {batch_size * n_batches})"
echo "  Diffusion:     T={diffusion_steps}, step_scale={step_scale}"
echo "  Checkpoint:    $WEIGHTS_DIR/rfd3_latest.ckpt"
echo ""

rfd3 design \\
    out_dir="$DIFF_DIR" \\
    inputs="$INPUTS_YAML" \\
    n_batches={n_batches} \\
    diffusion_batch_size={batch_size} \\
    inference_sampler.num_timesteps={diffusion_steps} \\
    inference_sampler.step_scale={step_scale} \\
    low_memory_mode=true \\
    prevalidate_inputs=true

# Output: <design>.cif.gz (compressed mmCIF, chain A=target, chain B=binder, UNK)
#         <design>.json   (sidecar metrics: helix_fraction, n_clashing, ...)

# ── Stage 2: ensure ProteinMPNN weights are installed ──────────────────────
# rfd3's `foundry install rfd3` only fetches rfd3_latest.ckpt — proteinmpnn is separate.
PROTEINMPNN_CKPT="$WEIGHTS_DIR/proteinmpnn_v_48_020.pt"
if [[ ! -f "$PROTEINMPNN_CKPT" ]]; then
    echo ""
    echo "Installing ProteinMPNN weights..."
    foundry install proteinmpnn --checkpoint-dir "$WEIGHTS_DIR"
fi

# ── Stage 3: ProteinMPNN sequence design (best-of-{mpnn_samples} per backbone) ──
# Gotchas:
#   - The CLI is `mpnn`, NOT `foundry mpnn` (foundry only has install / list-* / clean).
#   - --is_legacy_weights True is required when calling mpnn directly.
#   - --designed_chains wants a JSON list of letter strings (e.g. '["B"]').
#     Bare `B` or bare `1` get rejected with `chain-id strings, got <int>`.
echo ""
echo "=== ProteinMPNN sequence design ({mpnn_samples} per backbone, T={mpnn_temperature}) ==="

CIFS=("$DIFF_DIR"/*.cif.gz)
if [[ ! -e "${{CIFS[0]}}" ]]; then
    echo "ERROR: no .cif.gz backbones produced by rfd3 design" >&2
    exit 1
fi
N=${{#CIFS[@]}}
DONE=0
for CIF in "${{CIFS[@]}}"; do
    NAME=$(basename "$CIF" .cif.gz)
    OUT_FA="$MPNN_DIR/${{NAME}}.fa"
    if [[ -f "$OUT_FA" ]]; then
        DONE=$((DONE + 1))
        continue
    fi
    mpnn \\
        --structure_path "$CIF" \\
        --checkpoint_path "$PROTEINMPNN_CKPT" \\
        --model_type protein_mpnn \\
        --is_legacy_weights True \\
        --out_directory "$MPNN_DIR" \\
        --name "$NAME" \\
        --designed_chains '["B"]' \\
        --temperature {mpnn_temperature} \\
        --number_of_batches {mpnn_samples} \\
        --batch_size 1 \\
        --write_fasta True \\
        --write_structures False \\
        --seed 42 \\
        > /dev/null 2>&1 || {{ echo "  WARN: mpnn failed for $NAME"; continue; }}
    DONE=$((DONE + 1))
    if (( DONE % 50 == 0 )); then
        echo "  $DONE/$N MPNN passes done"
    fi
done

# ── Stage 4: aggregate best-of-N per backbone, strip target prefix ─────────
# mpnn writes one .fa per backbone with N sequences (target+binder concatenated).
# Pick the highest-recovery one per file; the binder sequence is the suffix
# after the first len(target_seq) chars.
echo ""
echo "=== Aggregating best-of-{mpnn_samples} sequences ==="
python3 - "$MPNN_DIR" "$RFD3_DIR" "$TARGET_SEQ" <<'PYEOF'
import csv, re, sys
from pathlib import Path

mpnn_dir = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
target_seq = sys.argv[3]
target_len = len(target_seq)

rows = []
for fa in sorted(mpnn_dir.glob("*.fa")):
    candidates = []
    with fa.open() as f:
        hdr = None
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith(">"):
                hdr = line[1:]
            elif hdr is not None:
                m = re.search(r"sequence_recovery=([0-9.]+)", hdr)
                rec = float(m.group(1)) if m else 0.0
                seq = line.strip().upper()
                if seq:
                    candidates.append((rec, seq, hdr))
                hdr = None
    if not candidates:
        continue
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_rec, best_full, _ = candidates[0]
    binder_seq = best_full[target_len:]
    if not binder_seq or set(binder_seq) == {{"X"}}:
        continue
    rows.append({{
        "design_id": f"rfd3_{{fa.stem}}",
        "sequence": binder_seq,
        "length": len(binder_seq),
        "backbone": fa.stem,
        "source": "rfd3",
        "mpnn_sequence_recovery": f"{{best_rec:.4f}}",
        "n_mpnn_samples": len(candidates),
    }})

if not rows:
    print("WARNING: no RFD3 binder sequences extracted", file=sys.stderr)
    sys.exit(0)

with (out_dir / "sequences.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
with (out_dir / "sequences.fasta").open("w") as fh:
    for r in rows:
        fh.write(f">{{r['design_id']}}  length={{r['length']}}  source=rfd3  rec={{r['mpnn_sequence_recovery']}}\\n")
        fh.write(f"{{r['sequence']}}\\n")
print(f"  -> {{len(rows)}} best-per-backbone sequences -> {{out_dir}}/sequences.csv")
PYEOF

echo ""
echo "=== RFD3 + MPNN design complete ==="
echo "  Backbones (cif.gz):  $DIFF_DIR"
echo "  MPNN .fa per design: $MPNN_DIR"
echo "  Aggregated CSV:      $RFD3_DIR/sequences.csv"
echo "  Aggregated FASTA:    $RFD3_DIR/sequences.fasta"
"""
    path.write_text(content)
    path.chmod(0o755)


def write_run_protein_hunter(path: Path, cfg: dict):
    """Generate run_protein_hunter.sh — Boltz-2 protein binder design (Protein-Hunter)."""
    run_dir = cfg["run_dir"]
    name = cfg["name"]
    target_seq = cfg.get("target_sequence", "")
    if not target_seq:
        raise RuntimeError("Protein-Hunter needs cfg['target_sequence'] (target chain amino-acid sequence).")

    n_designs = cfg.get("protein_hunter_n_designs", cfg.get("n_designs", 50))
    min_len = cfg.get("protein_hunter_min_length", cfg.get("min_length", 60))
    max_len = cfg.get("protein_hunter_max_length", cfg.get("max_length", 150))
    num_cycles = cfg.get("protein_hunter_num_cycles", 5)
    msa_mode = cfg.get("protein_hunter_msa_mode", "mmseqs")
    iptm_thr = cfg.get("protein_hunter_iptm_threshold", 0.7)
    plddt_thr = cfg.get("protein_hunter_plddt_threshold", 0.7)
    percent_x = cfg.get("protein_hunter_percent_X", 80)
    gpu_id = cfg.get("protein_hunter_gpu_id", 0)
    contact_residues = (cfg.get("protein_hunter_contact_residues") or cfg.get("hotspots", "") or "").strip()

    contact_arg = f' --contact_residues "{contact_residues}"' if contact_residues else ""

    content = f"""\
#!/usr/bin/env bash
# Run Protein-Hunter (Boltz-2 binder design with cycle optimization) for {name}
# Generated by BindMaster Configurator
set -euo pipefail

RUN_DIR="{run_dir}"
PH_DIR="{PROTEIN_HUNTER_DIR}"
PH_OUT="$RUN_DIR/protein_hunter/outputs"
mkdir -p "$PH_OUT"

# Robust conda init
set +u
_conda_found=false
for _conda_sh in \\
    "{BINDMASTER_DIR}/conda/etc/profile.d/conda.sh" \\
    "{CONDA_BASE}/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniforge3/etc/profile.d/conda.sh" \\
    "${{HOME}}/mambaforge/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniconda3/etc/profile.d/conda.sh" \\
    "${{HOME}}/anaconda3/etc/profile.d/conda.sh" \\
    "/opt/conda/etc/profile.d/conda.sh" \\
    "/opt/miniforge3/etc/profile.d/conda.sh"; do
    [[ -f "$_conda_sh" ]] && {{ source "$_conda_sh"; _conda_found=true; break; }}
done
[[ "$_conda_found" == true ]] || {{ echo "ERROR: conda not found." >&2; exit 1; }}
conda activate bindmaster_protein_hunter
set -u

cd "$PH_DIR"

echo "=== Protein-Hunter design for {name} ==="
echo "  Target seq:    {target_seq[:50]}{"..." if len(target_seq) > 50 else ""} ({len(target_seq)} aa)"
echo "  Binder length: {min_len}-{max_len}"
echo "  Designs:       {n_designs}"
echo "  Cycles:        {num_cycles}"
echo "  MSA mode:      {msa_mode}"
echo "  Contacts:      {contact_residues or "(none)"}"
echo "  iPTM thr:      {iptm_thr}"
echo "  Output:        $PH_OUT"
echo ""

python boltz_ph/design.py \\
    --gpu_id {gpu_id} \\
    --name "{name}" \\
    --num_designs {n_designs} \\
    --num_cycles {num_cycles} \\
    --min_protein_length {min_len} \\
    --max_protein_length {max_len} \\
    --protein_seqs "{target_seq}" \\
    --msa_mode {msa_mode} \\
    --high_iptm_threshold {iptm_thr} \\
    --high_plddt_threshold {plddt_thr} \\
    --percent_X {percent_x} \\
    --save_dir "$PH_OUT"{contact_arg}

echo ""
echo "=== Collecting Protein-Hunter binder sequences ==="
python3 - "$PH_OUT" "$RUN_DIR/protein_hunter/sequences.csv" "{name}" <<'PYEOF'
import csv, json, sys
from pathlib import Path
out_dir, csv_path, run_name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
AA3TO1 = {{
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E",
    "GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F",
    "PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V","MSE":"M",
}}
rows = []
# Strategy 1: prefer JSON / FASTA summaries that Protein-Hunter writes per design.
for fasta in sorted(out_dir.rglob("*.fasta")):
    try:
        text = fasta.read_text().splitlines()
        seq_lines, header = [], None
        for line in text:
            if line.startswith(">"):
                if seq_lines:
                    rows.append({{
                        "design_id": f"ph_{{header or fasta.stem}}",
                        "sequence": "".join(seq_lines),
                        "length": len("".join(seq_lines)),
                        "source": "protein_hunter",
                    }})
                header = line[1:].split()[0] if len(line) > 1 else fasta.stem
                seq_lines = []
            elif line.strip():
                seq_lines.append(line.strip())
        if seq_lines:
            rows.append({{
                "design_id": f"ph_{{header or fasta.stem}}",
                "sequence": "".join(seq_lines),
                "length": len("".join(seq_lines)),
                "source": "protein_hunter",
            }})
    except Exception:
        pass

# Strategy 2: fall back to extracting binder sequences from PDB outputs (chain A or first chain).
if not rows:
    for pdb in sorted(out_dir.rglob("*.pdb")):
        seen = {{}}
        chain_seen = None
        with open(pdb) as f:
            for line in f:
                if line[:4] != "ATOM" or line[12:16].strip() != "CA":
                    continue
                ch = line[21]
                if chain_seen is None:
                    chain_seen = ch
                if ch != chain_seen:
                    continue
                key = (line[22:26].strip(), line[26].strip())
                if key not in seen:
                    seen[key] = AA3TO1.get(line[17:20].strip().upper(), "X")
        seq = "".join(seen.values())
        if seq and set(seq) != {{"X"}}:
            rows.append({{
                "design_id": f"ph_{{pdb.stem}}",
                "sequence": seq,
                "length": len(seq),
                "source": "protein_hunter",
            }})

if not rows:
    print("WARNING: no Protein-Hunter binder sequences found", file=sys.stderr)
    sys.exit(0)

# De-duplicate by sequence.
seen_seq = set()
unique = []
for r in rows:
    if r["sequence"] in seen_seq:
        continue
    seen_seq.add(r["sequence"])
    unique.append(r)

with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(unique[0].keys()))
    w.writeheader()
    w.writerows(unique)
print(f"  -> {{len(unique)}} unique sequences written to {{csv_path}}")
PYEOF
"""
    path.write_text(content)
    path.chmod(0o755)


def write_run_evaluate(path: Path, cfg: dict, tools_enabled: dict):
    """Generate run_evaluate.sh — calls Evaluator/evaluate.sh with the right paths."""
    run_dir = cfg["run_dir"]
    eval_dir = run_dir / "evaluate"
    target_pdb = cfg["target_pdb"]
    target_seq = cfg.get("target_sequence", "")

    # Collect design output directories the evaluator should scan
    design_dirs = []
    if tools_enabled.get("mosaic"):
        design_dirs.append(("--mosaic", str(run_dir / "mosaic")))
    if tools_enabled.get("boltzgen"):
        design_dirs.append(("--boltzgen", str(run_dir / "boltzgen" / "outputs")))
    if tools_enabled.get("bindcraft"):
        design_dirs.append(("--bindcraft", str(run_dir / "bindcraft" / "outputs")))
    if tools_enabled.get("pxdesign_local"):
        # Length-scan merges CSVs to pxdesign/summary.csv; fixed-length has outputs/...summary.csv
        # Point extractor at pxdesign/ — it rglobs for summary.csv in either layout
        design_dirs.append(("--pxdesign", str(run_dir / "pxdesign")))
    elif tools_enabled.get("pxdesign") and cfg.get("pxdesign_output_dir"):
        design_dirs.append(("--pxdesign", cfg["pxdesign_output_dir"]))
    if tools_enabled.get("proteina_complexa"):
        design_dirs.append(("--proteina-complexa", str(run_dir / "proteina_complexa")))

    # Build the evaluate.sh invocation
    eval_sh = EVALUATOR_DIR / "evaluate.sh"
    conda_base = str(CONDA_BASE) if CONDA_BASE else ""
    bindmaster_dir = str(BINDMASTER_DIR)
    lines = [
        "#!/usr/bin/env bash",
        f"# Run Evaluator for {cfg['name']}",
        "# Generated by BindMaster Configurator",
        "set -euo pipefail",
        "",
        "# Robust conda init — works in non-interactive shells (no conda on PATH by default)",
        "set +u",
        "_conda_found=false",
        "for _conda_sh in \\",
        f'    "{bindmaster_dir}/conda/etc/profile.d/conda.sh" \\',
        f'    "{conda_base}/etc/profile.d/conda.sh" \\',
        '    "${HOME}/miniforge3/etc/profile.d/conda.sh" \\',
        '    "${HOME}/mambaforge/etc/profile.d/conda.sh" \\',
        '    "${HOME}/miniconda3/etc/profile.d/conda.sh" \\',
        '    "${HOME}/anaconda3/etc/profile.d/conda.sh" \\',
        '    "/opt/conda/etc/profile.d/conda.sh" \\',
        '    "/opt/miniforge3/etc/profile.d/conda.sh"; do',
        '    [[ -f "$_conda_sh" ]] && { source "$_conda_sh"; _conda_found=true; break; }',
        "done",
        '[[ "$_conda_found" == true ]] || { echo "ERROR: conda not found — install Miniconda or Miniforge first." >&2; exit 1; }',
        "set -u",
        "",
        f'EVAL_SCRIPT="{eval_sh}"',
        f'OUTPUT_DIR="{eval_dir}"',
        "",
        'if [[ ! -f "$EVAL_SCRIPT" ]]; then',
        '    echo "ERROR: Evaluator not found at $EVAL_SCRIPT" >&2',
        '    echo "Run: bindmaster install --tool evaluator" >&2',
        "    exit 1",
        "fi",
        "",
        "# Step 1: Extract sequences from design tool outputs into FASTA",
        'SEQUENCES="$OUTPUT_DIR/sequences.fasta"',
    ]

    if design_dirs:
        lines += [
            "",
            "# Collect design sequences from enabled tools",
            'if [[ ! -f "$SEQUENCES" ]]; then',
            '    echo "  Extracting sequences from design outputs..."',
            "    conda run -n binder-eval binder-compare extract \\",
        ]
        for flag, dir_path in design_dirs:
            lines.append(f'        {flag} "{dir_path}" \\')
        lines += [
            '        --output "$SEQUENCES"',
            "fi",
            "",
        ]

    lines += [
        "# Step 2: Run evaluation pipeline",
        f'echo "=== Running Evaluator for {cfg["name"]} ==="',
        'bash "$EVAL_SCRIPT" \\',
        '    --sequences "$SEQUENCES" \\',
        f'    --target-pdb "{target_pdb}" \\',
        f'    --target-seq "{target_seq}" \\',
        '    --output "$OUTPUT_DIR" \\',
        f'    --mosaic-path "{MOSAIC_DIR}" \\',
        "    --resume",
        "",
    ]

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
    if tools_enabled.get("evaluator"):
        (run_dir / "evaluate" / "evaluate_report").mkdir(parents=True, exist_ok=True)

    src_struct = Path(cfg["target_pdb_src"]).expanduser().resolve()
    src_ext = src_struct.suffix.lower()
    if src_ext in (".cif", ".mmcif"):
        # Copy the original CIF
        dest_cif = run_dir / "target" / f"{cfg['name']}{src_ext}"
        shutil.copy2(src_struct, dest_cif)
        # Convert to PDB for tools that need it
        dest_pdb = run_dir / "target" / f"{cfg['name']}.pdb"
        if cif_to_pdb_atoms(str(src_struct), str(dest_pdb)):
            print_ok(f"Converted CIF → PDB: {dest_pdb.name}")
        else:
            print_warn("CIF→PDB conversion failed — some tools may not work with CIF input.")
            dest_pdb = dest_cif  # fallback: point at CIF
        cfg["target_pdb"] = dest_pdb
        cfg["target_cif"] = dest_cif
    else:
        dest_pdb = run_dir / "target" / f"{cfg['name']}.pdb"
        shutil.copy2(src_struct, dest_pdb)
        cfg["target_pdb"] = dest_pdb

    if tools_enabled.get("bindcraft"):
        write_bindcraft_target(run_dir / "bindcraft" / "target_settings.json", cfg)
        copy_bindcraft_preset(FILTERS_DIR, cfg["filter_preset"], run_dir / "bindcraft" / "filters.json")
        copy_bindcraft_preset(ADVANCED_DIR, cfg["advanced_preset"], run_dir / "bindcraft" / "advanced.json")
        write_run_bindcraft(run_dir / "run_bindcraft.sh", cfg)

    if tools_enabled.get("boltzgen"):
        if cfg.get("boltzgen_mode") == "nanobody":
            copy_nanobody_scaffolds(run_dir / "boltzgen" / "nanobody_scaffolds")
        write_boltzgen_yaml(run_dir / "boltzgen" / "config.yaml", cfg)
        write_run_boltzgen(run_dir / "run_boltzgen.sh", cfg)

    if tools_enabled.get("mosaic"):
        write_mosaic_hallucinate(run_dir / "mosaic" / "hallucinate.py", cfg)
        write_run_mosaic(run_dir / "run_mosaic.sh", cfg)

    if tools_enabled.get("pxdesign_local"):
        (run_dir / "pxdesign" / "outputs").mkdir(parents=True, exist_ok=True)
        # In length-scan mode the per-length YAMLs are written by the bash script
        # itself; only emit a static input.yaml when scanning is disabled.
        if not cfg.get("pxdesign_length_scan"):
            write_pxdesign_yaml(run_dir / "pxdesign" / "input.yaml", cfg)
        write_run_pxdesign(run_dir / "run_pxdesign.sh", cfg)

    if tools_enabled.get("proteina_complexa"):
        (run_dir / "proteina_complexa").mkdir(parents=True, exist_ok=True)
        write_run_proteina_complexa(run_dir / "run_proteina_complexa.sh", cfg)

    if tools_enabled.get("rfd3"):
        (run_dir / "rfd3" / "outputs").mkdir(parents=True, exist_ok=True)
        write_run_rfd3(run_dir / "run_rfd3.sh", cfg)

    if tools_enabled.get("protein_hunter"):
        (run_dir / "protein_hunter" / "outputs").mkdir(parents=True, exist_ok=True)
        write_run_protein_hunter(run_dir / "run_protein_hunter.sh", cfg)

    if tools_enabled.get("evaluator"):
        write_run_evaluate(run_dir / "run_evaluate.sh", cfg, tools_enabled)

    write_run_all(run_dir / "run_all.sh", cfg, tools_enabled)


# ─── Pipeline runner ──────────────────────────────────────────────────────────


def run_pipeline(cfg: dict, tools_enabled: dict):
    """Run the enabled tools in sequence with live terminal output."""
    run_dir = cfg["run_dir"]
    failed = []

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

    if tools_enabled.get("pxdesign_local"):
        print_step("Running PXDesign")
        rc = subprocess.run(["bash", str(run_dir / "run_pxdesign.sh")]).returncode
        if rc == 0:
            print_ok("PXDesign completed")
        else:
            print_fail(f"PXDesign failed (exit code {rc})")
            failed.append("PXDesign")

    if tools_enabled.get("proteina_complexa"):
        print_step("Running Proteina-Complexa")
        rc = subprocess.run(["bash", str(run_dir / "run_proteina_complexa.sh")]).returncode
        if rc == 0:
            print_ok("Proteina-Complexa completed")
        else:
            print_fail(f"Proteina-Complexa failed (exit code {rc})")
            failed.append("Proteina-Complexa")

    if tools_enabled.get("evaluator"):
        print_step("Running Evaluator  (Boltz-2 refolding + ranked report — this may take a while)")
        rc = subprocess.run(["bash", str(run_dir / "run_evaluate.sh")]).returncode
        if rc == 0:
            print_ok("Evaluator completed")
        else:
            print_fail(f"Evaluator failed (exit code {rc})")
            failed.append("Evaluator")

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
    shortcut.write_text(f"#!/usr/bin/env bash\n# BindMaster Configurator shortcut — auto-generated\n{target_line}")
    shortcut.chmod(0o755)
    print_ok(f"Shortcut installed: {shortcut}")


# ─── Sequence → Structure prediction ─────────────────────────────────────────

PREDICT_SCRIPT = Path(__file__).resolve().parent / "predict_structure.py"


def _handle_sequence_input(run_dir: Path) -> str:
    """
    Handle the 'amino acid sequence' target input path.

    Offers local Boltz-2 prediction (if Mosaic is installed) or directs the
    user to the AlphaFold Server. Returns the path to the predicted PDB.
    """
    mosaic_python = MOSAIC_VENV / "bin" / "python"
    has_boltz2 = mosaic_python.exists()

    print()
    if has_boltz2:
        _, method = ask_choice(
            "How would you like to predict the structure?",
            [
                "Predict locally with Boltz-2 (GPU recommended, ~2-5 min)",
                "Use AlphaFold 3 Server (external, paste result path after)",
            ],
            default_index=0,
        )
    else:
        method = "alphafold"
        print_warn("Mosaic not installed — local Boltz-2 prediction unavailable.")
        print(f"  Install with: {CYAN}bindmaster install --tool mosaic{RESET}")
        print()

    if "boltz" in method.lower():
        return _predict_boltz2(run_dir, mosaic_python)

    # AF3 server path
    print()
    print(f"  {BOLD}AlphaFold 3 Server:{RESET}")
    print(f"    1. Go to {CYAN}https://alphafoldserver.com{RESET}")
    print("    2. Paste your sequence and submit a prediction job")
    print("    3. Download the best-ranked .cif/.pdb file")
    print("    4. Provide the path below")
    print()
    return ask("  Path to predicted structure file (.pdb / .cif)", validator=validate_structure_path)


def _predict_boltz2(run_dir: Path, mosaic_python: Path) -> str:
    """Run Boltz-2 structure prediction from a user-provided sequence."""
    sequence = ask("  Target amino acid sequence", validator=validate_sequence)
    sequence = sequence.upper().strip()

    target_dir = run_dir / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    output_pdb = target_dir / "predicted_boltz2.pdb"

    print()
    print_step(f"Predicting structure with Boltz-2 ({len(sequence)} residues)...")
    print(f"  Sequence: {sequence[:60]}{'...' if len(sequence) > 60 else ''}")
    print(f"  Output:   {output_pdb}")
    print()

    proc = subprocess.run(
        [str(mosaic_python), str(PREDICT_SCRIPT), sequence, str(output_pdb)],
        capture_output=False,
    )

    if proc.returncode != 0:
        print()
        print_fail("Boltz-2 prediction failed.")
        print(f"  You can try the AlphaFold 3 Server instead: {CYAN}https://alphafoldserver.com{RESET}")
        print()
        fallback = ask_yn("  Provide a structure file manually?", default=True)
        if fallback:
            return ask("  Path to target structure file (.pdb / .cif)", validator=validate_structure_path)
        sys.exit(1)

    if not output_pdb.exists():
        print_fail(f"Expected output not found: {output_pdb}")
        sys.exit(1)

    print()
    print_ok(f"Structure predicted → {output_pdb}")
    return str(output_pdb)


# ─── Wizard ───────────────────────────────────────────────────────────────────


def wizard():
    install_shortcut()
    banner()

    # ── Step 1: Project name ──────────────────────────────────────────────────
    print_step("Step 1 — Project name")
    print("  Used as binder name. Run folder path can be customised below.")
    name = ask("  Target name", validator=validate_name)
    run_dir = Path(
        ask(
            "  Run folder",
            default=str(RUNS_DIR / name),
        )
    ).expanduser()

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
        ["PDB or mmCIF file path", "Amino acid sequence (predict structure with Boltz-2 or AF3)"],
        default_index=0,
    )

    if "sequence" in input_type.lower():
        target_pdb_src = _handle_sequence_input(run_dir)
    else:
        target_pdb_src = ask("  Path to target structure file (.pdb / .cif)", validator=validate_structure_path)

    # ── Step 3: Target details ────────────────────────────────────────────────
    print_step("Step 3 — Target details")
    chains = ask("  Chain(s) to target (e.g. A or A,B)", default="A", validator=validate_chains)
    hotspots = ask(
        "  Hotspot residues (e.g. 56 or 1-10,20, blank=auto)",
        default="",
        validator=validate_hotspots,
    )

    primary_chain = chains.split(",")[0].strip()
    target_sequence = extract_sequence_from_structure(target_pdb_src, primary_chain)
    if target_sequence:
        preview = target_sequence[:50] + ("..." if len(target_sequence) > 50 else "")
        print_ok(f"Auto-extracted sequence for chain {primary_chain}: {preview} ({len(target_sequence)} aa)")

    # ── Step 4: Binder settings ───────────────────────────────────────────────
    print_step("Step 4 — Binder settings (global defaults)")
    print("  These apply to all tools — you can override per-tool in Step 6.")
    min_length = int(ask("  Minimum binder length", default=65, validator=validate_int(min_val=10, max_val=500)))
    max_length = int(ask("  Maximum binder length", default=150, validator=validate_int(min_val=10, max_val=500)))
    if max_length < min_length:
        print_warn("max length < min length — swapping values.")
        min_length, max_length = max_length, min_length
    n_designs = int(ask("  Number of top/final designs", default=10, validator=validate_int(min_val=1)))

    # ── Step 5: Tool selection ────────────────────────────────────────────────
    print_step("Step 5 — Tool selection")
    installed = detect_installs()

    def _tag(key):
        if installed.get(key):
            return f"{GREEN}installed{RESET}"
        return f"{RED}NOT installed — run: bindmaster install{RESET}"

    print(f"  {BOLD}Mosaic{RESET}    [{_tag('mosaic')}]")
    use_mosaic = ask_yn("  Enable Mosaic?", default=False)
    print(f"  {BOLD}BoltzGen{RESET}  [{_tag('boltzgen')}]")
    use_boltzgen = ask_yn("  Enable BoltzGen?", default=False)
    print(f"  {BOLD}BindCraft{RESET} [{_tag('bindcraft')}]")
    use_bindcraft = ask_yn("  Enable BindCraft?", default=True)
    print(f"  {BOLD}PXDesign{RESET}  [{_tag('pxdesign_local')}] / [external import]")
    pxdesign_mode, _ = ask_choice(
        "  PXDesign mode",
        ["Skip", "Run locally (requires install)", "Import external results"],
        default_index=0,
    )
    use_pxdesign = pxdesign_mode > 0
    use_pxdesign_local = pxdesign_mode == 1
    use_pxdesign_import = pxdesign_mode == 2
    print(f"  {BOLD}Proteina-Complexa{RESET} [{_tag('proteina_complexa')}]")
    use_proteina_complexa = ask_yn("  Enable Proteina-Complexa (NVIDIA flow matching)?", default=False)
    print(f"  {BOLD}Evaluator{RESET} [{_tag('evaluator')}]")
    use_evaluator = ask_yn("  Enable cross-evaluation (Boltz-2 refolding + ranked report)?", default=False)

    tools_enabled = {
        "mosaic": use_mosaic,
        "boltzgen": use_boltzgen,
        "bindcraft": use_bindcraft,
        "pxdesign": use_pxdesign,
        "pxdesign_local": use_pxdesign_local,
        "pxdesign_import": use_pxdesign_import,
        "proteina_complexa": use_proteina_complexa,
        "evaluator": use_evaluator,
    }

    # Evaluator is post-processing — don't count it as the sole tool
    design_tools = {k: v for k, v in tools_enabled.items() if k != "evaluator"}
    if not any(design_tools.values()) and not use_evaluator:
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
            default_fi = filter_presets.index("default_filters") if "default_filters" in filter_presets else 0
            _, cfg["filter_preset"] = ask_choice("Filter preset:", filter_presets, default_index=default_fi)
        else:
            print_warn(f"No filter presets found in {FILTERS_DIR}")

        advanced_presets = list_presets(ADVANCED_DIR)
        if advanced_presets:
            default_ai = (
                advanced_presets.index("default_4stage_multimer")
                if "default_4stage_multimer" in advanced_presets
                else 0
            )
            _, cfg["advanced_preset"] = ask_choice("Advanced preset:", advanced_presets, default_index=default_ai)
        else:
            print_warn(f"No advanced presets found in {ADVANCED_DIR}")

        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["bindcraft_min_length"] = int(
            ask("  Min binder length", default=min_length, validator=validate_int(min_val=1, max_val=500))
        )
        cfg["bindcraft_max_length"] = int(
            ask("  Max binder length", default=max_length, validator=validate_int(min_val=1, max_val=500))
        )
        cfg["bindcraft_n_designs"] = int(
            ask("  Number of final designs", default=n_designs, validator=validate_int(min_val=1))
        )

    if use_boltzgen:
        print_step("Step 6b — BoltzGen settings")
        _, mode_choice = ask_choice(
            "Binder type:",
            ["protein-anything — de-novo protein binder", "nanobody — redesign CDR loops of four scaffold nanobodies"],
            default_index=0,
        )
        cfg["boltzgen_mode"] = "nanobody" if "nanobody" in mode_choice else "protein"
        if cfg["boltzgen_mode"] == "nanobody":
            print(f"  Scaffolds: {CYAN}{', '.join(NANOBODY_SCAFFOLD_NAMES)}{RESET}")
            print("  (will be copied to boltzgen/nanobody_scaffolds/)")
        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["boltzgen_budget"] = int(
            ask("  Final designs (--budget)", default=n_designs, validator=validate_int(min_val=1))
        )
        cfg["boltzgen_min_length"] = int(
            ask("  Min binder length", default=min_length, validator=validate_int(min_val=1, max_val=500))
        )
        cfg["boltzgen_max_length"] = int(
            ask("  Max binder length", default=max_length, validator=validate_int(min_val=1, max_val=500))
        )
        cfg["boltzgen_intermediate"] = int(
            ask(
                "  Intermediate designs (--num_designs, recommended: 10 000)",
                default=10000,
                validator=validate_int(min_val=1),
            )
        )

    if use_mosaic:
        print_step("Step 6c — Mosaic settings")
        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["mosaic_n_designs"] = int(
            ask("  Designs to generate (Stage 1)", default=100, validator=validate_int(min_val=1))
        )
        cfg["mosaic_top_k"] = int(
            ask("  Top designs to refold (TOP_K)", default=n_designs, validator=validate_int(min_val=0))
        )
        cfg["mosaic_min_length"] = int(
            ask("  Min binder length", default=min_length, validator=validate_int(min_val=1, max_val=500))
        )
        cfg["mosaic_max_length"] = int(
            ask("  Max binder length", default=max_length, validator=validate_int(min_val=1, max_val=500))
        )
        cfg["mosaic_length_step"] = int(
            ask(
                "  Length scan step (1 = every aa, set min=max to skip scan)",
                default=5,
                validator=validate_int(min_val=1),
            )
        )
        if not target_sequence:
            print_warn("Could not auto-extract target sequence from PDB.")
            cfg["target_sequence"] = ask(
                f"  Target amino-acid sequence (chain {primary_chain})", validator=validate_sequence
            )
        else:
            seq_preview = target_sequence[:60] + ("..." if len(target_sequence) > 60 else "")
            print(f"  Sequence ({len(target_sequence)} aa): {CYAN}{seq_preview}{RESET}")
            if not ask_yn("  Use this sequence?", default=True):
                cfg["target_sequence"] = ask("  Enter target sequence", validator=validate_sequence)

    if use_pxdesign_local:
        print_step("Step 6d — PXDesign settings (local run)")
        pxd_length_mode, _ = ask_choice(
            "  Length mode",
            [
                "Length scan (range with step, like Mosaic)",
                "Fixed length (single binder length)",
            ],
            default_index=0,
        )
        cfg["pxdesign_length_scan"] = pxd_length_mode == 0
        if cfg["pxdesign_length_scan"]:
            cfg["pxdesign_min_length"] = int(
                ask("  Min binder length", default=min_length, validator=validate_int(min_val=30, max_val=300))
            )
            cfg["pxdesign_max_length"] = int(
                ask("  Max binder length", default=max_length, validator=validate_int(min_val=30, max_val=300))
            )
            cfg["pxdesign_length_step"] = int(
                ask("  Length step", default=20, validator=validate_int(min_val=5, max_val=100))
            )
            cfg["pxdesign_n_samples"] = int(
                ask("  Samples per length", default=10, validator=validate_int(min_val=1, max_val=1000))
            )
            # Compute total for user info
            n_lengths = len(
                range(cfg["pxdesign_min_length"], cfg["pxdesign_max_length"] + 1, cfg["pxdesign_length_step"])
            )
            total = n_lengths * cfg["pxdesign_n_samples"]
            print_ok(f"  {n_lengths} lengths x {cfg['pxdesign_n_samples']} samples = {total} total designs")
            # Set binder_length to min for the base YAML (overridden per-length in run script)
            cfg["pxdesign_binder_length"] = cfg["pxdesign_min_length"]
        else:
            cfg["pxdesign_binder_length"] = int(
                ask("  Binder length (amino acids)", default=80, validator=validate_int(min_val=30, max_val=300))
            )
            cfg["pxdesign_n_samples"] = int(
                ask("  Number of design samples", default=1000, validator=validate_int(min_val=1, max_val=10000))
            )
        preset_idx, _ = ask_choice(
            "  PXDesign preset",
            ["preview (fast, ~5 min/length)", "extended (production, ~2 hrs/length)"],
            default_index=0,
        )
        cfg["pxdesign_preset"] = ["preview", "extended"][preset_idx]
        if cfg["pxdesign_preset"] == "extended":
            print_warn("  Extended preset requires MSA computation (~10-20 min extra).")
        if cfg.get("hotspots"):
            print_ok(f"  Using hotspots from Step 3: {cfg['hotspots']}")
            cfg["pxdesign_hotspots"] = cfg["hotspots"]
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
        print_step("Step 6d — PXDesign settings (import)")
        print("  PXDesign results are imported from a local directory containing")
        print("  summary.csv (downloaded from protenix-server.com).")
        cfg["pxdesign_output_dir"] = ask(
            "  PXDesign output directory",
            default="",
            validator=lambda x: True if x.strip() else "path required",
        )

    if use_proteina_complexa:
        print_step("Step 6f — Proteina-Complexa settings")
        _, pc_algo = ask_choice(
            "  Search algorithm",
            [
                "single-pass — fastest, one forward pass per sample",
                "best-of-n — generate N candidates, keep best (recommended)",
                "beam-search — iterative refinement with beam width",
                "mcts — Monte Carlo Tree Search (most expensive, best quality)",
            ],
            default_index=1,
        )
        cfg["complexa_search_algorithm"] = pc_algo.split(" — ")[0].strip()
        cfg["complexa_replicas"] = int(
            ask(
                "  Number of replicas (best-of-n) or beam width",
                default=2,
                validator=validate_int(min_val=1, max_val=64),
            )
        )
        cfg["complexa_n_designs"] = int(
            ask("  Max designs to keep after filtering", default=100, validator=validate_int(min_val=1, max_val=10000))
        )
        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["complexa_min_length"] = int(
            ask("  Min binder length", default=min_length, validator=validate_int(min_val=10, max_val=500))
        )
        cfg["complexa_max_length"] = int(
            ask("  Max binder length", default=max_length, validator=validate_int(min_val=10, max_val=500))
        )
        if cfg.get("hotspots"):
            print_ok(f"  Using hotspots from Step 3: {cfg['hotspots']}")
            cfg["complexa_hotspots"] = cfg["hotspots"]
        else:
            cfg["complexa_hotspots"] = ask(
                "  Hotspot residues (blank=auto)",
                default="",
                validator=validate_hotspots,
            )
        cfg["complexa_chains"] = ask(
            "  Target chains to include (e.g. 'A' or 'A,B')",
            default=cfg.get("chains", "A"),
            validator=validate_chains,
        )

    # ── Step 7: Preview ───────────────────────────────────────────────────────
    print_step("Step 7 — Preview")
    print(f"  {CYAN}Run folder{RESET}:    {run_dir}")
    print(f"  {CYAN}Target file{RESET}:   {target_pdb_src}")
    print(f"  {CYAN}Chains{RESET}:        {chains}  |  {CYAN}Hotspots{RESET}: {hotspots or '(auto)'}")
    print(f"  {CYAN}Binder length{RESET}: {min_length}–{max_length}  |  {CYAN}Top designs{RESET}: {n_designs}")
    enabled_list = [t for t, v in tools_enabled.items() if v]
    print(f"  {CYAN}Tools{RESET}:         {', '.join(enabled_list)}")
    if use_bindcraft:
        bc_min = cfg.get("bindcraft_min_length", min_length)
        bc_max = cfg.get("bindcraft_max_length", max_length)
        bc_n = cfg.get("bindcraft_n_designs", n_designs)
        print(f"  {CYAN}BindCraft{RESET}:     filters={cfg['filter_preset']}  advanced={cfg['advanced_preset']}")
        print(f"             length={bc_min}–{bc_max}  final_designs={bc_n}")
    if use_boltzgen:
        bg_min = cfg.get("boltzgen_min_length", min_length)
        bg_max = cfg.get("boltzgen_max_length", max_length)
        bg_n = cfg.get("boltzgen_budget", n_designs)
        mode_label = "nanobody CDR redesign" if cfg["boltzgen_mode"] == "nanobody" else "de-novo protein"
        print(
            f"  {CYAN}BoltzGen{RESET}:      {mode_label}  |  "
            f"length={bg_min}–{bg_max}  budget={bg_n}  "
            f"intermediate={cfg['boltzgen_intermediate']:,}"
        )
    if use_mosaic:
        mo_min = cfg.get("mosaic_min_length", min_length)
        mo_max = cfg.get("mosaic_max_length", max_length)
        mo_n = cfg.get("mosaic_n_designs", 100)
        mo_k = cfg.get("mosaic_top_k", n_designs)
        seq = cfg["target_sequence"]
        print(f"  {CYAN}Mosaic{RESET}:        length={mo_min}–{mo_max}  generate={mo_n}  refold(TOP_K)={mo_k}")
        print(f"  {CYAN}Mosaic seq{RESET}:    {seq[:50]}{'...' if len(seq) > 50 else ''} ({len(seq)} aa)")
    if use_pxdesign_local:
        print(
            f"  {CYAN}PXDesign{RESET}:      preset={cfg.get('pxdesign_preset')}  "
            f"samples={cfg.get('pxdesign_n_samples')}  "
            f"binder_len={cfg.get('pxdesign_binder_length')}"
        )
    elif use_pxdesign_import:
        print(f"  {CYAN}PXDesign{RESET}:      import from {cfg.get('pxdesign_output_dir')}")
    if use_proteina_complexa:
        pc_min = cfg.get("complexa_min_length", min_length)
        pc_max = cfg.get("complexa_max_length", max_length)
        print(
            f"  {CYAN}Proteina-Complexa{RESET}: algo={cfg.get('complexa_search_algorithm')}  "
            f"replicas={cfg.get('complexa_replicas')}  "
            f"length={pc_min}–{pc_max}  "
            f"max_designs={cfg.get('complexa_n_designs')}"
        )
    if use_evaluator:
        print(f"  {CYAN}Evaluator{RESET}:     Boltz-2 refolding → ranked report")

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
    if use_evaluator:
        print_warn("Evaluator runs Boltz-2 refolding (GPU recommended, ~30 min per design).")

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
        if use_pxdesign_local:
            print(f"  {step}. bash {run_dir}/run_pxdesign.sh")
            step += 1
        if use_proteina_complexa:
            print(f"  {step}. bash {run_dir}/run_proteina_complexa.sh")
            step += 1
        if use_evaluator:
            print(f"  {step}. bash {run_dir}/run_evaluate.sh")
            step += 1
        if len(enabled_list) > 1:
            print(f"  Or run the full pipeline:  bash {run_dir}/run_all.sh")
        print()


# ─── CLI commands ─────────────────────────────────────────────────────────────


def cmd_archive(run_name: str):
    """Archive a run folder to a .tar.gz file."""
    run_dir = RUNS_DIR / run_name
    if not run_dir.is_dir():
        print_fail(f"Run folder not found: {run_dir}")
        sys.exit(1)

    archive_path = RUNS_DIR / f"{run_name}.tar.gz"
    file_count = sum(1 for _ in run_dir.rglob("*") if _.is_file())
    print(f"  Archiving {BOLD}{run_name}/{RESET}  ({file_count} files)")

    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(str(run_dir), arcname=run_name)

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print_ok(f"Created {archive_path.name}  ({size_mb:.1f} MB, {file_count} files)")

    if ask_yn(f"  Delete original folder {run_dir}?", default=False):
        shutil.rmtree(run_dir)
        print_ok(f"Deleted {run_dir}")


def cmd_status():
    """Show all runs and their completion state."""
    if not RUNS_DIR.is_dir():
        print(f"  No runs directory found at {RUNS_DIR}")
        return

    runs = sorted(d for d in RUNS_DIR.iterdir() if d.is_dir())
    if not runs:
        print(f"  No run folders in {RUNS_DIR}")
        return

    # Table header
    print()
    print(f"  {BOLD}{'Run Name':<25s}  {'Tools':<30s}  {'Status':<20s}{RESET}")
    print(f"  {'─' * 78}")

    for run_dir in runs:
        # Detect configured tools
        tools = []
        if (run_dir / "run_mosaic.sh").exists():
            tools.append("Mosaic")
        if (run_dir / "run_boltzgen.sh").exists():
            tools.append("BoltzGen")
        if (run_dir / "run_bindcraft.sh").exists():
            tools.append("BindCraft")
        if (run_dir / "run_pxdesign.sh").exists():
            tools.append("PXDesign")
        if (run_dir / "run_proteina_complexa.sh").exists():
            tools.append("Proteina-Complexa")
        if (run_dir / "run_rfd3.sh").exists():
            tools.append("RFD3")
        if (run_dir / "run_protein_hunter.sh").exists():
            tools.append("Protein-Hunter")
        if (run_dir / "run_evaluate.sh").exists():
            tools.append("Evaluator")
        if not tools:
            tools.append("(unknown)")

        # Detect status
        statuses = []
        if (run_dir / "mosaic" / "designs.csv").exists():
            statuses.append("Mosaic: done")
        elif "Mosaic" in tools:
            statuses.append("Mosaic: pending")

        bg_outputs = (
            list((run_dir / "boltzgen" / "outputs").glob("*.pdb"))
            if (run_dir / "boltzgen" / "outputs").is_dir()
            else []
        )
        if bg_outputs:
            statuses.append(f"BoltzGen: {len(bg_outputs)} PDBs")
        elif "BoltzGen" in tools:
            statuses.append("BoltzGen: pending")

        bc_outputs = (
            list((run_dir / "bindcraft" / "outputs").glob("*.pdb"))
            if (run_dir / "bindcraft" / "outputs").is_dir()
            else []
        )
        if bc_outputs:
            statuses.append(f"BindCraft: {len(bc_outputs)} PDBs")
        elif "BindCraft" in tools:
            statuses.append("BindCraft: pending")

        report_html = run_dir / "evaluate" / "evaluate_report" / "report.html"
        if report_html.exists():
            statuses.append("Eval: done")
        elif "Evaluator" in tools:
            statuses.append("Eval: pending")

        tools_str = ",".join(tools)
        if not statuses:
            status_str = "configured"
        elif all("done" in s or "PDBs" in s for s in statuses):
            status_str = f"{GREEN}complete{RESET}"
        else:
            status_str = "; ".join(statuses)

        # Truncate for display
        if len(status_str) > 40:
            status_str = status_str[:37] + "..."

        print(f"  {run_dir.name:<25s}  {tools_str:<30s}  {status_str}")

    print()


# ─── Entry point ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="BindMaster Configurator — setup wizard for protein binder design runs",
    )
    parser.add_argument(
        "--archive",
        metavar="RUN",
        help="Archive a run folder to tar.gz",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show all runs and their completion state",
    )
    args = parser.parse_args()

    if args.archive:
        cmd_archive(args.archive)
    elif args.status:
        cmd_status()
    else:
        wizard()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}Interrupted.{RESET} Some files may have been partially written.")
        sys.exit(1)
