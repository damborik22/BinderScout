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
import ast
import datetime as _dt
import difflib
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
# The maintained template lives in this repo. The copy under Mosaic/ is written
# at install time and then goes stale: a checkout installed before the 2026-07-08
# epitope work carries a parameter block with no TARGET_PDB and no EPITOPE_IDX,
# so the exact-match injection below silently missed and emitted a hallucinate.py
# still containing TARGET_SEQUENCE = "REPLACE_ME". Prefer the repo copy; fall back
# to the installed one only if the repo template is absent.
MOSAIC_HALLUCINATE_SRC_REPO = BINDMASTER_DIR / "bindmaster_examples" / "hallucinate_bindmaster.py"
MOSAIC_HALLUCINATE_SRC_INSTALLED = MOSAIC_DIR / "examples" / "bindmaster_examples" / "hallucinate_bindmaster.py"
MOSAIC_HALLUCINATE_SRC = (
    MOSAIC_HALLUCINATE_SRC_REPO if MOSAIC_HALLUCINATE_SRC_REPO.is_file() else MOSAIC_HALLUCINATE_SRC_INSTALLED
)
NANOBODY_SCAFFOLDS_SRC = BOLTZGEN_DIR / "example" / "nanobody_scaffolds"
NANOBODY_SCAFFOLD_NAMES = ["7eow", "7xl0", "8coh", "8z8v"]

# ── Design tools, in execution order — the single source of truth ────────────
# (tools_enabled key, run-script filename, display label, output subdir)
#
# Every UI surface iterates this: the Step 7 preview tree, the "To run later"
# list, run_pipeline() and write_run_all(). They were four independently
# maintained if-chains, and three of them fell behind: the preview tree knew 4
# of the 7 tools, the next-steps list and run_pipeline knew 5. A user could
# enable RFD3 or Protein-Hunter, watch the wizard generate run_rfd3.sh, and then
# never be told the script existed — while "Run the pipeline now?" silently
# skipped it. Adding a tool must not require editing four places.
TOOL_SEQUENCE: list[tuple[str, str, str, str]] = [
    ("mosaic", "run_mosaic.sh", "Mosaic", "mosaic"),
    ("boltzgen", "run_boltzgen.sh", "BoltzGen", "boltzgen"),
    ("bindcraft", "run_bindcraft.sh", "BindCraft", "bindcraft"),
    ("pxdesign_local", "run_pxdesign.sh", "PXDesign", "pxdesign"),
    ("proteina_complexa", "run_proteina_complexa.sh", "Proteina-Complexa", "proteina_complexa"),
    ("rfd3", "run_rfd3.sh", "RFD3", "rfd3"),
    ("protein_hunter", "run_protein_hunter.sh", "Protein-Hunter", "protein_hunter"),
]


def enabled_tools(tools_enabled: dict) -> list[tuple[str, str, str, str]]:
    """TOOL_SEQUENCE entries whose tools_enabled key is truthy, in execution order."""
    return [entry for entry in TOOL_SEQUENCE if tools_enabled.get(entry[0])]


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

# install/install.sh writes one marker file per tool here, named by the tool's
# canonical lowercase key, only AFTER that tool's install function has fully
# succeeded — and removes it again at the start of a re-install. Its existence is the
# only thing that separates "finished" from "died halfway": conda creates an env
# directory (and its bin/python symlink) at the START of solving and leaves both
# behind when the install fails, so a directory probe reports a failed install as
# `installed` forever and the user only finds out when the GPU run dies on a
# ModuleNotFoundError.
INSTALL_STATE_DIR = BINDMASTER_DIR / ".install_state"

# `bindmaster` is a shortcut created BY the installer, so on a fresh clone the bare
# command does not resolve yet and printing it as a hint sends the user nowhere.
# Same check bindmaster.py makes for its own usage block.
_INVOKE = "bindmaster" if shutil.which("bindmaster") else str(BINDMASTER_DIR / "bindmaster.py")


def _marked(key: str) -> bool:
    """True if install.sh recorded an install of `key` (earned or back-filled)."""
    return (INSTALL_STATE_DIR / key).is_file()


def _any_marker() -> bool:
    """True if the marker store holds at least one marker.

    Keyed on the files, not on ``INSTALL_STATE_DIR.is_dir()``: ``clear_tool_mark``
    is ``rm -f``, so ``--uninstall --tool all`` leaves the directory in place but
    empty. An empty store means "no marker information" and must fall back to the
    probes; reading it as "markers exist, none of them set" reported every tool
    uninstalled on a box where everything worked.
    """
    try:
        return any(p.is_file() for p in INSTALL_STATE_DIR.iterdir())
    except OSError:
        return False


def detect_installs() -> dict:
    """
    Once the marker store is non-empty, a tool counts as installed when it has BOTH
    a marker from install/install.sh AND a passing probe.

    Both halves are load-bearing, and each alone was wrong in a way that shipped:

    * **Marker alone** — a marker outlives the thing it describes. Delete a conda env
      by hand and the tool still reads "installed", which is BUG-06 in mirror image.
    * **Probe alone** — a conda env directory or a venv python binary cannot tell a
      finished install from one that died half way, which is what BUG-06 was.

    While the store is empty the probes are the only source, so a box installed
    before markers existed still reads correctly. ``install.sh`` closes that gap in
    the other direction with ``backfill_install_markers()``, which records a marker
    for every passing probe before it can write the first real one — without it, the
    first ``install --tool X`` made one marker authoritative and every other working
    tool went dark here, taking the Step-9 refold engines with it.

    A missing marker directory is "no markers", not an error.
    """

    def _env_exists(name: str) -> bool:
        if CONDA_ENVS_DIR is None:
            return False
        return (CONDA_ENVS_DIR / name).is_dir()

    markers = _any_marker()

    def _installed(key: str, probe: bool) -> bool:
        return (_marked(key) and probe) if markers else probe

    return {
        "bindcraft": _installed("bindcraft", _env_exists("BindCraft")),
        "boltzgen": _installed("boltzgen", _env_exists("BoltzGen")),
        "mosaic": _installed("mosaic", (MOSAIC_VENV / "bin" / "python").exists()),
        "evaluator": _installed("evaluator", (EVALUATOR_DIR / "evaluate.sh").exists() and _env_exists("binder-eval")),
        "pxdesign_local": _installed("pxdesign", _env_exists("bindmaster_pxdesign")),
        "proteina_complexa": _installed("proteina_complexa", (PROTEINA_COMPLEXA_VENV / "bin" / "python").exists()),
        "rfd3": _installed(
            "rfd3", _env_exists("bindmaster_rfd3") and (FOUNDRY_WEIGHTS_DIR / "rfd3_latest.ckpt").exists()
        ),
        "protein_hunter": _installed(
            "protein_hunter", _env_exists("bindmaster_protein_hunter") and PROTEIN_HUNTER_DIR.exists()
        ),
        "af3": _installed("af3", _env_exists("binder-eval-af3")),
        "esmfold2": _installed("esmfold2", _env_exists("binder-eval-esmfold2")),
        "soluprot": _installed("soluprot", _env_exists("binder-eval-soluprot")),
        "tmprot": _installed("tmprot", _env_exists("binder-eval-tmprot")),
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


def pdb_chain_residue_numbers(pdb_path: str, chain_id: str) -> list[int]:
    """Ordered residue numbers for CA atoms of chain_id.

    Parallels extract_sequence_from_pdb: element i here is residue i of that
    sequence, so it maps a hotspot residue number to its 0-based sequence index.
    """
    out: list[int] = []
    seen: set = set()
    try:
        with open(Path(pdb_path).expanduser()) as f:
            for line in f:
                if line[:4] != "ATOM":
                    continue
                if line[12:16].strip() != "CA":
                    continue
                if line[21].strip().upper() != chain_id.upper():
                    continue
                key = (line[22:26].strip(), line[26].strip())
                if key not in seen:
                    seen.add(key)
                    try:
                        out.append(int(line[22:26]))
                    except ValueError:
                        out.append(-1)
    except OSError:
        return []
    return out


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


def _cif_chain_ca_residues(text: str, chain_id: str) -> tuple[list[int], str]:
    """Ordered label_seq_ids and the 1-letter sequence of chain_id's CA atoms in a CIF.

    The mmCIF counterpart of _pdb_chain_ca_residues: element i of the id list is residue
    i of the returned sequence, so a per-residue annotation keyed on label_seq_id can be
    mapped onto a position in the extracted sequence. ([], "") when the chain has no CA
    records (or the file has no _atom_site loop at all).
    """
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
                if resnum not in seen:
                    seen[resnum] = AA3TO1.get(resname, "X")
            i += n_cols
        if seen:
            ids = sorted(seen)
            return ids, "".join(seen[k] for k in ids)
    return [], ""


def extract_sequence_from_cif(cif_path: str, chain_id: str) -> str | None:
    """Extract amino-acid sequence for chain_id from a CIF/mmCIF file.

    Returns a 1-letter string, or None on failure.
    """
    try:
        text = Path(cif_path).expanduser().read_text(errors="replace")
    except OSError:
        return None

    # _atom_site CA records for the requested chain FIRST: this is the only branch that can
    # honour chain_id. _entity_poly is chain-agnostic (it returns the longest entity), so trying
    # it first silently discarded the user's chain answer for every mmCIF that has one — i.e.
    # essentially every structure downloaded from the PDB.
    _ids, seq_from_atoms = _cif_chain_ca_residues(text, chain_id)
    if seq_from_atoms:
        return seq_from_atoms

    # No CA records for that chain (or no _atom_site at all — e.g. a sequence-only mmCIF).
    # _entity_poly is the last resort, but it cannot honour chain_id, so say so rather than
    # returning a different chain's sequence as if it were the requested one.
    seq = _cif_entity_poly_seq(text)
    if seq:
        print_warn(
            f"Chain {chain_id} has no CA records in {Path(cif_path).name} — falling back to the "
            f"longest _entity_poly entity ({len(seq)} aa), which may be a different chain. "
            f"Check the length before continuing."
        )
        return seq
    return None


def extract_sequence_from_structure(path: str, chain_id: str) -> str | None:
    """Dispatcher: extract sequence from PDB or mmCIF file."""
    p = Path(path).expanduser()
    if p.suffix.lower() in (".cif", ".mmcif"):
        return extract_sequence_from_cif(str(p), chain_id)
    return extract_sequence_from_pdb(str(p), chain_id)


# ─── Expression-tag detection ────────────────────────────────────────────────
#
# A stock RCSB entry is the CONSTRUCT that was crystallised, not the biological target.
# 5O45 (PD-L1) carries eleven extra residues on chain A — AAALE + His6 — and in the
# extracted sequence they are indistinguishable from the protein. Left in, they become
# designable surface AND are baked into the target-MSA cache key (the target sequence's
# SHA-256, shared by every refold engine), so a "hit" can be designed against a cloning
# linker that does not exist in vivo.
#
# The depositor already said which residues those are, per residue, by hand, at
# deposition time: SEQADV in a PDB file, _struct_ref_seq_dif in an mmCIF. That is
# authoritative. A regex over the sequence is a guess, and guessing the LINKER cannot
# work in general — real constructs use AAALE, LE (an XhoI site), GSGS, ENLYFQG (TEV),
# LVPRGS (thrombin), GGGGS repeats — which is exactly how the original [GSAL]{0,3}
# character class stopped at the 'E' of AAALE on 5O45 and trimmed 6 of 11 residues.

# Free-text annotations treated as "this residue is construct, not protein".
# ACCEPTED: EXPRESSION TAG, CLONING ARTIFACT, LINKER — all three describe sequence added
# in order to express or purify the protein, i.e. sequence that is not in the organism.
# NOT accepted: CONFLICT, VARIANT, ENGINEERED MUTATION, MICROHETEROGENEITY, INSERTION,
# DELETION, SEE REMARK 999. The first four are real residues of the (possibly mutated)
# protein that was crystallised; INSERTION/DELETION record a difference from the
# reference database entry — an isoform, a renumbering — not added sequence. Dropping
# any of them would change the protein rather than undo the construct.
_CONSTRUCT_ANNOTATIONS = ("EXPRESSION TAG", "CLONING ARTIFACT", "LINKER")

# FALLBACK ONLY, for files that carry no per-residue annotation (a predicted structure, a
# hand-built PDB, a pasted sequence). The linker beside a poly-His run is matched by NAME
# — the forms that actually occur: 5O45's AAALE, LE from an XhoI site, GS/GGGGS repeats,
# ENLYFQG for TEV, LVPRGS for thrombin, pET's SSGLVPRGS.
#
# "Up to five residues of anything" was tried first and is WRONG, which is worth
# recording: with no annotation to lean on, a pattern cannot tell a 0-residue linker from
# a 5-residue one, so `[A-Z]{0,5}H{6,10}$` trims five residues of native protein off a
# plain His6 tag (…ITVKVNAPY|HHHHHH became …ITVK). Linkers of arbitrary composition are
# exactly what the SEQADV / _struct_ref_seq_dif path above is for; a named list is the
# most a guess can honestly offer, and the prompt shows the residues so the user can see
# whether more should go.
_HIS_LINKER_BEFORE = r"(?:AAALE|ENLYFQ[GS]|SSGLVPRGS|LVPR[GS]{1,2}|(?:GGGGS)+|(?:GS)+|LE|[GSAL]{0,3})"
_HIS_LINKER_AFTER = r"(?:ENLYFQ[GS]|LVPRGS|(?:GGGGS)+|[GSAL]{0,4})"
_TAG_PATTERNS = [
    ("His6/His8", re.compile(_HIS_LINKER_BEFORE + r"H{5,10}$")),
    ("His6 (N-term)", re.compile(r"^M?" + _HIS_LINKER_BEFORE + r"H{5,10}" + _HIS_LINKER_AFTER)),
    ("Strep-II", re.compile(r"WSHPQFEK$")),
    ("FLAG", re.compile(r"DYKDDDDK$")),
    ("Myc", re.compile(r"EQKLISEEDL$")),
]


def _pdb_seqadv_construct(lines: list[str], chain_id: str) -> dict[tuple[str, str], str]:
    """(resSeq, iCode) -> resName for chain_id's SEQADV records annotated as construct.

    SEQADV is fixed-column (1-based): resName 13-15, chainID 17, seqNum 19-22, iCode 23,
    and the free-text conflict field 50-70, which is where "EXPRESSION TAG" lives.
    """
    flagged: dict[tuple[str, str], str] = {}
    for line in lines:
        if line[:6] != "SEQADV" or len(line) < 50:
            continue
        if line[16].strip().upper() != chain_id.upper():
            continue
        note = line[49:70].strip().upper()
        if not any(a in note for a in _CONSTRUCT_ANNOTATIONS):
            continue
        flagged[(line[18:22].strip(), line[22].strip())] = line[12:15].strip().upper()
    return flagged


def _cif_loop_rows(text: str, category: str) -> list[dict]:
    """Rows of the `loop_` whose columns belong to `category` (e.g. "_struct_ref_seq_dif").

    Only the loop_ form is read. A category with exactly one row is written as plain
    key-value pairs instead and returns []; one annotated residue is not a tag run worth
    trimming, and the pattern fallback still sees the sequence.
    """
    tokens = _cif_tokenize(text)
    prefix = category.lower() + "."
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
        if not cols or not cols[0].startswith(prefix):
            continue
        names = [c.split(".", 1)[1] for c in cols]
        n_cols = len(cols)
        rows: list[dict] = []
        while i + n_cols <= len(tokens):
            if tokens[i].lower() == "loop_" or (tokens[i].startswith("_") and "." in tokens[i]):
                break
            rows.append(dict(zip(names, tokens[i : i + n_cols])))
            i += n_cols
        return rows
    return []


def _cif_seqdif_construct(text: str, chain_id: str) -> dict[int, str]:
    """label_seq_id -> mon_id for chain_id's _struct_ref_seq_dif rows annotated as construct.

    The mmCIF equivalent of SEQADV: `details` carries the same free text (lower-cased by
    convention — 'expression tag'), `seq_num` is the entity sequence index, which is the
    numbering _cif_chain_ca_residues orders by, and `pdbx_pdb_strand_id` names the chain.

    Caveat, and why the caller cross-checks residue names: pdbx_pdb_strand_id is the
    AUTHOR chain id while _atom_site.label_asym_id (what the sequence extractor filters
    on) is the label chain id, and those are not the same namespace in every entry.
    """
    flagged: dict[int, str] = {}
    for row in _cif_loop_rows(text, "_struct_ref_seq_dif"):
        if row.get("pdbx_pdb_strand_id", "").upper() != chain_id.upper():
            continue
        if not any(a in row.get("details", "").upper() for a in _CONSTRUCT_ANNOTATIONS):
            continue
        try:
            flagged[int(row["seq_num"])] = row.get("mon_id", "").upper()
        except (KeyError, ValueError):
            continue
    return flagged


def _terminal_construct_span(flagged: set, n: int) -> tuple[int, int]:
    """[start, end) of an n-residue sequence to KEEP, given 0-based construct positions.

    ONLY a contiguous run at the N- and/or C-terminus is removed. An interior annotation
    is NOT a tag: it is a point mutation, an engineered variant or a numbering conflict —
    a real residue of the chain that was crystallised — and excising it would splice two
    distant stretches of the protein together, corrupting the sequence and putting it
    permanently out of step with the coordinates (and with every hotspot number the user
    typed). A purification tag sits at a terminus by construction, so restricting the
    trim to the termini costs nothing and makes the interior case impossible rather than
    merely unlikely.
    """
    start = 0
    while start < n and start in flagged:
        start += 1
    if start == n:  # every residue flagged: not a tag, and emptying the chain is never right
        return 0, n
    end = n
    while end > start and end - 1 in flagged:
        end -= 1
    return start, end


def _annotated_construct_span(seq: str, struct_path: str, chain_id: str) -> tuple[int, int, str, int] | None:
    """(start, end, evidence, n_interior) from the deposited file's own annotation.

    `seq[start:end]` is the biological target. None means this file carries no usable
    construct annotation for this chain and the caller should fall back to the pattern
    guess.
    """
    p = Path(struct_path).expanduser()
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return None

    if p.suffix.lower() in (".cif", ".mmcif"):
        cif_ids, chain_seq = _cif_chain_ca_residues(text, chain_id)
        ids: list = list(cif_ids)
        flagged: dict = _cif_seqdif_construct(text, chain_id)
        source = "_struct_ref_seq_dif"
    else:
        lines = text.splitlines()
        ids, chain_seq = _pdb_chain_ca_residues(lines, chain_id)
        flagged = _pdb_seqadv_construct(lines, chain_id)
        source = "SEQADV"

    # The annotation is per RESIDUE, so it can only be applied to the exact residue list
    # the sequence was extracted from. If the two disagree, hand over rather than guess
    # at an offset.
    if not flagged or chain_seq != seq:
        return None

    positions = {i for i, rid in enumerate(ids) if rid in flagged}
    # The annotated residue NAME must agree with the residue about to be dropped. This is
    # what makes the mmCIF path safe despite the author/label chain-id namespaces above:
    # if the two ids denote different chains the names do not line up, and the annotation
    # is refused rather than applied to the wrong residues.
    for i in sorted(positions):
        if seq[i] != AA3TO1.get(flagged[ids[i]], "X"):
            rid = "".join(ids[i]) if isinstance(ids[i], tuple) else str(ids[i])
            print_warn(f"{p.name}: {source} residue {rid} does not match chain {chain_id} — annotation ignored.")
            return None

    start, end = _terminal_construct_span(positions, len(seq))
    if (start, end) == (0, len(seq)):
        return None
    interior = len(positions - set(range(start)) - set(range(end, len(seq))))
    return start, end, f"the depositor's own {source} records in {p.name}", interior


def _offer_tag_trim(seq: str, start: int, end: int, label: str, evidence: str, interior: int = 0) -> str:
    """Report a detected construct region, say where the evidence came from, and ask."""
    n_dropped = start + (len(seq) - end)
    print()
    print_warn(f"{label} detected — {n_dropped} residue(s) of {len(seq)}:")
    if start:
        print(f"    N-terminal: {seq[:start]}…")
    if end < len(seq):
        print(f"    C-terminal: …{seq[end:]}")
    print(f"  Evidence: {evidence}")
    print("  Leaving it in makes the tag a designable epitope and is baked into the")
    print("  cached target MSA, so designs may bind something that does not exist.")
    if interior:
        print(f"  {interior} further annotated residue(s) are INTERIOR and are KEPT — an interior")
        print("  annotation is a point mutation or a conflict, not added sequence.")
    if not ask_yn(f"  Trim {n_dropped} residues?", default=True):
        print_warn("Keeping the tag — make sure that is what you want.")
        return seq
    trimmed = seq[start:end]
    print_ok(f"Trimmed to {len(trimmed)} aa")
    print("  The structure is trimmed to match when the run folder is generated")
    print("  (target/<name>.pdb); the untouched deposited file is kept beside it.")
    print("  Keep hotspots off the trimmed residues in Step 3.")
    return trimmed


def warn_expression_tags(seq: str, struct_path: str | None = None, chain_id: str = "") -> str:
    """Offer to trim expression-tag residues from an extracted target sequence.

    Priority: the deposited file's own per-residue annotation (PDB SEQADV / mmCIF
    _struct_ref_seq_dif), then — only if the file carries none — a sequence pattern.
    Always asks, because a genuine poly-histidine stretch in a real protein would be a
    false positive, and always says WHICH of the two found it: one is the depositor's
    statement of fact about their own construct, the other is a guess.
    """
    if struct_path and chain_id:
        annotated = _annotated_construct_span(seq, struct_path, chain_id)
        if annotated:
            start, end, evidence, interior = annotated
            return _offer_tag_trim(seq, start, end, "Expression-tag residues", evidence, interior)

    guess = "a sequence pattern — a GUESS; this file carries no per-residue tag annotation."
    for label, pat in _TAG_PATTERNS:
        m = pat.search(seq)
        if not m or not m.group(0):
            continue
        start, end = (m.end(), len(seq)) if m.start() == 0 else (0, m.start())
        if start >= end:
            continue  # a pattern that claims the whole chain is a false positive, not a tag
        trimmed = _offer_tag_trim(seq, start, end, f"Possible {label} expression tag", guess)
        if trimmed != seq:
            return trimmed
    return seq


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
            # The space between atom_field and comp_id is the altLoc column (17). Without
            # it every field from resName on was one column left of where the PDB format
            # puts it, so this project's own extract_sequence_from_pdb read the chain ID
            # out of the residue number and returned None for the converted file — and
            # prepare_target_pdb below would find no residues to keep in a CIF target.
            line = (
                f"{record}{serial:5d} {atom_field} {comp_id:>3s} {chain[0]:1s}{seq_id:4d}    "
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


# ─── Target structure preparation ────────────────────────────────────────────

# Header records copied through to the prepared file. Everything else is dropped,
# because every other record names an atom, residue or chain that preparation may
# have removed: SEQRES, LINK, SSBOND, CISPEP, HELIX, SHEET, SITE, HET/HETNAM/FORMUL,
# CONECT, ANISOU, MASTER, and COMPND (which lists the chains by name).
#
# SEQRES is DROPPED, not regenerated. With no SEQRES every parser we feed derives the
# sequence from the ATOM records, so header and coordinates cannot disagree; a
# regenerated SEQRES is a second, hand-rolled source of truth whose first off-by-one
# reintroduces the exact crash this preparation exists to avoid — BoltzGen builds its
# entities from SEQRES and then indexes `entity.subchains[0]`
# (BoltzGen/src/boltzgen/data/parse/pdb_parser.py:39), so a SEQRES declaring 129
# residues against 118 surviving ATOM records dies with `IndexError: list index out of
# range`. It also keeps a dropped His-tag from being recoverable out of the header
# after its atoms are gone. Targets that come in through the "provide a sequence" path
# already reach the tools without SEQRES, so this is not a new shape of input.
_PDB_HEADER_KEEP = ("HEADER", "TITLE ", "CRYST1")

_WATER_RESIDUES = ("HOH", "DOD", "WAT")


def _pdb_chain_ca_residues(lines: list[str], chain_id: str) -> tuple[list[tuple[str, str]], str]:
    """Ordered (resSeq, iCode) keys and the 1-letter sequence of chain_id's CA atoms.

    Mirrors extract_sequence_from_pdb: element i of the key list is residue i of the
    returned sequence, so selecting residues by these keys keeps the prepared structure
    and cfg["target_sequence"] in step.
    """
    keys: list[tuple[str, str]] = []
    seq: list[str] = []
    seen: set = set()
    for line in lines:
        if line[:4] != "ATOM" or len(line) < 27:
            continue
        if line[12:16].strip() != "CA":
            continue
        if line[21].strip().upper() != chain_id.upper():
            continue
        if line[16].strip() not in ("", "A"):
            continue
        key = (line[22:26].strip(), line[26].strip())
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
        seq.append(AA3TO1.get(line[17:20].strip().upper(), "X"))
    return keys, "".join(seq)


def _ter_record(serial: int, atom_line: str) -> str:
    """TER for the last kept atom of a chain, in fixed PDB columns."""
    return f"TER   {serial:>5}      {atom_line[17:20]} {atom_line[21]}{atom_line[22:27]}"


def prepare_target_pdb(src_pdb: Path, dest_pdb: Path, chains: str, target_sequence: str) -> dict | None:
    """Write dest_pdb holding only the target: selected chains, no ligands, no waters.

    A stock RCSB file is not a target. On 5O45 (PD-L1) the deposited coordinates carry
    chain A's His6 purification tag AND chain B, an 8-residue inhibitor peptide bound in
    the very epitope a binder has to reach — so BindCraft, RFD3's contigs and BoltzGen's
    `file:` entity were all designing against an occupied site. Trimming the tag out of
    the SEQUENCE (which the wizard already offers) does not touch the coordinates.

    Residue numbering is deliberately NOT renumbered: hotspot residue numbers the user
    gave in Step 3 refer to the deposited numbering and must keep resolving.

    Returns a report dict for the caller to print, or None when nothing survived (a
    structure with no CA atoms in the selected chains) — dest_pdb is then not written
    and the caller falls back to copying the source verbatim.
    """
    try:
        raw = src_pdb.read_text(errors="replace").splitlines()
    except OSError:
        return None

    # First model only: an NMR ensemble would otherwise fold every model's atoms into
    # one chain, which is both wrong and a chain the sequence extractor cannot explain.
    lines: list[str] = []
    for line in raw:
        if line[:6] == "ENDMDL":
            break
        lines.append(line)

    wanted = [c.strip().upper() for c in (chains or "A").split(",") if c.strip()] or ["A"]
    keep: set[tuple[str, tuple[str, str]]] = set()
    kept: dict[str, int] = {}
    construct_kept: dict[str, list[str]] = {}
    trim_failed = ""
    for idx, cid in enumerate(wanted):
        keys, seq = _pdb_chain_ca_residues(lines, cid)
        # The first chain is the one cfg["target_sequence"] was extracted from, so it is
        # the only one a sequence trim can speak about. warn_expression_tags only ever
        # removes a prefix or a suffix, so the trimmed sequence is a contiguous
        # substring and its offset identifies exactly which residues to drop.
        if idx == 0 and target_sequence and seq and target_sequence != seq:
            off = seq.find(target_sequence)
            if off >= 0:
                keys = keys[off : off + len(target_sequence)]
            else:
                trim_failed = cid
        # Backstop for the class of bug this whole path exists for: the deposited file
        # already names its construct residues, and we are reading those lines anyway.
        # If any residue we are about to KEEP is SEQADV-flagged as an expression tag /
        # cloning artifact / linker, the sequence trim missed it — say so rather than
        # ship it as designable surface.
        flagged = _pdb_seqadv_construct(lines, cid)
        still = [f"{k[0]}{k[1]}" for k in keys if k in flagged]
        if still:
            construct_kept[cid] = still
        kept[cid] = len(keys)
        keep.update((cid, k) for k in keys)

    if not keep:
        return None

    dropped_chains: dict[str, int] = {}
    trimmed = 0
    waters = 0
    ligands: dict[str, int] = {}
    seen_res: set = set()
    for line in lines:
        if line[:4] not in ("ATOM", "HETA") or len(line) < 27:
            continue
        cid = line[21].strip().upper()
        res = line[17:20].strip().upper()
        key = (line[22:26].strip(), line[26].strip())
        if (line[:4], cid, key, res) in seen_res:
            continue
        seen_res.add((line[:4], cid, key, res))
        if line[:4] == "HETA":
            if res in _WATER_RESIDUES:
                waters += 1
            else:
                ligands[res] = ligands.get(res, 0) + 1
        elif (cid, key) not in keep:
            if cid in wanted:
                trimmed += 1
            else:
                dropped_chains[cid] = dropped_chains.get(cid, 0) + 1

    out: list[str] = [line.rstrip() for line in lines if line[:6] in _PDB_HEADER_KEEP]
    out.append("REMARK 999 PREPARED BY BINDMASTER CONFIGURATOR - THIS IS NOT THE DEPOSITED FILE")
    out.append("REMARK 999 KEPT CHAIN(S): " + ", ".join(f"{c} ({n} RESIDUES)" for c, n in kept.items()))
    if dropped_chains:
        out.append(
            "REMARK 999 DROPPED CHAIN(S): " + ", ".join(f"{c} ({n} RESIDUES)" for c, n in dropped_chains.items())
        )
    out.append(f"REMARK 999 DROPPED {trimmed} TRIMMED RESIDUE(S), {waters} WATER(S), {sum(ligands.values())} HETERO")
    out.append("REMARK 999 SEQRES/LINK/CONECT/ANISOU OMITTED - SEQUENCE DERIVES FROM THE ATOM RECORDS")
    out.append(f"REMARK 999 UNTOUCHED SOURCE KEPT ALONGSIDE AS {src_pdb.name.upper()}")

    serial = 0
    current_chain = None
    last_kept = None
    for line in lines:
        if line[:4] != "ATOM" or len(line) < 27:
            continue
        if line[16].strip() not in ("", "A"):
            continue
        cid = line[21].strip().upper()
        if (cid, (line[22:26].strip(), line[26].strip())) not in keep:
            continue
        if current_chain is not None and cid != current_chain:
            serial += 1
            out.append(_ter_record(serial, last_kept))
        current_chain = cid
        serial += 1
        out.append(f"{line[:6]}{serial:>5}{line[11:].rstrip()}")
        last_kept = line
    if last_kept is not None:
        serial += 1
        out.append(_ter_record(serial, last_kept))
    out.append("END")

    dest_pdb.parent.mkdir(parents=True, exist_ok=True)
    dest_pdb.write_text("\n".join(out) + "\n")
    return {
        "kept": kept,
        "dropped_chains": dropped_chains,
        "trimmed": trimmed,
        "waters": waters,
        "ligands": ligands,
        "trim_failed": trim_failed,
        "construct_kept": construct_kept,
    }


def report_target_preparation(report: dict, dest_pdb: Path) -> None:
    """Say out loud what preparation changed — silence here is how BUG-16 stayed hidden."""
    kept = ", ".join(f"{c} ({n} aa)" for c, n in report["kept"].items())
    print_ok(f"Prepared target structure {dest_pdb.name} — kept chain(s) {kept}")
    empty = [c for c, n in report["kept"].items() if not n]
    if empty:
        print_warn(f"  Selected chain(s) {', '.join(empty)} have no amino-acid residues in this file.")
    if report["dropped_chains"]:
        dropped = ", ".join(f"{c} ({n} res)" for c, n in report["dropped_chains"].items())
        print_warn(f"  Dropped unselected chain(s): {dropped}")
        print("    A chain left in the file is part of the target as far as every design tool")
        print("    is concerned — a bound inhibitor peptide or a second copy of the protein")
        print("    occupies the epitope the binder has to reach.")
    if report["trimmed"]:
        print_ok(f"  Dropped {report['trimmed']} residue(s) so the coordinates match target_sequence")
        print("    (the trimmed expression tag; hotspot numbering is unchanged).")
    if report["waters"] or report["ligands"]:
        ligands = ", ".join(f"{n}×{res}" for res, n in sorted(report["ligands"].items()))
        print_ok(f"  Dropped {report['waters']} water(s) and {sum(report['ligands'].values())} heteroatom residue(s)")
        if ligands:
            print(f"    ({ligands})")
    for cid, residues in (report.get("construct_kept") or {}).items():
        shown = ", ".join(residues[:12]) + (", …" if len(residues) > 12 else "")
        print_warn(f"  Chain {cid} KEEPS {len(residues)} residue(s) the depositor flagged as construct: {shown}")
        print("    SEQADV marks these as an expression tag / cloning artifact / linker — not part")
        print("    of the biological target. They stay designable surface and go into the shared")
        print("    target-MSA cache key. Re-run and accept the tag trim in Step 3, or keep")
        print("    hotspots off them on purpose.")
    if report["trim_failed"]:
        print_warn(f"  cfg['target_sequence'] is not a contiguous part of chain {report['trim_failed']} as built.")
        print("    No residues were trimmed from it, so sequence and coordinates may disagree.")
    print(f"  The untouched source is kept alongside it in {dest_pdb.parent}")


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
        print("  │   ├── <target>.cif  (untouched source)")
        print("  │   ├── <target>_original.pdb  (converted, untouched)")
    else:
        print("  │   ├── <target>_original.pdb  (untouched source)")
    print("  │   └── <target>.pdb  (prepared: selected chains only, no ligands/waters)")
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
    scripts = [script for _key, script, _label, _subdir in enabled_tools(tools_enabled)]
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


# BoltzGen over-generates and then filters down to --budget, so the intermediate pool
# is a real knob — but it defaulted to a flat 10 000 and was never reconciled with the
# number of designs the user asked for. An `n_designs: 1` smoke test therefore carried
# `--num_designs 10000`: measured on an RTX 3090, 1000 dataloader steps at ~53 s/step,
# ETA 14 h 53 m, for one requested design, while every other tool honoured the count.
# Scale the pool with the request, with a floor so filtering still has something to
# filter, and keep cfg["boltzgen_intermediate"] as the explicit override.
_BOLTZGEN_INTERMEDIATE_FLOOR = 50
_BOLTZGEN_INTERMEDIATE_PER_DESIGN = 100
# Same 3090 measurement: 10 000 designs in ~14 h 53 m ≈ 5.35 s of GPU time each.
_BOLTZGEN_SECONDS_PER_DESIGN = 5.35


def boltzgen_intermediate_default(n_designs: int) -> int:
    """Intermediate pool implied by a requested design count."""
    return max(_BOLTZGEN_INTERMEDIATE_FLOOR, _BOLTZGEN_INTERMEDIATE_PER_DESIGN * int(n_designs))


def boltzgen_budget(cfg: dict) -> int:
    """BoltzGen --budget: the per-tool override when set, else the global design count.

    One resolver, because there were two answers. `--budget`, settings.json's "budget"
    and the YAML's documented run line all read cfg["n_designs"] directly and ignored
    cfg["boltzgen_budget"] — the per-tool override the wizard prompts for — while the
    intermediate-pool derivation did consult it. A wizard run with budget 20 over a
    global n_designs of 10 therefore generated a pool sized for 20 and a --budget of 10.
    cfg["n_designs"] is indexed, not .get(): the fallback has to exist, and preflight
    reporting a missing key beats silently designing one binder.
    """
    return int(cfg.get("boltzgen_budget") or cfg["n_designs"])


def boltzgen_intermediate(cfg: dict) -> int:
    """BoltzGen --num_designs: the explicit override when set, else derived from the count."""
    override = cfg.get("boltzgen_intermediate")
    if override:
        return int(override)
    return boltzgen_intermediate_default(boltzgen_budget(cfg))


def boltzgen_cost_note(n_intermediate: int) -> str:
    """ "10,000 intermediate designs (~15 h on one 24 GB GPU)" — the GPU bill, before it is paid."""
    hours = n_intermediate * _BOLTZGEN_SECONDS_PER_DESIGN / 3600
    span = f"~{round(hours * 60)} min" if hours < 1 else f"~{hours:.0f} h"
    return f"{n_intermediate:,} intermediate designs ({span} on one 24 GB GPU)"


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
        f"#       --num_designs {boltzgen_intermediate(cfg)} \\",
        f"#       --budget {boltzgen_budget(cfg)}",
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


def hotspots_to_epitope_idx(cfg: dict) -> list[int] | None:
    """Map configured hotspot residue numbers to 0-based indices into the Mosaic
    target sequence (what BinderTargetContact.epitope_idx expects).

    Prefers the target PDB residue order (His-tag/offset safe: the PDB-derived
    sequence is located within target_sequence to recover any N-terminal offset).
    Falls back to treating hotspots as 1-based positions in target_sequence when
    no PDB is available. Returns None when no hotspots are configured.
    """
    hotspots_str = cfg.get("mosaic_hotspots", "") or cfg.get("hotspots", "") or ""
    hotspot_list = parse_hotspots(hotspots_str) if hotspots_str.strip() else []
    if not hotspot_list:
        return None
    target_seq = cfg.get("target_sequence", "") or ""
    target_pdb = str(cfg.get("target_pdb", "") or "")
    # The wizard stores the chain selection in cfg["chains"] (Step 3). Neither "target_chain"
    # nor "chain" is ever assigned, so those lookups always fell through to "A" and hotspot
    # residue numbers were resolved against chain A no matter what the user picked.
    chain = (cfg.get("chains") or "A").split(",")[0].strip() or "A"
    resnums = pdb_chain_residue_numbers(target_pdb, chain) if target_pdb else []
    if resnums:
        pdb_seq = extract_sequence_from_pdb(target_pdb, chain) or ""
        offset = target_seq.find(pdb_seq) if (pdb_seq and pdb_seq in target_seq) else 0
        if offset < 0:
            offset = 0
        pos = {rn: i for i, rn in enumerate(resnums)}
        idx = sorted(offset + pos[r] for r in hotspot_list if r in pos)
    else:
        idx = sorted(r - 1 for r in hotspot_list if 0 < r <= len(target_seq)) if target_seq else []
    return idx or None


def write_mosaic_hallucinate(path: Path, cfg: dict):
    """
    Copy hallucinate_bindmaster.py and inject run parameters into the
    BINDMASTER PARAMETERS block at the top of the file.
    """
    content = MOSAIC_HALLUCINATE_SRC.read_text()

    target_pdb_path = str(cfg.get("target_pdb", ""))
    epitope_idx = hotspots_to_epitope_idx(cfg)

    old_block = (
        'TARGET_SEQUENCE = "REPLACE_ME"  # target protein sequence\n'
        'TARGET_PDB = ""  # path to target PDB (used as structural template; blank = predict from sequence)\n'
        "N_DESIGNS = 100  # Stage 1: how many designs to generate per length\n"
        "TOP_K = 5  # Stage 2: how many top designs to refold and export PDB\n"
        "MIN_LENGTH = 65  # minimum binder length (aa)\n"
        "MAX_LENGTH = 100  # maximum binder length (aa)\n"
        "LENGTH_STEP = 5  # step between scanned lengths; set MIN=MAX for a single length\n"
        "EPITOPE_IDX = None  # 0-based target-residue indices the binder must contact (hotspots); None = whole surface"
    )
    new_block = (
        f"TARGET_SEQUENCE = {cfg['target_sequence']!r}  # target protein sequence\n"
        f"TARGET_PDB = {target_pdb_path!r}  # path to target PDB (structural template)\n"
        f"N_DESIGNS = {cfg.get('mosaic_n_designs', 100)}  # Stage 1: how many designs to generate per length\n"
        f"TOP_K = {cfg.get('mosaic_top_k', min(5, cfg['n_designs']))}  # Stage 2: how many top designs to refold and export PDB\n"
        f"MIN_LENGTH = {cfg.get('mosaic_min_length', cfg['min_length'])}  # minimum binder length (aa)\n"
        f"MAX_LENGTH = {cfg.get('mosaic_max_length', cfg['max_length'])}  # maximum binder length (aa)\n"
        f"LENGTH_STEP = {cfg.get('mosaic_length_step', 5)}  # step between scanned lengths; set MIN=MAX for a single length\n"
        f"EPITOPE_IDX = {epitope_idx!r}  # 0-based target-residue indices the binder must contact (hotspots); None = whole surface"
    )

    if old_block not in content:
        # Fatal, not a warning. Writing the file anyway ships a hallucinate.py whose
        # TARGET_SEQUENCE is still the "REPLACE_ME" placeholder and whose EPITOPE_IDX
        # is still None — a script that looks runnable, runs, and designs against the
        # wrong target with no hotspots. A warning on stdout does not survive a
        # generate-now-launch-later workflow, and the placeholder has leaked far enough
        # downstream before that the evaluator carries a REPLACE_ME guard of its own.
        print_fail(f"Mosaic template has drifted: {MOSAIC_HALLUCINATE_SRC}")
        print_warn("  Its BINDMASTER PARAMETERS block does not match what the configurator injects.")
        print_warn("  Most likely the Mosaic checkout predates a template change — re-run")
        print_warn("  `bindmaster install --tool mosaic`, or point MOSAIC_HALLUCINATE_SRC at the")
        print_warn("  repo copy in bindmaster_examples/.")
        sys.exit(1)

    content = content.replace(old_block, new_block)
    path.write_text(content)


def write_run_bindcraft(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    conda_base = str(CONDA_BASE) if CONDA_BASE else ""
    bindmaster_dir = str(BINDMASTER_DIR)
    name = cfg["name"]
    target_seq = cfg.get("target_sequence", "")
    chains_str = cfg.get("chains", "A")
    hotspots_str = cfg.get("hotspots", "") or ""

    settings_block = _settings_json_block(
        tool="bindcraft",
        settings_dir_var="SETTINGS_DIR",
        conda_env="BindCraft",
        version_dict_inner="""
    "bindmaster_git_sha": "$GIT_SHA",
    "bindmaster_git_branch": "$GIT_BRANCH",
    "bindcraft_repo_git_sha": "$BINDCRAFT_SHA\"""",
        target_dict_inner=f"""
    "name": "{name}",
    "pdb": "{cfg["target_pdb"]}",
    "sequence": "{target_seq}",
    "length": {len(target_seq)},
    "chains": "{chains_str}",
    "hotspots": "{hotspots_str}\"""",
        design_params_inner=f"""
    "min_binder_length": {cfg.get("bindcraft_min_length", cfg["min_length"])},
    "max_binder_length": {cfg.get("bindcraft_max_length", cfg["max_length"])},
    "number_of_final_designs": {cfg.get("bindcraft_n_designs", cfg["n_designs"])},
    "filter_preset": "{cfg.get("filter_preset", "")}",
    "advanced_preset": "{cfg.get("advanced_preset", "")}",
    "settings_json": "$SETTINGS",
    "filters_json": "$FILTERS",
    "advanced_json": "$ADVANCED\"""",
        extra_env_inner=f'\nBINDCRAFT_SHA=$(git -C "{BINDCRAFT_DIR}" rev-parse HEAD 2>/dev/null || echo "unknown")',
    )

    content = (
        f"""\
#!/usr/bin/env bash
# Run BindCraft for {cfg["name"]}
# Generated by BindMaster Configurator
set -euo pipefail

BINDCRAFT_DIR="{BINDCRAFT_DIR}"
SETTINGS_DIR="{run_dir}/bindcraft"
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
    # shellcheck disable=SC1090
    [[ -f "$_conda_sh" ]] && {{ source "$_conda_sh"; _conda_found=true; break; }}
done
[[ "$_conda_found" == true ]] || {{ echo "ERROR: conda not found — install Miniconda or Miniforge first." >&2; exit 1; }}
conda activate BindCraft
set -u

# aarch64 / GB10: run on the GPU, but cap it in ABSOLUTE terms.
# Two things are different here and both bite. (1) jax must be >= 0.6.2 -- 0.4.34's
# LLVM has no sm_121, so AF2 dies at compile with "Unsupported rounding mode for
# conversion". This script no longer forces JAX_PLATFORMS=cpu; that workaround cost
# ~10x (measured 5.40 -> 2.39 s/iter moving to 0.6.2, and CPU is far worse again).
# (2) The GPU pool IS system RAM, so XLA's default fraction of 0.75 reserves ~91 GiB
# of a 121.7 GiB machine and takes the box down.
# tools/gb10-env.sh owns the per-tool budget table (bindcraft = 24 GiB) and also
# joins the MPS server, so prefer it; the inline fallback only exists so a run
# script still caps itself on a checkout that does not have it.
if [[ "$(uname -m)" == "aarch64" ]]; then
    _gb10_env="$(dirname "$BINDCRAFT_DIR")/tools/gb10-env.sh"
    if [[ -r "$_gb10_env" ]]; then
        # shellcheck disable=SC1090
        source "$_gb10_env" && gb10_apply bindcraft
    else
        export XLA_PYTHON_CLIENT_PREALLOCATE=true
        _bc_pool_gib=$(awk '/MemTotal/{{printf "%d", $2/1048576}}' /proc/meminfo)
        _bc_target_gib=${{BINDCRAFT_GPU_GIB:-24}}
        XLA_PYTHON_CLIENT_MEM_FRACTION=$(awk -v t="$_bc_target_gib" -v p="$_bc_pool_gib" \
            'BEGIN{{ if (p <= 0) {{ print "0.200"; exit }} f = t/p; if (f > 0.5) f = 0.5; printf "%.3f", f }}')
        export XLA_PYTHON_CLIENT_MEM_FRACTION
    fi
    # First AF2 compile is ~500 s (Triton autotuning), ~177 s once cached. Key the
    # cache per card: a compiled executable is not portable between GPU models.
    JAX_COMPILATION_CACHE_DIR="${{HOME}}/.cache/jax_bindcraft_$(uname -m)"
    export JAX_COMPILATION_CACHE_DIR
    echo "  aarch64: XLA fraction ${{XLA_PYTHON_CLIENT_MEM_FRACTION:-unset}}, jax compile cache $JAX_COMPILATION_CACHE_DIR"
fi

mkdir -p "$SETTINGS_DIR"
"""
        + settings_block
        + f"""
cd "$BINDCRAFT_DIR"

echo "=== Running BindCraft for {cfg["name"]} ==="
echo "  Settings persisted: $SETTINGS_DIR/settings.json"
python -u ./bindcraft.py \\
    --settings "$SETTINGS" \\
    --filters  "$FILTERS" \\
    --advanced "$ADVANCED"
"""
    )
    path.write_text(content)
    path.chmod(0o755)


def write_run_boltzgen(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    conda_base = str(CONDA_BASE) if CONDA_BASE else ""
    bindmaster_dir = str(BINDMASTER_DIR)
    name = cfg["name"]
    target_seq = cfg.get("target_sequence", "")
    chains_str = cfg.get("chains", "A")
    hotspots_str = cfg.get("hotspots", "") or ""

    settings_block = _settings_json_block(
        tool="boltzgen",
        settings_dir_var="SETTINGS_DIR",
        conda_env="BoltzGen",
        version_dict_inner="""
    "bindmaster_git_sha": "$GIT_SHA",
    "bindmaster_git_branch": "$GIT_BRANCH",
    "boltzgen_repo_git_sha": "$BOLTZGEN_SHA\"""",
        target_dict_inner=f"""
    "name": "{name}",
    "pdb": "{cfg["target_pdb"]}",
    "sequence": "{target_seq}",
    "length": {len(target_seq)},
    "chains": "{chains_str}",
    "hotspots": "{hotspots_str}\"""",
        design_params_inner=f"""
    "mode": "{cfg.get("boltzgen_mode", "protein")}",
    "protocol": "protein-anything",
    "num_designs": {boltzgen_intermediate(cfg)},
    "budget": {boltzgen_budget(cfg)},
    "min_binder_length": {cfg.get("boltzgen_min_length", cfg["min_length"])},
    "max_binder_length": {cfg.get("boltzgen_max_length", cfg["max_length"])},
    "use_kernels": false,
    "config_yaml": "$CONFIG\"""",
        extra_env_inner=f'\nBOLTZGEN_SHA=$(git -C "{BOLTZGEN_DIR}" rev-parse HEAD 2>/dev/null || echo "unknown")',
    )

    content = (
        f"""\
#!/usr/bin/env bash
# Run BoltzGen for {cfg["name"]}
# Generated by BindMaster Configurator
set -euo pipefail

CONFIG="{run_dir}/boltzgen/config.yaml"
SETTINGS_DIR="{run_dir}/boltzgen"
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
    # shellcheck disable=SC1090
    [[ -f "$_conda_sh" ]] && {{ source "$_conda_sh"; _conda_found=true; break; }}
done
[[ "$_conda_found" == true ]] || {{ echo "ERROR: conda not found — install Miniconda or Miniforge first." >&2; exit 1; }}
conda activate BoltzGen
set -u

# aarch64/Blackwell: set CUDA arch for Triton JIT compilation
if [[ "$(uname -m)" == "aarch64" ]]; then
    export TORCH_CUDA_ARCH_LIST="12.0"
fi

mkdir -p "$SETTINGS_DIR"
"""
        + settings_block
        + f"""
echo "=== Running BoltzGen for {cfg["name"]} ==="
echo "  Settings persisted: $SETTINGS_DIR/settings.json"
"$CONDA_PREFIX/bin/boltzgen" run "$CONFIG" \\
    --output "$OUTPUT_DIR" \\
    --protocol protein-anything \\
    --num_designs {boltzgen_intermediate(cfg)} \\
    --budget {boltzgen_budget(cfg)} \\
    --use_kernels false
"""
    )
    path.write_text(content)
    path.chmod(0o755)


def write_run_mosaic(path: Path, cfg: dict):
    run_dir = cfg["run_dir"]
    mosaic_python = MOSAIC_VENV / "bin" / "python"
    name = cfg["name"]
    target_seq = cfg.get("target_sequence", "")
    hotspots_str = cfg.get("mosaic_hotspots", "") or cfg.get("hotspots", "") or ""

    settings_block = _settings_json_block(
        tool="mosaic",
        settings_dir_var="MOSAIC_DIR",
        conda_env="(uv venv: Mosaic/.venv)",
        version_dict_inner="""
    "bindmaster_git_sha": "$GIT_SHA",
    "bindmaster_git_branch": "$GIT_BRANCH",
    "mosaic_repo_git_sha": "$MOSAIC_SHA\"""",
        target_dict_inner=f"""
    "name": "{name}",
    "pdb": "{cfg.get("target_pdb", "")}",
    "sequence": "{target_seq}",
    "length": {len(target_seq)},
    "chains": "{cfg.get("chains", "A")}",
    "hotspots": "{hotspots_str}\"""",
        design_params_inner=f"""
    "n_designs_per_length": {cfg.get("mosaic_n_designs", 100)},
    "top_k": {cfg.get("mosaic_top_k", min(5, cfg["n_designs"]))},
    "min_binder_length": {cfg.get("mosaic_min_length", cfg["min_length"])},
    "max_binder_length": {cfg.get("mosaic_max_length", cfg["max_length"])},
    "length_step": {cfg.get("mosaic_length_step", 5)},
    "epitope_idx": {json.dumps(hotspots_to_epitope_idx(cfg))}""",
        # Mosaic runs from a uv venv, not conda: `python` may not be on PATH at all,
        # so resolve the interpreter version from the venv interpreter the script uses.
        extra_env_inner=(
            f'\nMOSAIC_SHA=$(git -C "{MOSAIC_DIR}" rev-parse HEAD 2>/dev/null || echo "unknown")'
            '\nPY_VER=$("$MOSAIC_PYTHON" -c \'import sys;print(".".join(map(str,sys.version_info[:3])))\''
            ' 2>/dev/null || echo "unknown")'
        ),
    )

    content = (
        f"""\
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

mkdir -p "$MOSAIC_DIR"
"""
        + settings_block
        + f"""
echo "=== Running Mosaic for {cfg["name"]} ==="
echo "  Settings persisted: $MOSAIC_DIR/settings.json"
cd "$MOSAIC_DIR"
"$MOSAIC_PYTHON" hallucinate.py
"""
    )
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


def _settings_json_block(
    *,
    tool: str,
    settings_dir_var: str,
    conda_env: str,
    version_dict_inner: str,
    target_dict_inner: str,
    design_params_inner: str,
    extra_env_inner: str = "",
    gpu_id_var: str = "0",
) -> str:
    """Return a bash snippet that writes a self-describing settings.json before the design step.

    Implements the convention from CLAUDE.md > Conventions > "Per-run settings.json".
    Caller must have already activated the conda env (so `python` is on PATH and
    `git -C "{BINDMASTER_DIR}" rev-parse HEAD` works).

    Parameters are bash snippets (not full strings) because each tool's version /
    target / design_params dicts have tool-specific keys.  The block resolves
    GIT_SHA / GIT_BRANCH / GPU_NAME / GPU_MEM / PY_VER as bash variables which
    can be referenced inside the inner strings.

    Args:
        tool: Tool name to record under the "tool" key.
        settings_dir_var: Bash variable name (without $) holding the directory
            where settings.json should be written, e.g. "RUN_DIR" → "$RUN_DIR/settings.json".
        conda_env: Name of the conda env, recorded under env.conda_env.
        version_dict_inner: Inner JSON for the "version" object (no surrounding braces).
        target_dict_inner: Inner JSON for the "target" object.
        design_params_inner: Inner JSON for the "design_params" object.
        extra_env_inner: Optional extra bash setup before the heredoc (e.g. tool repo SHA).
        gpu_id_var: GPU index for nvidia-smi -i (default "0").
    """
    return f"""
# ── Persist exact run settings to ${settings_dir_var}/settings.json ─────────
# Convention (CLAUDE.md "Per-run settings.json"): every tool run writes a
# self-describing settings.json into its output subdir BEFORE launching the
# design step, so future sessions can audit `cat <tool>/settings.json` instead
# of grepping run.log.
GIT_SHA=$(git -C "{BINDMASTER_DIR}" rev-parse HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git -C "{BINDMASTER_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
# `|| echo` is load-bearing: every generated script runs under `set -euo pipefail`, and
# with pipefail a failing nvidia-smi in a command substitution kills the script (exit 127)
# BEFORE the design step. GIT_SHA/GIT_BRANCH/PY_VER above are already guarded this way;
# these two were not, so any host without nvidia-smi on PATH — a CPU login node, a
# container without the NVIDIA runtime, or a wrong --gpu-id — died in the provenance
# block that exists to improve reproducibility.
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader -i {gpu_id_var} 2>/dev/null | head -1 || echo "unknown")
GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i {gpu_id_var} 2>/dev/null | head -1 || echo 0)
# GB10 (DGX Spark) answers this query SUCCESSFULLY and returns the string "[N/A]",
# so the `|| echo 0` above never fires. gpu_memory_mib is the one unquoted value in
# the JSON, so that string lands bare and settings.json stops parsing — on the very
# machine that orchestrates the fleet. Keep the reading only when it is a number.
GPU_MEM=$(printf '%s' "$GPU_MEM" | grep -E '^[0-9]+$' || echo 0)
PY_VER=$(python -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null || echo "unknown"){extra_env_inner}
cat > "${settings_dir_var}/settings.json" <<SETTINGS_JSON_EOF
{{
  "tool": "{tool}",
  "started_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "version": {{{version_dict_inner}
  }},
  "target": {{{target_dict_inner}
  }},
  "design_params": {{{design_params_inner}
  }},
  "env": {{
    "conda_env": "{conda_env}",
    "python": "$PY_VER",
    "gpu_id": {gpu_id_var},
    "gpu_name": "$GPU_NAME",
    "gpu_memory_mib": $GPU_MEM
  }}
}}
SETTINGS_JSON_EOF
"""


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
    # shellcheck disable=SC1090
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
    # Non-zero for the same reason as the Proteina-Complexa harvest: a design step
    # that yields no designs must not report success, or the tool vanishes from the
    # pool with nothing but a warning buried in the log.
    print('ERROR: No binder sequences extracted', file=sys.stderr)
    sys.exit(1)

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
    name = cfg["name"]
    target_seq = cfg.get("target_sequence", "")
    preset = cfg.get("pxdesign_preset", "preview")
    n_samples = cfg.get("pxdesign_n_samples", 1000)
    length_scan = cfg.get("pxdesign_length_scan", False)
    top_per_length = int(cfg.get("pxdesign_top_per_length", 0) or 0)

    header = _pxdesign_conda_header(cfg)

    # Build settings.json design_params (mode-specific).
    if length_scan:
        min_len = cfg.get("pxdesign_min_length", 40)
        max_len = cfg.get("pxdesign_max_length", 140)
        step = cfg.get("pxdesign_length_step", 20)
        chains_str = cfg.get("pxdesign_chains", cfg.get("chains", "A"))
        hotspots_str = cfg.get("pxdesign_hotspots", "") or cfg.get("hotspots", "") or ""
        params_inner = f"""
    "preset": "{preset}",
    "length_scan": true,
    "min_length": {min_len},
    "max_length": {max_len},
    "length_step": {step},
    "n_samples_per_length": {n_samples},
    "top_per_length": {top_per_length},
    "chains": "{chains_str}",
    "hotspots": "{hotspots_str}\""""
    else:
        params_inner = f"""
    "preset": "{preset}",
    "length_scan": false,
    "n_samples": {n_samples},
    "binder_length": {cfg.get("pxdesign_binder_length", "null")}"""

    settings_block = _settings_json_block(
        tool="pxdesign",
        settings_dir_var="SETTINGS_DIR",
        conda_env="bindmaster_pxdesign",
        version_dict_inner="""
    "bindmaster_git_sha": "$GIT_SHA",
    "bindmaster_git_branch": "$GIT_BRANCH",
    "pxdesign_repo_git_sha": "$PXDESIGN_SHA\"""",
        target_dict_inner=f"""
    "name": "{name}",
    "sequence": "{target_seq}",
    "length": {len(target_seq)}""",
        design_params_inner=params_inner,
        extra_env_inner=f'\nPXDESIGN_SHA=$(git -C "{PXDESIGN_DIR}" rev-parse HEAD 2>/dev/null || echo "unknown")',
    )

    if length_scan:
        target_pdb = cfg["target_pdb"]
        chain_ids = [c.strip() for c in chains_str.split(",")]
        hotspot_list = parse_hotspots(hotspots_str) if hotspots_str.strip() else []

        # Build YAML chain lines
        chain_lines = ""
        for cid in chain_ids:
            if hotspot_list:
                hs = ", ".join(str(h) for h in hotspot_list)
                chain_lines += f"    {cid}:\\n      hotspots: [{hs}]\\n"
            else:
                chain_lines += f"    {cid}: all\\n"

        body_setup = f"""
RUN_DIR="{run_dir}"
TARGET_PDB="{target_pdb}"
SETTINGS_DIR="$RUN_DIR/pxdesign"
mkdir -p "$SETTINGS_DIR"
"""
        body_workload = f"""
MIN_LENGTH={min_len}
MAX_LENGTH={max_len}
LENGTH_STEP={step}
N_SAMPLES={n_samples}

echo "=== PXDesign Length Scan for {name} ==="
echo "  Lengths: ${{MIN_LENGTH}} to ${{MAX_LENGTH}} (step ${{LENGTH_STEP}})"
echo "  Samples per length: ${{N_SAMPLES}}"
echo "  Settings persisted: $SETTINGS_DIR/settings.json"

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
        content = header + body_setup + settings_block + body_workload
    else:
        body_setup = f"""
RUN_DIR="{run_dir}"
SETTINGS_DIR="$RUN_DIR/pxdesign"
INPUT_YAML="$RUN_DIR/pxdesign/input.yaml"
OUTPUT_DIR="$RUN_DIR/pxdesign/outputs"
mkdir -p "$SETTINGS_DIR"
"""
        body_workload = f"""
echo "=== Running PXDesign for {name} ==="
echo "  Settings persisted: $SETTINGS_DIR/settings.json"

pxdesign pipeline \\
    --preset {preset} \\
    --N_sample {n_samples} \\
    --dtype bf16 \\
    -i "$INPUT_YAML" \\
    -o "$OUTPUT_DIR"
"""
        content = header + body_setup + settings_block + body_workload

    # Append sequence extraction step (common to both modes)
    content += _pxdesign_sequence_collector(run_dir, top_per_length=top_per_length)

    path.write_text(content)
    path.chmod(0o755)


def _run_all_order(tools_enabled: dict) -> str:
    """The steps run_all.sh will actually execute, in order, for the header comment."""
    labels = [label for _key, _script, label, _subdir in enabled_tools(tools_enabled)]
    if tools_enabled.get("evaluator"):
        labels.append("Evaluator")
    return " → ".join(labels) if labels else "(nothing enabled)"


def write_run_all(path: Path, cfg: dict, tools_enabled: dict):
    run_dir = cfg["run_dir"]
    lines = [
        "#!/usr/bin/env bash",
        # The order line used to name all seven tools regardless of what was enabled,
        # so a two-tool run advertised five tools it would never start.
        f"# Run all enabled tools for {cfg['name']} in order: {_run_all_order(tools_enabled)}",
        "# Generated by BindMaster Configurator",
        "#",
        "# Deliberately NOT `set -e`, and no `exit 1` per step. These tools run for hours",
        "# to days each and fail independently — a BoltzGen OOM at hour 2 used to abort the",
        "# script, so RFD3 and Protein-Hunter never started and the Evaluator never ran on",
        "# the designs that HAD finished. Each step is now isolated: a failure is recorded,",
        "# the rest continue, the Evaluator reports on whatever completed, and the script",
        "# exits non-zero at the end naming every step that failed.",
        "set -uo pipefail",
        "",
        f'RUN_DIR="{run_dir}"',
        "FAILED=()",
        "",
        "run_tool() {",
        '    local label="$1" script="$2" output="$3"',
        '    echo "=== Step: $label ==="',
        '    if ! "$script"; then',
        '        echo "WARNING: $label exited non-zero — continuing with the remaining tools." >&2',
        '        FAILED+=("$label")',
        "        return",
        "    fi",
        "    # $output is a directory for some tools and a CSV for others. `ls -A` on a",
        "    # file prints its name, so a 0-byte CSV used to count as real output.",
        '    if [ -d "$output" ]; then',
        '        [ -n "$(ls -A "$output" 2>/dev/null)" ] && return',
        '    elif [ -s "$output" ]; then',
        "        return",
        "    fi",
        '    echo "WARNING: $label produced no output in $output — continuing." >&2',
        '    FAILED+=("$label")',
        "}",
        "",
    ]

    if tools_enabled.get("mosaic"):
        lines += [
            "# Mosaic runs unattended like every other tool. This block used to SKIP it with a",
            '# "needs interactive input" warning, so the documented one-command path silently',
            "# ran 6 of 7 tools — in exactly the context where nobody is watching. It needs no",
            "# stdin: run_mosaic.sh runs mosaic/hallucinate.py, whose every parameter (target",
            "# sequence and PDB, N_DESIGNS, TOP_K, MIN/MAX_LENGTH, LENGTH_STEP, EPITOPE_IDX) is",
            "# injected by write_mosaic_hallucinate at generation time. There is no input(),",
            "# no prompt and no stdin read anywhere in it or in the template it comes from.",
            "# Re-running this script is cheap for Mosaic: a finished designs.csv is reused.",
            # The banner lives in the skip branch only: run_tool() echoes
            # "=== Step: $label ===" itself, so echoing it here too printed the Mosaic
            # header twice in an unattended log while the other six printed it once.
            'if [[ -f "$RUN_DIR/mosaic/designs.csv" ]]; then',
            '    echo "=== Step: Mosaic ==="',
            '    echo "  Mosaic designs.csv found — already done, skipping."',
            "else",
            '    run_tool "Mosaic" "$RUN_DIR/run_mosaic.sh" "$RUN_DIR/mosaic/designs.csv"',
            "fi",
            "",
        ]

    if tools_enabled.get("boltzgen"):
        lines += [
            'run_tool "BoltzGen" "$RUN_DIR/run_boltzgen.sh" "$RUN_DIR/boltzgen/outputs"',
            "",
        ]

    if tools_enabled.get("bindcraft"):
        lines += [
            'run_tool "BindCraft" "$RUN_DIR/run_bindcraft.sh" "$RUN_DIR/bindcraft/outputs"',
            "",
        ]

    if tools_enabled.get("pxdesign_local"):
        lines += [
            # In length-scan mode the script writes per-length outputs_lenN/ dirs
            # and aggregates into sequences.csv — pxdesign/outputs/ never exists.
            # Check the unified CSV like the other tools do.
            'run_tool "PXDesign" "$RUN_DIR/run_pxdesign.sh" "$RUN_DIR/pxdesign/sequences.csv"',
            "",
        ]

    if tools_enabled.get("proteina_complexa"):
        lines += [
            'run_tool "Proteina-Complexa" "$RUN_DIR/run_proteina_complexa.sh" '
            '"$RUN_DIR/proteina_complexa/sequences.csv"',
            "",
        ]

    if tools_enabled.get("rfd3"):
        lines += [
            'run_tool "RFD3" "$RUN_DIR/run_rfd3.sh" "$RUN_DIR/rfd3/sequences.csv"',
            "",
        ]

    if tools_enabled.get("protein_hunter"):
        lines += [
            'run_tool "Protein-Hunter" "$RUN_DIR/run_protein_hunter.sh" "$RUN_DIR/protein_hunter/sequences.csv"',
            "",
        ]

    if tools_enabled.get("evaluator"):
        lines += [
            'echo "=== Step: Evaluator ==="',
            "# A tool that failed leaves an empty output dir, and `binder-compare extract`",
            "# treats that as an error so a mistyped path cannot silently shrink the pool.",
            "# That is right when run_evaluate.sh is invoked by hand; here we already know",
            "# which tool died and want the report on the ones that finished. An entirely",
            "# empty pool still errors out inside extract.",
            "if [ ${#FAILED[@]} -gt 0 ]; then",
            "    export BINDMASTER_ALLOW_EMPTY=1",
            "fi",
            'if ! "$RUN_DIR/run_evaluate.sh"; then',
            '    FAILED+=("Evaluator")',
            "fi",
            "",
        ]

    lines += [
        'echo ""',
        "if [ ${#FAILED[@]} -gt 0 ]; then",
        '    echo "=== Pipeline finished, ${#FAILED[@]} step(s) FAILED: ${FAILED[*]} ===" >&2',
        "    exit 1",
        "fi",
        'echo "=== Pipeline complete! ==="',
    ]

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

    name = cfg["name"]
    target_seq = cfg.get("target_sequence", "")

    settings_block = _settings_json_block(
        tool="proteina-complexa",
        settings_dir_var="SETTINGS_DIR",
        conda_env="(uv venv: Proteina-Complexa/.venv)",
        version_dict_inner="""
    "bindmaster_git_sha": "$GIT_SHA",
    "bindmaster_git_branch": "$GIT_BRANCH",
    "complexa_repo_git_sha": "$COMPLEXA_SHA\"""",
        target_dict_inner=f"""
    "name": "{name}",
    "pdb": "{target_pdb}",
    "sequence": "{target_seq}",
    "length": {len(target_seq)},
    "chains": "{chains_str}",
    "hotspots": "{hotspots_str}\"""",
        design_params_inner=f"""
    "search_algorithm": "{search_algo}",
    "replicas": {replicas},
    "min_binder_length": {min_len},
    "max_binder_length": {max_len},
    "filter_samples_limit": {n_designs},
    "mcts_n_simulations": {mcts_n_simulations if mcts_n_simulations is not None else "null"},
    "nres_nsamples": {nres_nsamples if nres_nsamples is not None else "null"},
    "refinement": {f'"{refinement}"' if refinement else "null"}""",
        extra_env_inner=f'\nCOMPLEXA_SHA=$(git -C "{PROTEINA_COMPLEXA_DIR}" rev-parse HEAD 2>/dev/null || echo "unknown")',
    )

    content = (
        f"""\
#!/usr/bin/env bash
# Run Proteina-Complexa for {name}
# Generated by BindMaster Configurator
set -euo pipefail

PROTEINA_COMPLEXA_DIR="{PROTEINA_COMPLEXA_DIR}"
RUN_DIR="{run_dir}"
SETTINGS_DIR="$RUN_DIR/proteina_complexa"
mkdir -p "$SETTINGS_DIR"

# Activate Proteina-Complexa uv venv + initialize env.sh.
# Without `complexa init uv` + `source env.sh`, every CLI call dies on
# "Environment not initialized. Run: complexa init <uv|docker>; source env.sh".
# `complexa init` is idempotent (`--force` regenerates env.sh from .env).
source "${{PROTEINA_COMPLEXA_DIR}}/.venv/bin/activate"
cd "${{PROTEINA_COMPLEXA_DIR}}"
if [[ ! -f env.sh ]]; then
    complexa init uv --force
fi
# shellcheck disable=SC1091
source env.sh
"""
        + settings_block
        + f"""
echo "=== Running Proteina-Complexa for {name} ==="
echo "  Settings persisted: $SETTINGS_DIR/settings.json"

# Write custom target definition
TARGET_YAML="$RUN_DIR/proteina_complexa/target_bindmaster.yaml"
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
# The harvest goes through a quoted heredoc, never an inline -c string. Inside a
# double-quoted shell word a quote character ends the string and a backquoted word
# runs as a command, and this program comments contain both -- 9 and 12 of them,
# one reading like an uninstall command. The generated script failed bash -n
# outright, so the step died before Complexa ever ran. Quoting the heredoc
# delimiter makes bash pass the body through untouched; the single value that does
# need expanding is handed over as an environment variable instead.
RUN_DIR="$RUN_DIR" python3 - <<'PY'
import csv, glob, os, shutil, sys
from pathlib import Path

pc_dir = Path(os.environ["RUN_DIR"]) / "proteina_complexa"
run_name = '{cfg["name"]}'

# Find the directory Complexa actually wrote its designs into.
#
# This used to try only `outputs/<run_name>`, then rglob for a directory literally
# named `evaluation_results`. At PROTEINA_COMPLEXA_COMMIT neither exists: the design
# pipeline writes to `inference/<config_name>_<task_name>_<run_name>/`, holding
# top_samples_*.csv plus one subdirectory per design with its .pdb. So the harvest
# found nothing, printed a warning, and exited 0 — the step reported "design
# complete" with no sequences.csv, and the Evaluator then logged
# "Proteina-Complexa: no CSV found" and silently dropped the tool from the pool.
# Search `inference/` first and keep the old paths as fallbacks for other revisions.
#
# Scan EVERY candidate, not just the first that exists. The two trees hold different
# things: `inference/<config>_<task>_<run>/` has one subdirectory per design with its
# .pdb but no sequence-bearing CSV, while `evaluation_results/<config>_<task>/` has
# the metrics. Committing to the first existing directory reached the PDBs and never
# the metrics, so the harvest always fell through to the chain-B fallback below and
# emitted designs with no iPTM / pLDDT / scRMSD -- measured on PD-L1 2026-10-28, where
# Proteina-Complexa carried 2 native metric columns against 4-9 for every other tool.
rows = []
search_dirs = []
for base in (Path('inference'), Path('outputs')):
    if base.is_dir():
        search_dirs += [p for p in sorted(base.iterdir()) if p.is_dir() and run_name in p.name]
# The run name sits in the CHILD of `evaluation_results`
# (evaluation_results/<config>_<task>/), not in that directory's own path, so the old
# `run_name in str(p)` filter on the rglob hit rejected every match and this candidate
# could never contribute. Descend one level, and keep the parent as a fallback.
for _ev in sorted(Path('.').rglob('evaluation_results')):
    if not _ev.is_dir():
        continue
    _subs = [p for p in sorted(_ev.iterdir()) if p.is_dir() and run_name in p.name]
    search_dirs += _subs or [_ev]
if (Path('outputs') / run_name).is_dir():
    search_dirs.append(Path('outputs') / run_name)
_seen_dirs = set()
search_dirs = [p for p in search_dirs if p.resolve() not in _seen_dirs and not _seen_dirs.add(p.resolve())]
for p in search_dirs:
    print('  Reading Complexa outputs from ' + str(p))

AA3TO1 = {{
    'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E',
    'GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F',
    'PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V','MSE':'M',
}}

def chain_b_seq(pdb_path):
    '''Binder sequence from a Complexa complex PDB (target = A, binder = B).'''
    seen = {{}}
    with open(pdb_path) as f:
        for line in f:
            if line[:4] != 'ATOM' or line[12:16].strip() != 'CA':
                continue
            if line[21].strip().upper() != 'B':
                continue
            key = (line[22:26].strip(), line[26].strip())
            if key not in seen:
                seen[key] = AA3TO1.get(line[17:20].strip().upper(), 'X')
    return ''.join(seen.values())

# Map binder sequence -> the PDB that holds it. The metrics CSVs carry no design name
# column, so without this the design_id degrades to '<csv stem>_<row index>' and the
# sequence cannot be traced to a structure -- which is the whole point of keeping both.
pdb_by_seq = {{}}
for _d in search_dirs:
    for _p in sorted(_d.rglob('*.pdb')):
        try:
            _s = chain_b_seq(_p)
        except Exception:
            continue
        if _s and set(_s) != {{'X'}} and _s not in pdb_by_seq:
            pdb_by_seq[_s] = _p

# Strategy 1: metrics CSVs. Complexa names the binder column `binder_sequence`;
# reading only `sequence` was the other half of the same bug -- pointed straight at
# evaluation_results, Strategy 1 still matched nothing and fell through.
SEQ_COLS = ('binder_sequence', 'sequence')
_seen_seqs = set()
for _d in search_dirs:
    for csv_path in sorted(_d.rglob('*.csv')):
        try:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                col = next((c for c in SEQ_COLS if reader.fieldnames and c in reader.fieldnames), None)
                if not col:
                    continue
                for i, r in enumerate(reader):
                    seq = (r.get(col) or '').strip()
                    if not seq or set(seq) == {{'X'}}:
                        continue
                    # The same design appears in several of Complexa's CSVs
                    # (RAW_*_combined and all_successes_*); keep the first.
                    if seq in _seen_seqs:
                        continue
                    _seen_seqs.add(seq)
                    _hit = pdb_by_seq.get(seq)
                    name = r.get('name') or r.get('sample_name') or r.get('sample_id') \
                        or (_hit.stem if _hit is not None else csv_path.stem + '_' + str(i))
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
                        'structure': (_hit.name if _hit is not None else ''),
                        'source': 'proteina_complexa',
                    }})
        except Exception as e:
            print(f'  Warning: could not parse {{csv_path}}: {{e}}', file=sys.stderr)
if rows:
    _linked = sum(1 for r in rows if r.get('structure'))
    print(f'  Found {{len(rows)}} sequences with metrics from Complexa CSVs '
          f'({{_linked}} linked to a structure)')

# Strategy 2: Fall back to PDB sequence extraction
if not rows:
    for pdb_path, seq in sorted((p, s) for s, p in pdb_by_seq.items()):
        try:
            if seq and set(seq) != {{'X'}}:
                rows.append({{
                    'design_id': f'complexa_{{pdb_path.stem}}',
                    'sequence': seq,
                    'length': len(seq),
                    'structure': pdb_path.name,
                    'source': 'proteina_complexa',
                }})
        except Exception:
            pass
    if rows:
        print(f'  Found {{len(rows)}} sequences from PDB files (fallback)')

if not rows:
    # Exit NON-ZERO. This was `sys.exit(0)`, so a run that generated backbones but
    # harvested nothing printed one warning and reported success: run_all.sh counted
    # the step as passed, the Evaluator logged "no CSV found" and dropped the tool,
    # and the campaign report simply had no Proteina-Complexa column. A design step
    # that produces no designs is a failure, and run_all.sh is built to carry on
    # past a failed step and name it at the end.
    print('ERROR: No binder sequences extracted from Proteina-Complexa', file=sys.stderr)
    print('       Looked under: ' + ', '.join(str(p) for p in search_dirs), file=sys.stderr)
    print('       If Complexa wrote elsewhere, the harvest globs in this script need updating.', file=sys.stderr)
    sys.exit(1)

# Copy the raw outputs into the run directory. Complexa writes its PDBs and metrics
# CSVs inside its own clone (Proteina-Complexa/inference/, .../evaluation_results/),
# which is gitignored and deleted by `bindmaster install --uninstall`. Every other
# tool keeps its structures under runs/<name>/<tool>/; this one left the run holding
# sequences.csv and nothing else -- 3 files against 34-639 for the other six -- so an
# archived run could not be re-reported or inspected.
struct_dir = pc_dir / 'structures'
raw_dir = pc_dir / 'raw'
struct_dir.mkdir(parents=True, exist_ok=True)
raw_dir.mkdir(parents=True, exist_ok=True)
n_pdb = n_csv = 0
for _d in search_dirs:
    for src in sorted(_d.rglob('*.pdb')):
        dest = struct_dir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
            n_pdb += 1
    for src in sorted(_d.rglob('*.csv')):
        dest = raw_dir / (_d.name + '__' + src.name)
        if not dest.exists():
            shutil.copy2(src, dest)
            n_csv += 1
print('  -> copied ' + str(n_pdb) + ' structure(s) and ' + str(n_csv) + ' raw CSV(s) into ' + str(pc_dir))

out_csv = pc_dir / 'sequences.csv'
with open(out_csv, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f'  -> {{len(rows)}} binder sequences written to {{out_csv}}')
PY
"""
    )

    path.write_text(content)
    path.chmod(0o755)


def rfd3_target_contig(target_pdb: Path, chain_id: str, target_len: int) -> str:
    """The preserved-target half of an RFD3 contig, in the structure's OWN numbering.

    RFD3 resolves contig components against the atom array's author numbering, so a
    hardcoded "A1-<len>" only works when the file happens to start at residue 1. It
    usually does not: the prepared PDL1 target runs A17-A134, and `A1-118` aborted the
    whole run with `[component=A1] Residue A1 not found in atom array.` — a hard
    ValidationError before the first diffusion step, so no partial output either.

    Numbering gaps (unmodelled loops) get their own range, because a single span across
    a gap names residues that are equally absent from the atom array.

    Falls back to "<chain>1-<target_len>" only when the file cannot be read at all;
    that is the historical behaviour and is right for a 1-based file.
    """
    try:
        lines = target_pdb.read_text(errors="replace").splitlines()
    except OSError as exc:
        print_warn(f"  Could not read {target_pdb} for the RFD3 contig ({exc}) — assuming 1-based numbering.")
        return f"{chain_id}1-{target_len}"

    keys, _seq = _pdb_chain_ca_residues(lines, chain_id)
    if not keys:
        print_warn(f"  No CA atoms for chain {chain_id} in {target_pdb.name} — assuming 1-based numbering.")
        return f"{chain_id}1-{target_len}"

    if any(icode for _resseq, icode in keys):
        # A numeric range cannot address 52 vs 52A, and RFD3's contig grammar has no
        # syntax for insertion codes. Say so rather than emit a range that silently
        # covers the wrong residue count.
        print_warn(f"  Chain {chain_id} has insertion codes — the RFD3 contig ignores them; check its residue count.")

    nums = sorted({int(resseq) for resseq, _icode in keys if resseq.lstrip("-").isdigit()})
    if not nums:
        return f"{chain_id}1-{target_len}"

    spans: list[tuple[int, int]] = [(nums[0], nums[0])]
    for n in nums[1:]:
        if n == spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], n)
        else:
            spans.append((n, n))
    if len(spans) > 1:
        print_warn(f"  Chain {chain_id} numbering has {len(spans) - 1} gap(s) — contig emitted as {len(spans)} ranges.")
    return ",".join(f"{chain_id}{lo}-{hi}" for lo, hi in spans)


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
    batch_size = cfg.get("rfd3_batch_size", 10)
    # Round n_batches up so at least n_designs samples are produced.
    n_batches = max(1, -(-n_designs // batch_size))
    diffusion_steps = cfg.get("rfd3_diffusion_steps", 200)
    step_scale = cfg.get("rfd3_step_scale", 1.5)
    mpnn_samples = cfg.get("rfd3_mpnn_samples", 5)
    # ProteinMPNN's field-default T=0.1 with no bias collapses RFD3 backbones to
    # ~50% alanine — sequences that gate and tier normally (no engine in the stack
    # penalises low-complexity sequence) but are not viable protein. Measured on the
    # ApoE4-isoform pool; the fix below brings alanine 0.50 -> 0.102 and composition
    # entropy H to 2.59, matching the pool that produced real selectives.
    # NOTE the pair moves together: raising T without the bias does not fix it, and
    # biasing off ALA alone on *helical-bundle* backbones can relocate the collapse to
    # poly-Glu (seen on PXDesign, where GLU/ARG also need -0.6). Tune per backbone
    # source, and check composition entropy afterwards, not alanine alone.
    mpnn_temperature = cfg.get("rfd3_mpnn_temperature", 0.25)
    mpnn_bias = cfg.get("rfd3_mpnn_bias", {"ALA": -1.5})
    if isinstance(mpnn_bias, str):
        try:
            mpnn_bias = json.loads(mpnn_bias) if mpnn_bias.strip() else {}
        except ValueError:
            print_fail(f"rfd3_mpnn_bias is not valid JSON: {mpnn_bias!r}")
            sys.exit(1)
    if mpnn_bias and not isinstance(mpnn_bias, dict):
        print_fail(f"rfd3_mpnn_bias must be a JSON object of three-letter codes, got {mpnn_bias!r}")
        sys.exit(1)
    # mpnn takes the bias as a JSON object argument; empty dict = pass no flag.
    mpnn_bias_flag = f"--bias '{json.dumps(mpnn_bias)}' \\\n        " if mpnn_bias else ""
    # Recorded in settings.json so a future session can tell a biased run from an
    # unbiased one without re-reading the script (CLAUDE.md per-run settings.json).
    mpnn_bias_json = json.dumps(mpnn_bias or {})

    hotspots_str = cfg.get("rfd3_hotspots") or cfg.get("hotspots", "") or ""
    hotspot_list = parse_hotspots(hotspots_str) if hotspots_str.strip() else []
    # Build select_hotspots as a comma-separated component string ("A15,A18,...")
    # rfd3's parsing.canonicalize_() will treat each as a token-level hotspot.
    select_hotspots_str = ",".join(f"{primary_chain}{r}" for r in hotspot_list) if hotspot_list else ""

    # RFD3 REQUIRES hotspots. Refuse to generate a run without them.
    #
    # Two wrong answers were tried here before this one:
    #
    #  1. Emit `infer_ori_strategy: hotspots` unconditionally, with the comment
    #     "COM falls back when select_hotspots is empty". That comment was false --
    #     rfd3/utils/inference.py::infer_ori_from_hotspots opens with
    #     `assert "is_atom_level_hotspot" in atom_array.get_annotation_categories()`
    #     and `com` is a SEPARATE key in INFER_ORI_STRATEGIES_TO_FUNCTIONS, reached
    #     only by asking for it. With no hotspots the annotation never exists, so
    #     every run died in the dataloader (BUG-27).
    #
    #  2. Fall back to `infer_ori_strategy: com` when no hotspots are configured.
    #     That "fixed" the crash and made the output WORSE THAN USELESS: centring on
    #     the whole fixed motif's centre of mass seeds every diffused binder atom at
    #     the target's centre, so the binder nucleates inside the target and grows as
    #     an extended coil. Measured on CBG/2VDY (2026-09-16, 304 backbones lost):
    #     binder Rg 23.1 A vs 10.9 A, DSSP helix 0.27 vs 0.85, PPII 0.23 vs 0.001 --
    #     and n_chainbreaks stays 0, so EVERY downstream guard passes. Reproduced on
    #     PDL1 2026-10-27: ten 89-residue binders at Rg 16.8-19.6 A against a
    #     118-residue target at 14.0 A. See CLAUDE.md "infer_ori_strategy is
    #     LOAD-BEARING".
    #
    # A silent generator of unfoldable backbones is the worst of the three outcomes,
    # so fail here -- at configure time, before any GPU is committed -- and say what
    # to do about it. Hotspots are optional for the other six tools; this one needs
    # them, and that is a fact about RFD3, not a gap in the wizard.
    if not select_hotspots_str:
        print_fail("RFD3 needs hotspot residues and none are configured.")
        print(
            "  Without them RFD3 centres the binder on the whole target's centre of\n"
            "  mass and silently produces extended coils that pass every quality gate\n"
            "  (measured: Rg 23.1 A vs 10.9 A, helix 0.27 vs 0.85). It is not safe to\n"
            "  guess a default, so this run is refused rather than wasted.\n"
            "\n"
            "  Fix either way:\n"
            '    * set hotspots for the campaign, e.g.  "hotspots": "A56,A115,A123"\n'
            '      (or "rfd3_hotspots" to scope them to RFD3 alone), then re-run; or\n'
            '    * disable RFD3 for this campaign:  "rfd3": false  in tools_enabled.\n'
            "\n"
            "  The bindmaster-target-analyst skill proposes hotspots for a target if\n"
            "  you do not have them yet."
        )
        sys.exit(1)
    rfd3_ori_strategy = "hotspots"

    # Author numbering, read from the file RFD3 will actually load — not 1..N.
    target_contig = rfd3_target_contig(target_pdb, primary_chain, target_len)

    name = cfg["name"]

    settings_block = _settings_json_block(
        tool="rfd3",
        settings_dir_var="RFD3_DIR",
        conda_env="bindmaster_rfd3",
        version_dict_inner="""
    "bindmaster_git_sha": "$GIT_SHA",
    "bindmaster_git_branch": "$GIT_BRANCH",
    "rfd3_pkg_version": "$RFD3_VER\"""",
        target_dict_inner=f"""
    "name": "{name}",
    "pdb": "{target_pdb}",
    "sequence": "{target_seq}",
    "length": {target_len},
    "primary_chain": "{primary_chain}\"""",
        design_params_inner=f"""
    "contig": "{target_contig},/0,{min_len}-{max_len}",
    "binder_min_length": {min_len},
    "binder_max_length": {max_len},
    "n_designs": {n_designs},
    "n_batches": {n_batches},
    "diffusion_batch_size": {batch_size},
    "num_timesteps": {diffusion_steps},
    "step_scale": {step_scale},
    "low_memory_mode": true,
    "mpnn_samples": {mpnn_samples},
    "mpnn_temperature": {mpnn_temperature},
    "mpnn_bias": {mpnn_bias_json},
    "select_hotspots": "{select_hotspots_str}\"""",
        extra_env_inner='\nRFD3_VER=$(python -c \'import importlib.metadata;print(importlib.metadata.version("rfd3"))\' 2>/dev/null || echo "unknown")',
    )

    content = (
        f"""\
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
# Avoid VRAM fragmentation on 24 GB cards: with diffusion_batch_size=10 and
# low_memory_mode=true, peak live allocation is ~15 GiB but PyTorch reserves
# another ~6 GiB unallocated, pushing the next 3 GiB allocation over the cliff
# mid-run (a 24 GB RTX 3090 node OOMed on its 7th batch on the 2VDY run).
# expandable_segments lets the allocator hand back reserved-but-unallocated
# memory instead of fragmenting forever.
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
set -u
"""
        + settings_block
        + f"""
# ── Stage 1: backbone diffusion ─────────────────────────────────────────────
# Contig: target first (preserved residues), then chain break (/0), then binder
# length range. RFD3 labels the preserved chain as A and the designed chain as B.
cat > "$INPUTS_YAML" <<INPUTSEOF
{name}:
  input: $TARGET_PDB
  contig: "{target_contig},/0,{min_len}-{max_len}"
  infer_ori_strategy: {rfd3_ori_strategy}{(chr(10) + '  select_hotspots: "' + select_hotspots_str + '"') if select_hotspots_str else ""}
INPUTSEOF

echo "=== RFD3 backbone diffusion for {name} ==="
echo "  Target:        $TARGET_PDB"
echo "  Contig:        {target_contig},/0,{min_len}-{max_len}"
echo "  Hotspots:      {select_hotspots_str or "(none)"}"
echo "  Designs:       {n_designs}  (batch_size={batch_size} x n_batches={n_batches} = {batch_size * n_batches})"
echo "  Diffusion:     T={diffusion_steps}, step_scale={step_scale}"
echo "  Checkpoint:    $WEIGHTS_DIR/rfd3_latest.ckpt"
echo ""

"$CONDA_PREFIX/bin/rfd3" design \\
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
    "$CONDA_PREFIX/bin/foundry" install proteinmpnn --checkpoint-dir "$WEIGHTS_DIR"
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
    "$CONDA_PREFIX/bin/mpnn" \\
        --structure_path "$CIF" \\
        --checkpoint_path "$PROTEINMPNN_CKPT" \\
        --model_type protein_mpnn \\
        --is_legacy_weights True \\
        --out_directory "$MPNN_DIR" \\
        --name "$NAME" \\
        --designed_chains '["B"]' \\
        {mpnn_bias_flag}--temperature {mpnn_temperature} \\
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
    )
    path.write_text(content)
    path.chmod(0o755)


def write_run_protein_hunter(path: Path, cfg: dict):
    """Generate run_protein_hunter.sh — Boltz-2 protein binder design (Protein-Hunter).

    Mirrors bindmaster_examples/run_protein_hunter.sh.template (the canonical
    CALCA-validated pattern). See CLAUDE.md "Protein-Hunter / boltz_ph runtime
    gotchas" for the non-obvious bits:
      - --msa_mode accepts only "single" / "mmseqs" (NOT "single_sequence").
      - Boltz-2 cache must live at ~/.boltz with mols/ALA.pkl present;
        bootstrap with download_boltz2(cache=Path.home()/'.boltz').
      - design.py creates a {name}/ subdirectory under save_dir; canonical
        outputs are at <save_dir>/{name}/summary_high_iptm.csv and summary_all_runs.csv.
    """
    run_dir = cfg["run_dir"]
    name = cfg["name"]
    target_seq = cfg.get("target_sequence", "")
    if not target_seq:
        raise RuntimeError("Protein-Hunter needs cfg['target_sequence'] (target chain amino-acid sequence).")

    n_designs = cfg.get("protein_hunter_n_designs", cfg.get("n_designs", 50))
    min_len = cfg.get("protein_hunter_min_length", cfg.get("min_length", 60))
    max_len = cfg.get("protein_hunter_max_length", cfg.get("max_length", 150))
    num_cycles = cfg.get("protein_hunter_num_cycles", 7)
    msa_mode = cfg.get("protein_hunter_msa_mode", "single")
    iptm_thr = cfg.get("protein_hunter_iptm_threshold", 0.7)
    plddt_thr = cfg.get("protein_hunter_plddt_threshold", 0.7)
    percent_x = cfg.get("protein_hunter_percent_X", 80)
    gpu_id = cfg.get("protein_hunter_gpu_id", 0)
    contact_residues = (cfg.get("protein_hunter_contact_residues") or cfg.get("hotspots", "") or "").strip()

    contact_arg = f' --contact_residues "{contact_residues}"' if contact_residues else ""

    settings_block = _settings_json_block(
        tool="protein-hunter",
        settings_dir_var="PH_DIR_OUT",
        conda_env="bindmaster_protein_hunter",
        version_dict_inner="""
    "bindmaster_git_sha": "$GIT_SHA",
    "bindmaster_git_branch": "$GIT_BRANCH",
    "tool_repo_git_sha": "$PH_SHA\"""",
        target_dict_inner=f"""
    "name": "{name}",
    "sequence": "{target_seq}",
    "length": {len(target_seq)}""",
        design_params_inner=f"""
    "num_designs": {n_designs},
    "num_cycles": {num_cycles},
    "min_protein_length": {min_len},
    "max_protein_length": {max_len},
    "msa_mode": "{msa_mode}",
    "high_iptm_threshold": {iptm_thr},
    "high_plddt_threshold": {plddt_thr},
    "percent_X": {percent_x},
    "contact_residues": "{contact_residues}\"""",
        extra_env_inner=f'\nPH_SHA=$(git -C "{PROTEIN_HUNTER_DIR}" rev-parse HEAD 2>/dev/null || echo "unknown")',
        gpu_id_var=str(gpu_id),
    )

    content = (
        f"""\
#!/usr/bin/env bash
# Run Protein-Hunter (Boltz-2 binder design with cycle optimization) for {name}
# Generated by BindMaster Configurator (mirrors bindmaster_examples/run_protein_hunter.sh.template).
set -euo pipefail

RUN_DIR="{run_dir}"
PH_DIR="{PROTEIN_HUNTER_DIR}"
PH_DIR_OUT="$RUN_DIR/protein_hunter"
mkdir -p "$PH_DIR_OUT"

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
conda activate bindmaster_protein_hunter
set -u

# Gotcha: boltz_ph reads Boltz-2 weights + CCD library from ~/.boltz. The
# directory must contain boltz2_conf.ckpt, boltz2_aff.ckpt, AND a fully
# populated mols/ subdirectory (45 k .pkl files including ALA.pkl). If any
# canonical residue .pkl is missing, design.py aborts on startup with
# "ValueError: CCD component ALA not found!".  download_boltz2 requires the
# `cache` argument as a positional pathlib.Path — passing a str silently
# no-ops on some versions.
if [[ ! -f "$HOME/.boltz/mols/ALA.pkl" ]]; then
    echo "Bootstrapping Boltz-2 cache to ~/.boltz/ ..."
    python -c "from boltz.main import download_boltz2; from pathlib import Path; download_boltz2(cache=Path.home()/'.boltz')"
fi

cd "$PH_DIR"
"""
        + settings_block
        + f"""
echo "=== Protein-Hunter design for {name} ==="
echo "  Target seq:    {target_seq[:50]}{"..." if len(target_seq) > 50 else ""} ({len(target_seq)} aa)"
echo "  Binder length: {min_len}-{max_len}"
echo "  Designs:       {n_designs}"
echo "  Cycles:        {num_cycles}"
echo "  MSA mode:      {msa_mode}"
echo "  Contacts:      {contact_residues or "(none)"}"
echo "  iPTM thr:      {iptm_thr}"
echo "  Output:        $PH_DIR_OUT"
echo "  Settings:      $PH_DIR_OUT/settings.json"
echo ""

# Gotcha: --msa_mode accepts ONLY "single" or "mmseqs". The literal string
# "single_sequence" is NOT a valid choice and will raise argparse error
# "invalid choice: 'single_sequence' (choose from 'single', 'mmseqs')".
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
    --save_dir "$PH_DIR_OUT"{contact_arg}

# Output layout: design.py creates {{name}}/ subdir under --save_dir, so the
# canonical CSV paths are:
#   $PH_DIR_OUT/{name}/summary_high_iptm.csv  — best-of-cycle rows passing
#                                                the iPTM threshold (often
#                                                > num_designs because every
#                                                passing cycle gets a row)
#   $PH_DIR_OUT/{name}/summary_all_runs.csv   — one row per design

echo ""
echo "=== Collecting Protein-Hunter binder sequences ==="
python3 - "$PH_DIR_OUT" "$RUN_DIR/protein_hunter/sequences.csv" "{name}" <<'PYEOF'
import csv, sys
from pathlib import Path

out_dir, csv_path, run_name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
AA3TO1 = {{
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E",
    "GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F",
    "PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V","MSE":"M",
}}

rows = []

def _row(design_id, seq, **extras):
    if not seq:
        return None
    if all(c == "X" for c in seq):
        return None
    return {{
        "design_id": f"ph_{{design_id}}",
        "sequence": seq,
        "length": len(seq),
        "source": "protein_hunter",
        **extras,
    }}

# Strategy 1: prefer summary_high_iptm.csv (canonical PH "best-of-cycle" filter).
for csv_file in [out_dir / run_name / "summary_high_iptm.csv", out_dir / run_name / "summary_all_runs.csv"]:
    if csv_file.exists():
        with csv_file.open() as f:
            reader = csv.DictReader(f)
            for r in reader:
                seq_field = (r.get("best_seq") or r.get("sequence") or r.get("designed_seq") or "").strip().upper()
                if not seq_field or seq_field.lower() == "nan":
                    continue
                design_id = r.get("design_id") or r.get("name") or r.get("run_id") or f"{{csv_file.stem}}_{{len(rows)}}"
                cycle = r.get("cycle", "")
                iptm = r.get("iptm") or r.get("i_ptm") or r.get("high_iptm") or ""
                plddt = r.get("plddt") or r.get("pLDDT") or r.get("high_plddt") or ""
                row = _row(
                    design_id,
                    seq_field,
                    cycle=cycle,
                    iptm=iptm,
                    plddt=plddt,
                    csv_source=csv_file.name,
                )
                if row is not None:
                    rows.append(row)
        if rows:
            print(f"  Found {{len(rows)}} sequences in {{csv_file.name}}")
            break

# Strategy 2: fall back to FASTA glob (older boltz_ph layouts).
if not rows:
    for fasta in sorted(out_dir.rglob("*.fasta")):
        try:
            text = fasta.read_text().splitlines()
            seq_lines, header = [], None
            for line in text:
                if line.startswith(">"):
                    if seq_lines:
                        row = _row(header or fasta.stem, "".join(seq_lines))
                        if row is not None:
                            rows.append(row)
                    header = line[1:].split()[0] if len(line) > 1 else fasta.stem
                    seq_lines = []
                elif line.strip():
                    seq_lines.append(line.strip())
            if seq_lines:
                row = _row(header or fasta.stem, "".join(seq_lines))
                if row is not None:
                    rows.append(row)
        except Exception:
            pass

# Strategy 3: fall back to extracting binder sequences from PDB outputs.
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
        row = _row(pdb.stem, "".join(seen.values()))
        if row is not None:
            rows.append(row)

if not rows:
    print("WARNING: no Protein-Hunter binder sequences found", file=sys.stderr)
    sys.exit(0)

# De-duplicate by sequence (PH summary CSVs may include the same sequence
# across multiple cycles).
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
    )
    path.write_text(content)
    path.chmod(0o755)


def write_run_evaluate(path: Path, cfg: dict, tools_enabled: dict):
    """Generate run_evaluate.sh — calls Evaluator/evaluate.sh with the right paths."""
    run_dir = cfg["run_dir"]
    eval_dir = run_dir / "evaluate"
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
    if tools_enabled.get("protein_hunter"):
        design_dirs.append(("--protein-hunter", str(run_dir / "protein_hunter")))
    if tools_enabled.get("rfd3"):
        # run_rfd3.sh writes RFD3_DIR="$RUN_DIR/rfd3" (sequences.csv + sequences.fasta), and
        # write_run_all already checks "$RUN_DIR/rfd3/sequences.csv". Pointing the extractor at
        # rfd3/outputs/ handed it an empty directory, so a completed RFD3 run (23 h GPU on the
        # documented 2VDY campaign) contributed zero designs to the report, silently.
        design_dirs.append(("--rfd3", str(run_dir / "rfd3")))

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
        "    # shellcheck disable=SC1090",
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
            # Proteina-Complexa's native aatype column encodes target + binder +
            # padding, so the extractor needs the same target evaluate.sh gets below.
            f'        --target-seq "{target_seq}" \\',
            '        --output "$SEQUENCES" \\',
            # Set by run_all.sh when a design tool failed, so the tools that DID finish
            # still get evaluated. Unset (the standalone case) keeps extract strict: a
            # requested directory that yields nothing is an error, not a shrug.
            "        ${BINDMASTER_ALLOW_EMPTY:+--allow-empty}",
            "fi",
            "",
        ]

    lines += [
        "# Step 2: Run evaluation pipeline",
        f'echo "=== Running Evaluator for {cfg["name"]} ==="',
        'bash "$EVAL_SCRIPT" \\',
        '    --sequences "$SEQUENCES" \\',
        f'    --target-seq "{target_seq}" \\',
        '    --output "$OUTPUT_DIR" \\',
    ]

    # Engine selection flags (skip flags omit engines NOT selected)
    if not cfg.get("use_boltz", True):
        lines.append("    --skip-boltz2 \\")
    if not cfg.get("use_af3", False):
        lines.append("    --skip-af3 \\")
    if not cfg.get("use_esmfold2", False):
        lines.append("    --skip-esmfold2 \\")

    # SoluProt is a screen, not an engine. When enabled it runs before the
    # refold steps; --soluprot-filter drops sub-threshold designs from the
    # FASTA so the refold engines never see them.
    if not cfg.get("use_soluprot", False):
        lines.append("    --skip-soluprot \\")
    else:
        threshold = cfg.get("soluprot_threshold", 0.5)
        lines.append(f"    --soluprot-threshold {threshold} \\")
        if cfg.get("soluprot_filter", False):
            lines.append("    --soluprot-filter \\")

    primary = cfg.get("primary_engine", "boltz")
    lines += [
        f"    --primary-engine {primary} \\",
    ]

    # Emitted ONLY when the operator chose it (wizard prompt, or by hand in
    # config.json). Absent means evaluate.sh keeps the default gate of 3 — the gate is
    # never derived from the engines this host happens to have, because that would make
    # two operators with the same designs produce different rankings.
    min_engines = cfg.get("min_engines")
    if min_engines:
        lines.append(f"    --min-engines {min_engines} \\")

    lines += [
        "    --resume",
        "",
    ]

    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o755)


# ─── Generation ───────────────────────────────────────────────────────────────


# ─── Run config persistence (headless replay) ─────────────────────────────────

CONFIG_FILENAME = "config.json"


def _jsonable(value):
    """Path -> str; everything else passes through."""
    return str(value) if isinstance(value, Path) else value


def write_run_config(path: Path, cfg: dict, tools_enabled: dict) -> None:
    """Persist the exact answers that produced this run directory.

    The wizard's ~80 answers were previously discarded the moment the scripts were
    written, so reproducing a campaign meant re-typing every one of them and there was
    no machine-readable record of what a run was configured with. `cfg` already IS the
    complete description — it just was never saved.

    Together with `--config`, this closes CLAUDE.md's deferred item F2 ("--headless
    mode for configurator") and gives any future front-end (GUI, cron, another script)
    something to read and write instead of re-implementing the interview.
    """
    payload = {
        "_comment": (
            "Written by `bindmaster configure`. Replay with: "
            "`python configurator/configurator.py --config <this file>`. "
            "Edit freely — every key maps to one wizard answer."
        ),
        "config_version": 1,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tools_enabled": dict(sorted(tools_enabled.items())),
        "cfg": {k: _jsonable(v) for k, v in sorted(cfg.items())},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _default_pxdesign_mode(tools_enabled: dict, cfg: dict | None = None) -> None:
    """`pxdesign: True` with no mode key: INFER the mode from the evidence, then default.

    PXDesign is the one tool with a MODE on top of its switch — local run vs. importing
    someone else's results — and each half is gated on a different key (`pxdesign_local`
    for the generator, `pxdesign` + cfg["pxdesign_output_dir"] for write_run_evaluate's
    import branch). Only the wizard's mode prompt sets those keys, so a headless
    `--config` that enabled the tool the obvious way got no run_pxdesign.sh while the
    summary still listed PXDesign as enabled.

    Defaulting unconditionally to local, though, broke the other hand-written shape:
    `{pxdesign: true}` plus cfg["pxdesign_output_dir"] is unambiguously an IMPORT, and
    forcing it to local mode then hard-failed preflight on local mode's required keys
    (pxdesign_binder_length) — a config that used to work. So look at cfg first:
    pxdesign_output_dir is read only by the import path, and local mode never sets it.
    An explicit mode key still wins, and the wizard always sets all three, so this stays
    a no-op there.
    """
    if not tools_enabled.get("pxdesign"):
        return
    if tools_enabled.get("pxdesign_local") or tools_enabled.get("pxdesign_import"):
        return
    if cfg and cfg.get("pxdesign_output_dir"):
        tools_enabled["pxdesign_import"] = True
        print_warn("pxdesign enabled without a mode — inferring IMPORT (pxdesign_import).")
        print("  Evidence: cfg['pxdesign_output_dir'] is set, and only import mode reads it.")
        return
    tools_enabled["pxdesign_local"] = True
    print_warn("pxdesign enabled without a mode — inferring a LOCAL run (pxdesign_local).")
    print("  Evidence: no cfg['pxdesign_output_dir'] to import from, and a local run is")
    print("  what the other six tools mean by 'enabled'. Set pxdesign_output_dir to import.")


def known_cfg_keys() -> frozenset[str]:
    """Every cfg key this module actually reads, recovered from its own source.

    Derived rather than hand-listed so it cannot drift: a hand list is how
    `pxdesign_n_samples` and `bindcraft_n_designs` came to be siblings with
    different suffixes in the first place.
    """
    keys: set[str] = set()
    try:
        tree = ast.parse(Path(__file__).read_text())
    except (OSError, SyntaxError):
        return frozenset()

    for node in ast.walk(tree):
        # cfg["key"] / cfg.get("key")
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "cfg":
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                keys.add(node.slice.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "cfg"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return frozenset(keys)


def check_cfg_keys(cfg: dict, path: Path) -> None:
    """Refuse a config carrying a key this version does not read.

    A silently ignored key is the worst outcome available here, because the value
    the user wrote is replaced by a default that is nowhere in their config. The PDL1
    campaign config carried `pxdesign_n_designs: 1` — plausible, since
    `bindcraft_n_designs` is real — but the writer reads `pxdesign_n_samples`, so the
    key was dropped and PXDesign ran its **1000**-sample default. That is ~1000x the
    requested GPU work, and the only symptom was 1000 of 1003 sequences arriving at
    the evaluator, hours later.

    Fatal rather than a warning: this path is `--config`, i.e. unattended by design,
    so a warning scrolls past into a log nobody reads until the GPU bill arrives.
    Keys starting with `_` are exempt — `_comment` is written by this very module and
    is meant to be inert.
    """
    known = known_cfg_keys()
    if not known:  # AST parse of our own source failed; nothing to check against
        return

    unknown = sorted(k for k in cfg if k not in known and not k.startswith("_"))
    if not unknown:
        return

    print_fail(f"{path.name} has {len(unknown)} key(s) this version does not read:")
    for key in unknown:
        # Three candidates, not one: edit distance ranks `pxdesign_chains` above
        # `pxdesign_n_samples` for `pxdesign_n_designs`, so the single best guess is
        # not reliably the right one. Let the reader pick.
        close = difflib.get_close_matches(key, sorted(known), n=3, cutoff=0.5)
        hint = f"  — did you mean {', '.join(repr(c) for c in close)}?" if close else ""
        print(f"    {key!r} = {cfg[key]!r}{hint}")
    print_warn("  An unread key is not a no-op: the built-in default is used instead.")
    print_warn("  Fix the spelling, or delete the key to accept the default deliberately.")
    sys.exit(1)


def load_run_config(path: Path) -> tuple[dict, dict]:
    """Read a config.json back into (cfg, tools_enabled).

    Path-typed keys are restored, and `run_dir` is re-resolved so a config can be
    copied to another machine (or edited to point at a new run directory) and replayed.
    """
    try:
        payload = json.loads(Path(path).expanduser().read_text())
    except (OSError, ValueError) as exc:
        print_fail(f"Could not read config {path}: {exc}")
        sys.exit(1)

    if not isinstance(payload, dict) or "cfg" not in payload or "tools_enabled" not in payload:
        print_fail(f"{path} is not a BindMaster run config (expected 'cfg' and 'tools_enabled' keys).")
        sys.exit(1)

    version = payload.get("config_version")
    if version != 1:
        print_warn(f"config_version {version!r} is not 1 — attempting to load anyway.")

    cfg = dict(payload["cfg"])
    tools_enabled = dict(payload["tools_enabled"])
    check_cfg_keys(cfg, Path(path))
    _default_pxdesign_mode(tools_enabled, cfg)

    for key in ("run_dir", "target_pdb", "target_pdb_src"):
        if cfg.get(key):
            cfg[key] = Path(str(cfg[key])).expanduser()

    missing = [k for k in ("name", "run_dir", "target_pdb_src") if not cfg.get(k)]
    if missing:
        print_fail(f"{path} is missing required keys: {', '.join(missing)}")
        sys.exit(1)

    if not Path(cfg["target_pdb_src"]).exists():
        print_fail(f"Target structure not found: {cfg['target_pdb_src']}")
        print_warn("  Edit target_pdb_src in the config, or copy the structure to that path.")
        sys.exit(1)

    return cfg, tools_enabled


def cmd_from_config(config_path: str, run_now: bool) -> None:
    """Non-interactive path: generate a run directory straight from a saved config."""
    cfg, tools_enabled = load_run_config(Path(config_path))
    run_dir = Path(cfg["run_dir"])

    # Before the summary, not just before generate(): the summary itself resolves the
    # BoltzGen budget out of cfg, so an incomplete config has to be a preflight message
    # here rather than a KeyError traceback. generate() calls preflight again; it only
    # prints on failure, so the repeat is free.
    preflight(cfg, tools_enabled)

    print_step(f"Generating run folder from {config_path}")
    print(f"  Run folder: {run_dir}")
    enabled = [label for _k, _s, label, _d in enabled_tools(tools_enabled)]
    print(f"  Tools:      {', '.join(enabled) if enabled else '(none)'}")
    if tools_enabled.get("boltzgen"):
        # Same pre-GPU cost line the wizard preview prints — this path had no summary at
        # all, and it is the path where `n_designs: 1` met a flat --num_designs 10000.
        print(f"  BoltzGen:   {boltzgen_cost_note(boltzgen_intermediate(cfg))}")
    if tools_enabled.get("evaluator"):
        print("  Evaluator:  enabled")

    if not enabled and not tools_enabled.get("evaluator"):
        print_fail("No tools enabled in this config — nothing to generate.")
        sys.exit(1)

    run_dir.mkdir(parents=True, exist_ok=True)
    generate(cfg, tools_enabled)
    print_ok(f"Run folder ready: {run_dir}")

    if run_now:
        run_pipeline(cfg, tools_enabled)
    else:
        print()
        print_warn("To run:")
        step = 1
        for _key, script, _label, _subdir in enabled_tools(tools_enabled):
            print(f"  {step}. bash {run_dir}/{script}")
            step += 1
        if tools_enabled.get("evaluator"):
            print(f"  {step}. bash {run_dir}/run_evaluate.sh")
        if len(enabled) > 1:
            print(f"  Or the whole pipeline:  bash {run_dir}/run_all.sh")
        print()


# Files each tool's generator reads out of that tool's cloned repo. Absent means the
# tool is not installed. The generators used to discover this halfway through writing
# the run directory, as a bare FileNotFoundError traceback — and since config.json is
# written at the END of generate(), the wizard's ~80 answers went with it.
def _missing_tool_assets(cfg: dict, tools_enabled: dict) -> list[tuple[str, Path, str]]:
    """(tool label, missing path, how to get it) for every enabled tool that cannot generate."""
    missing: list[tuple[str, Path, str]] = []

    if tools_enabled.get("bindcraft"):
        for src_dir, stem in ((FILTERS_DIR, cfg.get("filter_preset")), (ADVANCED_DIR, cfg.get("advanced_preset"))):
            if stem and not (src_dir / f"{stem}.json").is_file():
                missing.append(("BindCraft", src_dir / f"{stem}.json", "bindmaster install --tool bindcraft"))

    # Ask the venv, NOT MOSAIC_HALLUCINATE_SRC. That constant now prefers the template
    # in bindmaster_examples/, which is tracked in this repo and therefore ALWAYS exists —
    # checking it here made "is Mosaic installed" unfalsifiable and silently deleted this
    # guard. Two different questions were riding one constant: which template to inject
    # from (the repo's, always present) versus whether the tool can actually run (the uv
    # venv, which only the installer creates, and which run_mosaic.sh requires).
    if tools_enabled.get("mosaic") and not MOSAIC_VENV.is_dir():
        missing.append(("Mosaic", MOSAIC_VENV, "bindmaster install --tool mosaic"))

    if tools_enabled.get("boltzgen") and cfg.get("boltzgen_mode") == "nanobody":
        for name in NANOBODY_SCAFFOLD_NAMES:
            for ext in (".yaml", ".cif"):
                src = NANOBODY_SCAFFOLDS_SRC / f"{name}{ext}"
                if not src.is_file():
                    missing.append(("BoltzGen (nanobody mode)", src, "bindmaster install --tool boltzgen"))

    return missing


# Keys each tool's generator reads as cfg["..."] — absent is a KeyError, not a default.
# The wizard always sets them; a hand-written or hand-edited --config need not, and
# `configurator --config` validates only name / run_dir / target_pdb_src. Kept in sync
# with the writers by tests/configurator/test_configurator_writers.py, which re-derives
# this map from the writer sources.
REQUIRED_CFG_KEYS: dict[str, tuple[str, ...]] = {
    "bindcraft": ("chains", "hotspots", "max_length", "min_length", "n_designs", "target_pdb"),
    # No "boltzgen_intermediate": it is now derived from n_designs when absent
    # (boltzgen_intermediate()), so a config that omits it gets a pool sized to the
    # request instead of a flat 10 000 — and requiring it would force every headless
    # config to restate the value the derivation exists to supply.
    "boltzgen": (
        "chains",
        "hotspots",
        "max_length",
        "min_length",
        "n_designs",
        "target_pdb",
    ),
    "mosaic": ("max_length", "min_length", "n_designs", "target_sequence"),
    "pxdesign_local": ("pxdesign_binder_length", "target_pdb"),
    "proteina_complexa": ("target_pdb",),
    "rfd3": ("target_pdb",),
    "protein_hunter": (),
    "evaluator": (),
}


def _missing_cfg_keys(cfg: dict, tools_enabled: dict) -> list[tuple[str, str]]:
    """(tool key, missing cfg key) pairs, deduplicated across tools that share a key."""
    seen: set[str] = set()
    missing: list[tuple[str, str]] = []
    for tool, keys in REQUIRED_CFG_KEYS.items():
        if not tools_enabled.get(tool):
            continue
        for key in keys:
            # `target_pdb` is derived by generate() from target_pdb_src, so it counts as
            # present whenever the source structure was given (load_run_config checks it).
            if key == "target_pdb" and cfg.get("target_pdb_src"):
                continue
            if key not in cfg and key not in seen:
                seen.add(key)
                missing.append((tool, key))
    return missing


# The tools_enabled keys generate() gates a run-script writer on. Identical to
# TOOL_SEQUENCE's keys today; the pair exists so that a drift between the list the UI
# calls "enabled" and the key the generator actually branches on is reportable BEFORE a
# single file is written. PXDesign shipped for a while with the generator on
# "pxdesign_local" while the summary keyed on "pxdesign", so a run advertised a tool it
# had written no script for. Kept honest by tests/configurator/test_configurator_writers.py,
# which re-derives the keys generate() branches on from its own source.
_SCRIPT_WRITER_KEYS = frozenset(
    {
        "bindcraft",
        "boltzgen",
        "mosaic",
        "pxdesign_local",
        "proteina_complexa",
        "rfd3",
        "protein_hunter",
    }
)


def _tools_without_a_generator(tools_enabled: dict) -> list[tuple[str, str, str]]:
    """(label, tools_enabled key, script) for enabled tools generate() would not write.

    Knowable before any file exists, which is the point: the post-write check below
    could only report the same fact after both config.json writes, leaving a half-built
    run directory for the user to clean up.
    """
    return [
        (label, key, script)
        for key, script, label, _subdir in enabled_tools(tools_enabled)
        if key not in _SCRIPT_WRITER_KEYS
    ]


def verify_enabled_tools_generated(run_dir: Path, tools_enabled: dict) -> None:
    """Every tool reported as enabled must have left its run script behind.

    Defence in depth behind preflight's _tools_without_a_generator(), which asks the
    same question up front from the key registry. This one asks the filesystem after
    the fact, so a generator branch that exists but silently writes nothing (a writer
    that returns early, a path built wrong) is still caught.
    """
    missing = [
        (label, script)
        for _key, script, label, _subdir in enabled_tools(tools_enabled)
        if not (run_dir / script).is_file()
    ]
    if not missing:
        return

    print()
    print_fail("This run is incomplete — tools are reported as enabled but have no run script:")
    for label, script in missing:
        print(f"    {RED}✗{RESET} {label}    (expected: {run_dir / script})")
    print()
    print("    That is a configurator bug, not a problem with your config: the generator")
    print("    gates this tool on a different key than the enabled-tools list does.")
    print()
    sys.exit(1)


def preflight(cfg: dict, tools_enabled: dict) -> None:
    """Refuse to start generating unless every enabled tool can be generated.

    Reports EVERYTHING that is wrong at once and exits 1 before a single file is
    written, instead of raising a traceback partway through and leaving a half-built
    run directory behind.
    """
    assets = _missing_tool_assets(cfg, tools_enabled)
    keys = _missing_cfg_keys(cfg, tools_enabled)
    ungenerated = _tools_without_a_generator(tools_enabled)
    if not assets and not keys and not ungenerated:
        return

    print()
    print_fail("Cannot generate this run — fix the following first:")
    if ungenerated:
        print()
        print(f"  {BOLD}Tools reported as enabled that the generator has no writer for:{RESET}")
        for label, key, script in ungenerated:
            print(f"    {RED}✗{RESET} {label}    (key {key!r}, would never write {script})")
        print()
        print("    That is a configurator bug, not a problem with your config: the generator")
        print("    gates this tool on a different key than the enabled-tools list does.")
    if assets:
        print()
        print(f"  {BOLD}Enabled tools that are not installed:{RESET}")
        for label, path, how in assets:
            print(f"    {RED}✗{RESET} {label}: missing {path}")
            print(f"       install it:  {how}   (or disable {label} for this run)")
    if keys:
        print()
        print(f"  {BOLD}Config keys the enabled tools need but this config does not set:{RESET}")
        for tool, key in keys:
            print(f"    {RED}✗{RESET} {key}    (required by: {tool})")
        print()
        print("    Every wizard run writes a complete config to runs/<name>/config.json —")
        print("    copy that and edit values rather than writing one from scratch.")
    print()
    sys.exit(1)


def generate(cfg: dict, tools_enabled: dict):
    run_dir: Path = cfg["run_dir"]

    # Everything below writes files. Validate first so a missing tool or a missing
    # config key is a message, not a traceback over a half-written run directory.
    preflight(cfg, tools_enabled)

    (run_dir / "target").mkdir(parents=True, exist_ok=True)
    # Persist the answers BEFORE generating anything. This used to be the last line of
    # the function, so any failure in between cost the operator the entire wizard
    # session — ~80 answers with nothing to replay. Written again at the end to capture
    # the paths generate() derives (target_pdb, target_cif).
    write_run_config(run_dir / CONFIG_FILENAME, cfg, tools_enabled)
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
    # <name>.pdb is the PREPARED target every tool reads; the verbatim source is kept
    # beside it as <name>_original.pdb (and, for CIF input, the untouched .cif) so
    # preparation never destroys the only copy of the deposited coordinates.
    dest_pdb = run_dir / "target" / f"{cfg['name']}.pdb"
    raw_pdb: Path | None = run_dir / "target" / f"{cfg['name']}_original.pdb"
    if src_ext in (".cif", ".mmcif"):
        # Copy the original CIF
        dest_cif = run_dir / "target" / f"{cfg['name']}{src_ext}"
        shutil.copy2(src_struct, dest_cif)
        # Convert to PDB for tools that need it
        if cif_to_pdb_atoms(str(src_struct), str(raw_pdb)):
            print_ok(f"Converted CIF → PDB: {raw_pdb.name}")
        else:
            print_warn("CIF→PDB conversion failed — some tools may not work with CIF input.")
            raw_pdb = None
            dest_pdb = dest_cif  # fallback: point at CIF
        cfg["target_cif"] = dest_cif
    else:
        shutil.copy2(src_struct, raw_pdb)

    if raw_pdb is not None:
        report = prepare_target_pdb(raw_pdb, dest_pdb, cfg.get("chains", "A"), cfg.get("target_sequence", "") or "")
        if report is None:
            print_warn(f"Could not prepare {raw_pdb.name} — no amino-acid residues found in the selected chain(s).")
            print("  Copying the structure through unchanged: bound ligands, waters and any")
            print("  purification tag in the coordinates will be visible to every design tool.")
            shutil.copy2(raw_pdb, dest_pdb)
        else:
            report_target_preparation(report, dest_pdb)
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
        # Matches every other tool: create the output dir the run script writes into
        # (rfd3/sequences.csv), which is also the dir run_evaluate.sh hands the extractor.
        (run_dir / "rfd3").mkdir(parents=True, exist_ok=True)
        write_run_rfd3(run_dir / "run_rfd3.sh", cfg)

    if tools_enabled.get("protein_hunter"):
        (run_dir / "protein_hunter").mkdir(parents=True, exist_ok=True)
        write_run_protein_hunter(run_dir / "run_protein_hunter.sh", cfg)

    if tools_enabled.get("evaluator"):
        write_run_evaluate(run_dir / "run_evaluate.sh", cfg, tools_enabled)

    write_run_all(run_dir / "run_all.sh", cfg, tools_enabled)

    # Save the answers that produced this directory, so the run is replayable with
    # `configurator.py --config` and machine-readable without re-running the wizard.
    write_run_config(run_dir / CONFIG_FILENAME, cfg, tools_enabled)

    verify_enabled_tools_generated(run_dir, tools_enabled)


# ─── Pipeline runner ──────────────────────────────────────────────────────────


def run_pipeline(cfg: dict, tools_enabled: dict):
    """Run the enabled tools in sequence with live terminal output."""
    run_dir = cfg["run_dir"]
    failed = []

    # Driven by TOOL_SEQUENCE, so a newly added tool is dispatched automatically.
    # The previous hand-written if-chain covered 5 of the 7 tools: answering "y" to
    # "Run the pipeline now?" silently ran nothing for RFD3 or Protein-Hunter, and
    # the Evaluator then reported on an empty pool.
    for _key, script, label, _subdir in enabled_tools(tools_enabled):
        print_step(f"Running {label}")
        rc = subprocess.run(["bash", str(run_dir / script)]).returncode
        if rc == 0:
            print_ok(f"{label} completed")
        else:
            print_fail(f"{label} failed (exit code {rc})")
            failed.append(label)

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

    # A bare .exists() is true for FILES too, and the prompt above asked for a path —
    # pasting the target .pdb here used to be accepted, warned about as a "folder",
    # offered a meaningless "Overwrite?", and then crash generate() with
    # NotADirectoryError after all ~80 answers had been given. Catch it while the
    # user can still fix it for free.
    if run_dir.exists() and not run_dir.is_dir():
        print()
        print_fail(f"Not a directory: {run_dir}")
        print("  The run folder must be a directory (or a new path).")
        print("  Did you paste the target structure path by mistake?")
        sys.exit(1)

    if run_dir.is_dir() and any(run_dir.iterdir()):
        print()
        print_warn(f"Run folder already exists and is not empty: {run_dir}")
        print("  Existing files with the same names will be replaced; others are left alone.")
        if not ask_yn("  Continue?", default=False):
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
        # The file and chain go with the sequence: the depositor's own SEQADV /
        # _struct_ref_seq_dif records name the construct residues exactly, and a pattern
        # over the sequence alone cannot (5O45's AAALE linker defeats any character class).
        target_sequence = warn_expression_tags(target_sequence, target_pdb_src, primary_chain)
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
        return f"{RED}NOT installed — run: {_INVOKE} install{RESET}"

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
    print(f"  {BOLD}Protein-Hunter{RESET} [{_tag('protein_hunter')}]")
    use_protein_hunter = ask_yn("  Enable Protein-Hunter (Boltz-2 / Chai-1 hallucination)?", default=False)
    print(f"  {BOLD}RFD3{RESET} [{_tag('rfd3')}]")
    use_rfd3 = ask_yn("  Enable RFD3 (RosettaCommons foundry diffusion + ProteinMPNN)?", default=False)
    print(f"  {BOLD}Evaluator{RESET} [{_tag('evaluator')}]")
    use_evaluator = ask_yn("  Enable cross-evaluation (refolding + ranked report)?", default=False)

    # ── Refolding engine selection ──
    use_boltz = use_af3 = use_esmfold2 = False
    primary_engine = "boltz"
    min_engines = None
    if use_evaluator:
        print(f"  {BOLD}Refolding engines for evaluation{RESET}")
        engines_available = []
        if installed.get("mosaic"):
            engines_available.append(("boltz", "Boltz-2 (Mosaic venv)", True))
        else:
            print(f"    Boltz-2: {RED}requires Mosaic install{RESET} — skipped")
        if installed.get("af3"):
            engines_available.append(("af3", "AlphaFold 3 v3.0.2 (binder-eval-af3 env)", False))
        else:
            print(f"    AF3: {RED}requires binder-eval-af3 env{RESET} — skipped")
        if installed.get("esmfold2"):
            engines_available.append(("esmfold2", "ESMFold2 (binder-eval-esmfold2 env)", False))
        else:
            print(f"    ESMFold2: {RED}requires binder-eval-esmfold2 env{RESET} — skipped")
        for key, label, default_on in engines_available:
            ans = ask_yn(f"    Use {label}?", default=default_on)
            if key == "boltz":
                use_boltz = ans
            elif key == "af3":
                use_af3 = ans
            elif key == "esmfold2":
                use_esmfold2 = ans
        # Require at least one engine
        if not (use_boltz or use_af3 or use_esmfold2):
            print_warn("No refolding engine selected — Evaluator disabled.")
            use_evaluator = False
        else:
            # If >1 engine, pick primary
            selected = [
                k
                for k, on in (
                    ("boltz", use_boltz),
                    ("af3", use_af3),
                    ("esmfold2", use_esmfold2),
                )
                if on
            ]
            if len(selected) > 1:
                default_idx = selected.index("boltz") if "boltz" in selected else 0
                idx, _ = ask_choice("    Primary engine for ranking", selected, default_index=default_idx)
                primary_engine = selected[idx]
            else:
                primary_engine = selected[0]

            # The cross-engine gate defaults to 3 and is NEVER lowered automatically —
            # deriving it from whatever happens to be installed would make two operators
            # with the same designs produce different rankings (CLAUDE.md). But running
            # fewer engines than the gate means no design can clear it and the shortlist
            # comes back empty with no error, which is exactly what the documented
            # one-command path does on any host without the gated AF3 weights. So ask
            # once, here, and record the answer in config.json — the gate stays an
            # explicit, reproducible, auditable decision.
            if len(selected) == 2:
                print()
                print_warn("Only 2 refold engines selected, but the cross-engine gate defaults to 3.")
                print("  With the default, every design fails the gate and you get no ranked shortlist.")
                print("  Lowering it ranks on the engines you have — but rankings are then only")
                print("  comparable to other runs using the same number of engines.")
                if ask_yn("    Set --min-engines 2 in run_evaluate.sh?", default=True):
                    min_engines = 2
            elif len(selected) == 1:
                print()
                print_warn("Only 1 refold engine selected — a cross-engine consensus needs at least 2.")
                print("  The gate cannot be met at all, so the ranked shortlist will be empty.")
                print("  Enable AF3 or ESMFold2 as a second engine to get a ranked report.")

    # ── SoluProt solubility screen (filter, not engine) ──
    # Sits before the refold engines — when --soluprot-filter is on, designs
    # below the threshold are dropped from the FASTA so the refold engines
    # never spend GPU on them. SoluProt is a screen; it does NOT participate
    # in ranking.
    use_soluprot = False
    soluprot_threshold = 0.5
    soluprot_filter = False
    if use_evaluator and installed.get("soluprot"):
        print(f"  {BOLD}SoluProt solubility screen{RESET} (sequence-only filter, no GPU)")
        use_soluprot = ask_yn("    Use SoluProt to score solubility?", default=True)
        if use_soluprot:
            soluprot_threshold = float(
                ask(
                    "    Pass threshold (paper default 0.5; lower for short binders)",
                    default=0.5,
                    validator=lambda v: True if 0.0 <= float(v) <= 1.0 else "must be 0.0–1.0",
                )
            )
            soluprot_filter = ask_yn(
                "    Drop sub-threshold designs BEFORE refolding (saves GPU)?",
                default=True,
            )

    tools_enabled = {
        "mosaic": use_mosaic,
        "boltzgen": use_boltzgen,
        "bindcraft": use_bindcraft,
        "pxdesign": use_pxdesign,
        "pxdesign_local": use_pxdesign_local,
        "pxdesign_import": use_pxdesign_import,
        "proteina_complexa": use_proteina_complexa,
        "protein_hunter": use_protein_hunter,
        "rfd3": use_rfd3,
        "evaluator": use_evaluator,
        "use_boltz": use_boltz,
        "use_af3": use_af3,
        "use_esmfold2": use_esmfold2,
        "primary_engine": primary_engine,
        "use_soluprot": use_soluprot,
        "soluprot_threshold": soluprot_threshold,
        "soluprot_filter": soluprot_filter,
    }

    # Evaluator is post-processing — don't count it as the sole tool
    _meta_keys = {
        "evaluator",
        "use_boltz",
        "use_af3",
        "use_esmfold2",
        "primary_engine",
        "use_soluprot",
        "soluprot_threshold",
        "soluprot_filter",
    }
    design_tools = {k: v for k, v in tools_enabled.items() if k not in _meta_keys}
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
        "boltzgen_intermediate": boltzgen_intermediate_default(n_designs),
        "use_boltz": use_boltz,
        "use_af3": use_af3,
        "use_esmfold2": use_esmfold2,
        "primary_engine": primary_engine,
        # None = leave the cross-engine gate at its default of 3. Set only by the
        # explicit prompt above (or by hand in config.json) — never derived from what
        # happens to be installed.
        "min_engines": min_engines,
        "use_soluprot": use_soluprot,
        "soluprot_threshold": soluprot_threshold,
        "soluprot_filter": soluprot_filter,
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
        # Default scaled to the budget just entered, not a flat 10 000 — see
        # boltzgen_intermediate(). The cost is stated before the prompt because this one
        # answer is the whole GPU bill for the tool.
        bg_intermediate_default = boltzgen_intermediate_default(cfg["boltzgen_budget"])
        print("  BoltzGen over-generates, then filters down to the budget above.")
        print(f"  Default pool for a budget of {cfg['boltzgen_budget']}: {boltzgen_cost_note(bg_intermediate_default)}")
        cfg["boltzgen_intermediate"] = int(
            ask(
                "  Intermediate designs (--num_designs)",
                default=bg_intermediate_default,
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
            ask(
                "  Top designs to refold (best-of-N for Stage 2)",
                default=min(5, n_designs),
                validator=validate_int(min_val=0),
            )
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
        print_step("Step 6e — Proteina-Complexa settings")
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

    if use_rfd3:
        print_step("Step 6f — RFD3 settings")
        cfg["rfd3_batch_size"] = int(
            ask(
                "  Diffusion batch size (10 fits 24 GB; drop to 4 for longer binders)",
                default=10,
                validator=validate_int(min_val=1, max_val=64),
            )
        )
        cfg["rfd3_mpnn_samples"] = int(
            ask(
                "  ProteinMPNN sequences per backbone (best-of-N)",
                default=5,
                validator=validate_int(min_val=1, max_val=64),
            )
        )
        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["rfd3_min_length"] = int(
            ask("  Min binder length", default=min_length, validator=validate_int(min_val=10, max_val=500))
        )
        cfg["rfd3_max_length"] = int(
            ask("  Max binder length", default=max_length, validator=validate_int(min_val=10, max_val=500))
        )
        cfg["rfd3_n_designs"] = int(
            ask("  Number of backbone designs", default=n_designs, validator=validate_int(min_val=1, max_val=10000))
        )

    if use_protein_hunter:
        print_step("Step 6g — Protein-Hunter settings")
        cfg["protein_hunter_num_cycles"] = int(
            ask(
                "  Boltz-2 hallucination cycles per design (7 = CALCA-validated)",
                default=7,
                validator=validate_int(min_val=1, max_val=20),
            )
        )
        _, ph_msa = ask_choice(
            "  MSA mode",
            [
                "single — no MSA, fastest (recommended for de-novo binders)",
                "mmseqs — fetch MSA from ColabFold server (slower)",
            ],
            default_index=0,
        )
        cfg["protein_hunter_msa_mode"] = ph_msa.split(" — ")[0].strip()
        print(f"  {YELLOW}Per-tool overrides (Enter = keep global default):{RESET}")
        cfg["protein_hunter_min_length"] = int(
            ask("  Min binder length", default=min_length, validator=validate_int(min_val=10, max_val=500))
        )
        cfg["protein_hunter_max_length"] = int(
            ask("  Max binder length", default=max_length, validator=validate_int(min_val=10, max_val=500))
        )
        cfg["protein_hunter_n_designs"] = int(
            ask("  Number of designs", default=n_designs, validator=validate_int(min_val=1, max_val=10000))
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
        bg_n = boltzgen_budget(cfg)
        mode_label = "nanobody CDR redesign" if cfg["boltzgen_mode"] == "nanobody" else "de-novo protein"
        print(
            f"  {CYAN}BoltzGen{RESET}:      {mode_label}  |  "
            f"length={bg_min}–{bg_max}  budget={bg_n}  "
            f"intermediate={boltzgen_intermediate(cfg):,}"
        )
        # The intermediate pool IS the BoltzGen runtime, and it is the one number here
        # that can turn a one-design smoke test into an overnight job. Say the cost now,
        # while it is still a prompt away, the way Evaluator/evaluate.sh warns before it
        # spends GPU time rather than reporting it afterwards.
        print(f"  {CYAN}BoltzGen cost{RESET}: {boltzgen_cost_note(boltzgen_intermediate(cfg))}")
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
    if use_rfd3:
        r_min = cfg.get("rfd3_min_length", min_length)
        r_max = cfg.get("rfd3_max_length", max_length)
        r_n = cfg.get("rfd3_n_designs", n_designs)
        print(
            f"  {CYAN}RFD3{RESET}:          length={r_min}–{r_max}  "
            f"designs={r_n}  batch={cfg.get('rfd3_batch_size', 10)}  "
            f"mpnn_samples={cfg.get('rfd3_mpnn_samples', 5)}"
        )
    if use_protein_hunter:
        ph_min = cfg.get("protein_hunter_min_length", min_length)
        ph_max = cfg.get("protein_hunter_max_length", max_length)
        ph_n = cfg.get("protein_hunter_n_designs", n_designs)
        print(
            f"  {CYAN}Protein-Hunter{RESET}: length={ph_min}–{ph_max}  designs={ph_n}  "
            f"cycles={cfg.get('protein_hunter_num_cycles', 7)}  "
            f"msa={cfg.get('protein_hunter_msa_mode', 'single')}"
        )
    if use_evaluator:
        engines = []
        if cfg.get("use_boltz"):
            engines.append("Boltz-2")
        if cfg.get("use_af3"):
            engines.append("AF3")
        if cfg.get("use_esmfold2"):
            engines.append("ESMFold2")
        engines_str = " + ".join(engines) if engines else "Boltz-2"
        primary = cfg.get("primary_engine", "boltz")
        print(f"  {CYAN}Evaluator{RESET}:     {engines_str}  |  primary={primary}  → ranked report")

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
    if use_boltzgen:
        print_warn("BoltzGen downloads ~6 GB of weights on first run.")
    if use_evaluator:
        print_warn("Evaluator runs Boltz-2 refolding (GPU recommended, ~30 min per design).")

    if ask_yn("Run the pipeline now?", default=True):
        run_pipeline(cfg, tools_enabled)
    else:
        print()
        print_warn("To run later:")
        # Driven by TOOL_SEQUENCE so every generated script is listed. The old
        # hand-written chain omitted RFD3 and Protein-Hunter, so a user who enabled
        # them was never told their run scripts existed.
        step = 1
        for _key, script, _label, _subdir in enabled_tools(tools_enabled):
            print(f"  {step}. bash {run_dir}/{script}")
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
    parser.add_argument(
        "--config",
        metavar="JSON",
        help=(
            "Generate a run folder non-interactively from a saved config, skipping all "
            f"prompts. Every wizard run writes one to runs/<name>/{CONFIG_FILENAME} — copy "
            "it, edit it, and replay. Closes the headless gap for cron / scripts / a GUI."
        ),
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="With --config: run the pipeline immediately after generating the scripts.",
    )
    args = parser.parse_args()

    if args.archive:
        cmd_archive(args.archive)
    elif args.status:
        cmd_status()
    elif args.config:
        cmd_from_config(args.config, run_now=args.run)
    else:
        wizard()


if __name__ == "__main__":
    try:
        main()
    except EOFError:
        # Piped/redirected stdin or a Ctrl-D at a prompt. Used to dump an EOFError
        # traceback, which reads as "the software is broken" to a non-programmer.
        print(f"\n\n  {YELLOW}No more input.{RESET} The wizard needs an interactive terminal.")
        print(f"  For scripted use see:  {CYAN}{_INVOKE} configure --config <config.json>{RESET}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}Interrupted.{RESET} Some files may have been partially written.")
        sys.exit(1)
