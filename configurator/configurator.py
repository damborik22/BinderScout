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
RFAA_DIR = BINDMASTER_DIR / "rf_diffusion_all_atom"
LIGANDMPNN_DIR = BINDMASTER_DIR / "LigandMPNN"
PXDESIGN_DIR = BINDMASTER_DIR / "PXDesign"
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
        "evaluator": (
            (EVALUATOR_DIR / "evaluate.sh").exists()
            and (_env_exists("binder-eval-boltz2") or _env_exists("binder-eval-af2"))
        ),
        "rfaa": _env_exists("bindmaster_rfaa"),
        "pxdesign_local": _env_exists("bindmaster_pxdesign"),
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
    if tools_enabled.get("rfaa"):
        print(f"  ├── {CYAN}rfaa/{RESET}")
        print("  │   ├── outputs/          ← backbone PDBs")
        print("  │   ├── ligandmpnn/       ← LigandMPNN sequences")
        print("  │   └── sequences.csv")
    if tools_enabled.get("pxdesign_local"):
        print(f"  ├── {CYAN}pxdesign/{RESET}")
        print("  │   ├── input.yaml")
        print("  │   └── outputs/")
    if tools_enabled.get("evaluator"):
        print(f"  ├── {CYAN}evaluate/{RESET}")
        print("  │   └── comparison_report/")
    scripts = []
    if tools_enabled.get("mosaic"):
        scripts.append("run_mosaic.sh")
    if tools_enabled.get("boltzgen"):
        scripts.append("run_boltzgen.sh")
    if tools_enabled.get("bindcraft"):
        scripts.append("run_bindcraft.sh")
    if tools_enabled.get("rfaa"):
        scripts.append("run_rfaa.sh")
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

    old_block = (
        'TARGET_SEQUENCE = "REPLACE_ME"  # target protein sequence\n'
        "N_DESIGNS = 100  # Stage 1: how many designs to generate per length\n"
        "TOP_K = 5  # Stage 2: how many top designs to refold and export PDB\n"
        "MIN_LENGTH = 65  # minimum binder length (aa)\n"
        "MAX_LENGTH = 100  # maximum binder length (aa)\n"
        "LENGTH_STEP = 5  # step between scanned lengths; set MIN=MAX for a single length"
    )
    new_block = (
        f"TARGET_SEQUENCE = {cfg['target_sequence']!r}  # target protein sequence\n"
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


def write_run_rfaa(path: Path, cfg: dict):
    """Generate run_rfaa.sh — two-stage: RFAA backbones then LigandMPNN sequences."""
    run_dir = cfg["run_dir"]
    conda_base = str(CONDA_BASE) if CONDA_BASE else ""
    bindmaster_dir = str(BINDMASTER_DIR)
    ligand = cfg.get("rfaa_ligand")
    contigs = cfg.get("rfaa_contigs", f"{cfg['min_length']}-{cfg['max_length']}")
    n_designs = cfg.get("rfaa_n_designs", cfg["n_designs"])
    diffusion_t = cfg.get("rfaa_diffusion_steps", 100)
    lmpnn_temperature = cfg.get("lmpnn_temperature", 0.1)
    lmpnn_seqs = cfg.get("lmpnn_seqs_per_backbone", 5)
    ligand_line = f'\n    inference.ligand="{ligand}" \\' if ligand else ""

    content = f"""\
#!/usr/bin/env bash
# Run RFDiffusionAA + LigandMPNN for {cfg["name"]}
# Generated by BindMaster Configurator
set -euo pipefail

RFAA_DIR="{RFAA_DIR}"
LIGANDMPNN_DIR="{LIGANDMPNN_DIR}"
OUTPUT_DIR="{run_dir}/rfaa/outputs"
LMPNN_DIR="{run_dir}/rfaa/ligandmpnn"
TARGET_PDB="{cfg["target_pdb"]}"

mkdir -p "$OUTPUT_DIR" "$LMPNN_DIR"

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
conda activate bindmaster_rfaa
set -u

# Add RFAA + LigandMPNN to PYTHONPATH (not pip-installed)
export PYTHONPATH="${{RFAA_DIR}}:${{LIGANDMPNN_DIR}}${{PYTHONPATH:+:$PYTHONPATH}}"

# ============================================================
# Stage 1: RFDiffusionAA — generate backbone PDBs
# ============================================================
echo "=== Stage 1: RFDiffusionAA ==="
cd "$RFAA_DIR"

python run_inference.py \\
    inference.input_pdb="$TARGET_PDB" \\
    inference.output_prefix="$OUTPUT_DIR/sample" \\
    inference.ckpt_path="$RFAA_DIR/weights/RFDiffusionAA_paper_weights.pt" \\
    inference.num_designs={n_designs} \\
    diffuser.T={diffusion_t} \\{ligand_line}
    contigmap.contigs="['{contigs}']"

BACKBONE_COUNT=$(find "$OUTPUT_DIR" -name "*.pdb" | wc -l)
echo "  -> $BACKBONE_COUNT backbone PDBs generated"

if [[ "$BACKBONE_COUNT" -eq 0 ]]; then
    echo "ERROR: RFAA produced no backbone PDBs" >&2
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
    python run.py \\
        --seed "$SEED" \\
        --pdb_path "$PDB_FILE" \\
        --out_folder "$LMPNN_OUT" \\
        --model_type "ligand_mpnn" \\
        --ligand_mpnn_use_side_chain_context 1 \\
        --temperature {lmpnn_temperature} \\
        --number_of_batches {lmpnn_seqs}

    SEED=$((SEED + 1))
done

# ============================================================
# Stage 3: Collect sequences into summary CSV
# ============================================================
echo ""
echo "=== Collecting sequences ==="
python3 -c "
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
                conf_m = re.search(r'overall_confidence=([0-9.]+)', header)
                lig_m = re.search(r'ligand_confidence=([0-9.]+)', header)
                name = header.split()[0].lstrip('>')
                rows.append({{
                    'design_id': name,
                    'sequence': seq,
                    'length': len(seq),
                    'overall_confidence': conf_m.group(1) if conf_m else '',
                    'ligand_confidence': lig_m.group(1) if lig_m else '',
                    'backbone_pdb': fasta.parent.parent.name,
                    'source': 'rfaa',
                }})

if not rows:
    print('WARNING: No sequences found in LigandMPNN output', file=sys.stderr)
    sys.exit(0)

out_csv = Path('$LMPNN_DIR').parent / 'sequences.csv'
with open(out_csv, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f'  -> {{len(rows)}} sequences written to {{out_csv}}')
"

echo ""
echo "=== RFAA + LigandMPNN complete ==="
echo "Backbone PDBs:  $OUTPUT_DIR/"
echo "Sequences:      $(dirname "$LMPNN_DIR")/sequences.csv"
"""
    path.write_text(content)
    path.chmod(0o755)


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
set -u

# aarch64/Blackwell: CUDA arch list and JAX CPU-only mode
if [[ "$(uname -m)" == "aarch64" ]]; then
    export TORCH_CUDA_ARCH_LIST="12.0"
    export JAX_PLATFORMS=cpu
fi

cd "$PXDESIGN_DIR"
"""


def write_run_pxdesign(path: Path, cfg: dict):
    """Generate run_pxdesign.sh for local PXDesign execution."""
    run_dir = cfg["run_dir"]
    preset = cfg.get("pxdesign_preset", "preview")
    n_samples = cfg.get("pxdesign_n_samples", 1000)
    length_scan = cfg.get("pxdesign_length_scan", False)

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

        content = header + f"""
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

    if [[ -f "$OUTPUT_DIR/design_outputs/input/summary.csv" ]]; then
        N_DONE=$(tail -n +2 "$OUTPUT_DIR/design_outputs/input/summary.csv" | wc -l)
        TOTAL_DESIGNS=$((TOTAL_DESIGNS + N_DONE))
        echo "  -> ${{N_DONE}} designs at length ${{LENGTH}}"
    fi
done

echo ""
echo "=== Length Scan Complete ==="
echo "  Total designs: ${{TOTAL_DESIGNS}}"

# Merge all summary CSVs into one
MERGED="$RUN_DIR/pxdesign/summary_all.csv"
FIRST=true
for LENGTH in $(seq "$MIN_LENGTH" "$LENGTH_STEP" "$MAX_LENGTH"); do
    CSV="$RUN_DIR/pxdesign/outputs_len${{LENGTH}}/design_outputs/input/summary.csv"
    if [[ -f "$CSV" ]]; then
        if [[ "$FIRST" == true ]]; then
            cat "$CSV" > "$MERGED"
            FIRST=false
        else
            tail -n +2 "$CSV" >> "$MERGED"
        fi
    fi
done

if [[ -f "$MERGED" ]]; then
    # Also place at top level for evaluator extractor
    cp "$MERGED" "$RUN_DIR/pxdesign/summary.csv"
    N_MERGED=$(tail -n +2 "$MERGED" | wc -l)
    echo "  Merged summary: ${{MERGED}} (${{N_MERGED}} designs)"
fi
"""
    else:
        content = header + f"""
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
    path.write_text(content)
    path.chmod(0o755)


def write_run_all(path: Path, cfg: dict, tools_enabled: dict):
    run_dir = cfg["run_dir"]
    lines = [
        "#!/usr/bin/env bash",
        f"# Run all enabled tools for {cfg['name']} in order: Mosaic → BoltzGen → BindCraft → RFAA → PXDesign → Evaluator",
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

    if tools_enabled.get("evaluator"):
        lines += [
            'echo "=== Step: Evaluator ==="',
            '"$RUN_DIR/run_evaluate.sh"',
            "",
        ]

    lines += ['echo ""', 'echo "=== Pipeline complete! ==="']

    path.write_text("\n".join(lines) + "\n")
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
    if tools_enabled.get("rfaa"):
        design_dirs.append(("--rfaa", str(run_dir / "rfaa")))
    if tools_enabled.get("pxdesign_local"):
        # Length-scan merges CSVs to pxdesign/summary.csv; fixed-length has outputs/...summary.csv
        # Point extractor at pxdesign/ — it rglobs for summary.csv in either layout
        design_dirs.append(("--pxdesign", str(run_dir / "pxdesign")))
    elif tools_enabled.get("pxdesign") and cfg.get("pxdesign_output_dir"):
        design_dirs.append(("--pxdesign", cfg["pxdesign_output_dir"]))

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
        (run_dir / "evaluate" / "comparison_report").mkdir(parents=True, exist_ok=True)

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

    if tools_enabled.get("rfaa"):
        (run_dir / "rfaa" / "outputs").mkdir(parents=True, exist_ok=True)
        (run_dir / "rfaa" / "ligandmpnn").mkdir(parents=True, exist_ok=True)
        write_run_rfaa(run_dir / "run_rfaa.sh", cfg)

    if tools_enabled.get("pxdesign_local"):
        (run_dir / "pxdesign" / "outputs").mkdir(parents=True, exist_ok=True)
        write_pxdesign_yaml(run_dir / "pxdesign" / "input.yaml", cfg)
        write_run_pxdesign(run_dir / "run_pxdesign.sh", cfg)

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

    if tools_enabled.get("rfaa"):
        print_step("Running RFAA + LigandMPNN")
        rc = subprocess.run(["bash", str(run_dir / "run_rfaa.sh")]).returncode
        if rc == 0:
            print_ok("RFAA + LigandMPNN completed")
        else:
            print_fail(f"RFAA failed (exit code {rc})")
            failed.append("RFAA")

    if tools_enabled.get("pxdesign_local"):
        print_step("Running PXDesign")
        rc = subprocess.run(["bash", str(run_dir / "run_pxdesign.sh")]).returncode
        if rc == 0:
            print_ok("PXDesign completed")
        else:
            print_fail(f"PXDesign failed (exit code {rc})")
            failed.append("PXDesign")

    if tools_enabled.get("evaluator"):
        print_step("Running Evaluator  (Boltz2 + AF2 refolding — this may take a while)")
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
        ["PDB or mmCIF file path", "Amino acid sequence (requires structure prediction first)"],
        default_index=0,
    )

    if "sequence" in input_type.lower():
        print()
        print_warn("You need to predict the structure first.")
        print("  Recommended: ColabFold")
        print("    1. Paste your sequence into the AlphaFold2 ColabFold notebook")
        print("    2. Download the best-ranked .pdb file")
        print("    3. Come back and provide the .pdb path below")
        print()

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
    print(f"  {BOLD}RFAA{RESET}      [{_tag('rfaa')}]")
    use_rfaa = ask_yn("  Enable RFDiffusionAA (ligand binder design)?", default=False)
    print(f"  {BOLD}PXDesign{RESET}  [{_tag('pxdesign_local')}] / [external import]")
    pxdesign_mode, _ = ask_choice(
        "  PXDesign mode",
        ["Skip", "Run locally (requires install)", "Import external results"],
        default_index=0,
    )
    use_pxdesign = pxdesign_mode > 0
    use_pxdesign_local = pxdesign_mode == 1
    use_pxdesign_import = pxdesign_mode == 2
    print(f"  {BOLD}Evaluator{RESET} [{_tag('evaluator')}]")
    use_evaluator = ask_yn("  Enable cross-evaluation (Boltz2 + AF2 refolding)?", default=False)

    tools_enabled = {
        "mosaic": use_mosaic,
        "boltzgen": use_boltzgen,
        "bindcraft": use_bindcraft,
        "rfaa": use_rfaa,
        "pxdesign": use_pxdesign,
        "pxdesign_local": use_pxdesign_local,
        "pxdesign_import": use_pxdesign_import,
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
            n_lengths = len(range(cfg["pxdesign_min_length"], cfg["pxdesign_max_length"] + 1, cfg["pxdesign_length_step"]))
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

    if use_rfaa:
        print_step("Step 6e — RFDiffusionAA + LigandMPNN settings")
        print("  RFAA designs all-atom backbones for ligand-binding proteins.")
        print("  LigandMPNN then designs sequences for each backbone.")

        cfg["rfaa_ligand"] = (
            ask(
                "  Ligand CCD code (3 letters, e.g. OQO, HEM, ATP; blank=protein-only)",
                default="",
                validator=lambda s: (
                    True
                    if s.strip() == ""
                    else (
                        True
                        if len(s.strip()) == 3 and s.strip().isalpha()
                        else "Must be exactly 3 letters (CCD code) or blank"
                    )
                ),
            )
            .strip()
            .upper()
            or None
        )
        cfg["rfaa_contigs"] = ask(
            "  Contig string (e.g. '150-150' for 150-residue binder)",
            default=f"{cfg['min_length']}-{cfg['max_length']}",
        )
        cfg["rfaa_n_designs"] = int(
            ask(
                "  Number of backbone designs",
                default=cfg["n_designs"],
                validator=validate_int(min_val=1, max_val=1000),
            )
        )
        cfg["rfaa_diffusion_steps"] = int(
            ask("  Diffusion steps (T)", default=100, validator=validate_int(min_val=10, max_val=500))
        )
        print()
        print(f"  {BOLD}LigandMPNN sequence design{RESET}")
        cfg["lmpnn_seqs_per_backbone"] = int(
            ask("  Sequences per backbone", default=5, validator=validate_int(min_val=1, max_val=100))
        )
        cfg["lmpnn_temperature"] = float(ask("  Sampling temperature (0.05=conservative, 0.3=diverse)", default="0.1"))

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
    if use_rfaa:
        ligand_label = cfg.get("rfaa_ligand") or "(protein-only)"
        print(
            f"  {CYAN}RFAA{RESET}:          ligand={ligand_label}  contigs={cfg.get('rfaa_contigs')}  "
            f"backbones={cfg.get('rfaa_n_designs')}  T={cfg.get('rfaa_diffusion_steps')}"
        )
        print(
            f"  {CYAN}LigandMPNN{RESET}:    seqs/backbone={cfg.get('lmpnn_seqs_per_backbone')}  "
            f"temperature={cfg.get('lmpnn_temperature')}"
        )
    if use_pxdesign_local:
        print(
            f"  {CYAN}PXDesign{RESET}:      preset={cfg.get('pxdesign_preset')}  "
            f"samples={cfg.get('pxdesign_n_samples')}  "
            f"binder_len={cfg.get('pxdesign_binder_length')}"
        )
    elif use_pxdesign_import:
        print(f"  {CYAN}PXDesign{RESET}:      import from {cfg.get('pxdesign_output_dir')}")
    if use_evaluator:
        print(f"  {CYAN}Evaluator{RESET}:     Boltz2 + AF2 refolding → comparison report")

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
        print_warn("Evaluator runs Boltz2 + AF2 refolding (GPU recommended, ~30 min per design).")

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
        if use_rfaa:
            print(f"  {step}. bash {run_dir}/run_rfaa.sh")
            step += 1
        if use_pxdesign_local:
            print(f"  {step}. bash {run_dir}/run_pxdesign.sh")
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
        if (run_dir / "run_rfaa.sh").exists():
            tools.append("RFAA")
        if (run_dir / "run_pxdesign.sh").exists():
            tools.append("PXDesign")
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

        report_html = run_dir / "evaluate" / "comparison_report" / "report.html"
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
