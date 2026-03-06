"""
Ligand validation and preparation utilities for RFDiffusionAA.
"""

import re
from pathlib import Path


def list_hetatm_codes(pdb_path: Path) -> list[str]:
    """
    Parse a PDB file and return all unique 3-letter HETATM residue names.
    """
    codes = set()
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("HETATM"):
                code = line[17:20].strip()
                if code and code not in ("HOH", "WAT", "DOD"):
                    codes.add(code)
    return sorted(codes)


def verify_ligand_in_pdb(pdb_path: Path, ligand_ccd: str) -> bool:
    """
    Check that a ligand CCD code is present in the PDB as a HETATM record.
    """
    if not pdb_path.exists():
        raise FileNotFoundError(f"PDB not found: {pdb_path}")

    available = list_hetatm_codes(pdb_path)
    found = ligand_ccd.upper() in available

    if not found:
        print(
            f"[rfaa/ligand_prep] Ligand '{ligand_ccd}' not found in {pdb_path.name}.\n"
            f"   Available HETATM codes: {available or 'none'}"
        )
    return found


def validate_contig_string(contig: str) -> tuple[bool, str]:
    """
    Validate a contig string for RFAA.

    Valid formats:
        '150-150'                   — free binder, 150 residues
        '10-120,A84-87,10-120'      — motif with flanking
        '100-200'                   — variable length binder

    Returns:
        (is_valid, error_message) — error_message is '' if valid
    """
    if not contig:
        return False, "Contig string is empty"

    parts = contig.split(",")
    for part in parts:
        part = part.strip()
        if re.fullmatch(r'\d+-\d+', part):
            lo, hi = map(int, part.split('-'))
            if lo > hi:
                return False, f"Invalid range {part}: lower bound > upper bound"
        elif re.fullmatch(r'[A-Za-z]\d+-\d+', part):
            pass
        else:
            return False, f"Unrecognized contig element: '{part}'"

    return True, ""
