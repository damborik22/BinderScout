"""Epitope-match fraction (Item 2).

Reviewer concern: iPTM/ipSAE measure how well the binder binds *something* on
the target, not whether the contact lands on the intended epitope. For
flexible/distinct-pocket targets (serpins like 2VDY have a steroid pocket, a
RCL, and a shutter region) a design with high cross-engine confidence can
still bind the wrong face.

This module extracts the target-side interface residues from a refolded
target–binder complex PDB/CIF and reports overlap with an intended hotspot
list. Pure Python — parses PDB ATOM/HETATM lines + (sparingly) CIF
``_atom_site`` blocks; no PyRosetta, no Biopython.

The CLI is ``binder-compare epitope``; the report joins the per-design
``epitope_match_fraction`` column by ``binder_id`` and surfaces it as an
advisory column. **Never reorders or drops** — the rank stays the rank.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Hotspot:
    """A single target hotspot. ``chain_id`` may be empty when the campaign
    uses a single-chain target — the comparison ignores chain if unspecified."""

    resnum: int
    chain_id: str = ""

    @classmethod
    def parse(cls, spec: str) -> Hotspot | None:
        """Parse 'A15', '15', 'A_15', or 'A:15' into a Hotspot. Returns None on garbage."""
        s = spec.strip()
        if not s:
            return None
        m = re.match(r"^([A-Za-z]?)[_:]?(-?\d+)$", s)
        if not m:
            return None
        chain = m.group(1).upper()
        try:
            return cls(resnum=int(m.group(2)), chain_id=chain)
        except ValueError:
            return None


def parse_hotspots(spec: str) -> list[Hotspot]:
    """Parse a comma-/whitespace-delimited hotspot list. Drops malformed entries silently."""
    if not spec:
        return []
    out: list[Hotspot] = []
    for piece in re.split(r"[,\s]+", spec):
        h = Hotspot.parse(piece)
        if h is not None:
            out.append(h)
    return out


# ─── PDB / CIF Cα coordinate extraction (no Biopython) ───────────────────────


@dataclass(frozen=True)
class _Atom:
    chain_id: str
    resnum: int
    x: float
    y: float
    z: float


def _parse_pdb_cas(text: str) -> list[_Atom]:
    """Return one _Atom per Cα ATOM record (skips HETATM, alt_locs other than A/' ')."""
    atoms: list[_Atom] = []
    for line in text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if len(line) < 54:
            continue
        if line[12:16].strip() != "CA":
            continue
        # alt_loc filter — keep only blank or "A" so we don't double-count
        alt = line[16] if len(line) > 16 else " "
        if alt not in (" ", "A"):
            continue
        chain = (line[21] if len(line) > 21 else " ").strip().upper()
        resnum_field = line[22:26].strip()
        try:
            resnum = int(resnum_field)
            x = float(line[30:38].strip())
            y = float(line[38:46].strip())
            z = float(line[46:54].strip())
        except ValueError:
            continue
        atoms.append(_Atom(chain_id=chain, resnum=resnum, x=x, y=y, z=z))
    return atoms


def _parse_cif_cas(text: str) -> list[_Atom]:
    """Minimal mmCIF ATOM-site Cα extractor (one loop_ at a time, no semicolon multilines)."""
    atoms: list[_Atom] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line == "loop_":
            i += 1
            cols: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("_atom_site."):
                cols.append(lines[i].strip().removeprefix("_atom_site."))
                i += 1
            if not cols:
                continue
            try:
                idx_group = cols.index("group_PDB")
                idx_label_atom = cols.index("label_atom_id")
                idx_chain = cols.index("auth_asym_id") if "auth_asym_id" in cols else cols.index("label_asym_id")
                idx_resnum = cols.index("auth_seq_id") if "auth_seq_id" in cols else cols.index("label_seq_id")
                idx_x = cols.index("Cartn_x")
                idx_y = cols.index("Cartn_y")
                idx_z = cols.index("Cartn_z")
            except ValueError:
                # Not an atom_site loop — skip ahead until next loop_ marker.
                while i < len(lines) and not lines[i].strip().startswith(("#", "loop_", "data_")):
                    i += 1
                continue
            while i < len(lines):
                row = lines[i].strip()
                if not row or row.startswith(("#", "loop_", "data_", "_atom_site.", "_")):
                    break
                # split honouring quoted tokens (CIF uses single-quoted strings)
                parts = _split_cif_row(row)
                if len(parts) < len(cols):
                    i += 1
                    continue
                if parts[idx_group] not in ("ATOM",):
                    i += 1
                    continue
                if parts[idx_label_atom].strip("'\"") != "CA":
                    i += 1
                    continue
                try:
                    resnum_field = parts[idx_resnum].strip("'\"")
                    if resnum_field in (".", "?"):
                        i += 1
                        continue
                    atoms.append(
                        _Atom(
                            chain_id=parts[idx_chain].strip("'\"").upper(),
                            resnum=int(resnum_field),
                            x=float(parts[idx_x]),
                            y=float(parts[idx_y]),
                            z=float(parts[idx_z]),
                        )
                    )
                except ValueError:
                    pass
                i += 1
        else:
            i += 1
    return atoms


def _split_cif_row(row: str) -> list[str]:
    """Split a CIF data row on whitespace, preserving 'single-quoted tokens'."""
    tokens: list[str] = []
    i = 0
    while i < len(row):
        if row[i].isspace():
            i += 1
            continue
        if row[i] in ("'", '"'):
            quote = row[i]
            end = row.find(quote, i + 1)
            if end == -1:
                tokens.append(row[i + 1 :])
                break
            tokens.append(row[i + 1 : end])
            i = end + 1
        else:
            end = i
            while end < len(row) and not row[end].isspace():
                end += 1
            tokens.append(row[i:end])
            i = end
    return tokens


def _parse_structure_cas(path: str | Path) -> list[_Atom]:
    """Auto-detect PDB vs CIF by suffix; return Cα atoms."""
    p = Path(path)
    text = p.read_text(errors="replace")
    if p.suffix.lower() in (".cif", ".mmcif"):
        return _parse_cif_cas(text)
    return _parse_pdb_cas(text)


# ─── Interface residue extraction ────────────────────────────────────────────


def extract_interface_residues(
    structure_path: str | Path,
    binder_chain: str,
    target_chain: str | None = None,
    cutoff: float = 8.0,
) -> set[tuple[str, int]]:
    """Return the set of TARGET residues whose Cα is within `cutoff` Å of any binder Cα.

    Args:
        structure_path: PDB or CIF file of the target–binder complex.
        binder_chain: 1-letter chain ID for the binder (e.g. "B" for AF3/ESMFold2
            refolds, "A" for Boltz-2 refolds — depends on engine).
        target_chain: 1-letter chain ID for the target. ``None`` (default)
            means "any chain that isn't the binder", which works for the
            standard 2-chain complex layout this pipeline produces.
        cutoff: Cα-Cα distance threshold (Å). Defaults to 8 Å — a generous
            interface-shell radius (PDB convention is ~5 Å for atom-atom
            contacts; we use 8 Å on Cα to compensate for not having sidechain
            atoms in this lightweight extractor).

    Returns:
        Set of (chain_id, resnum) tuples on the target side. Empty if the
        structure can't be parsed or chains are missing.
    """
    binder_chain = (binder_chain or "").upper()
    target_chain_norm = (target_chain or "").upper() if target_chain else None
    atoms = _parse_structure_cas(structure_path)
    if not atoms:
        return set()
    binder = [a for a in atoms if a.chain_id == binder_chain]
    if target_chain_norm:
        target = [a for a in atoms if a.chain_id == target_chain_norm]
    else:
        target = [a for a in atoms if a.chain_id != binder_chain]
    if not binder or not target:
        return set()
    cutoff_sq = cutoff * cutoff
    contacts: set[tuple[str, int]] = set()
    for t in target:
        for b in binder:
            dx = t.x - b.x
            dy = t.y - b.y
            dz = t.z - b.z
            if dx * dx + dy * dy + dz * dz <= cutoff_sq:
                contacts.add((t.chain_id, t.resnum))
                break  # one binder contact is enough to flag this target residue
    return contacts


# ─── Epitope-match fraction ──────────────────────────────────────────────────


def epitope_match(
    interface_residues: set[tuple[str, int]],
    hotspots: list[Hotspot],
) -> tuple[float, set[tuple[str, int]], set[tuple[str, int]]]:
    """Return ``(fraction, matched, off_target)``.

    ``fraction`` is |interface ∩ hotspots| / |hotspots| — recall on the intended
    site. ``matched`` is the intersection. ``off_target`` is interface
    residues NOT in the hotspot list.

    When ``hotspots`` is empty (no campaign-supplied target), returns
    ``(NaN, set(), interface_residues)`` so the caller can leave the column
    blank rather than reporting a misleading 0/0.
    """
    if not hotspots:
        return (math.nan, set(), set(interface_residues))
    hotspot_set: set[tuple[str, int]] = set()
    for h in hotspots:
        if h.chain_id:
            hotspot_set.add((h.chain_id, h.resnum))
        else:
            # When chain is unspecified, accept any chain (collapse by resnum).
            for chain_id, resnum in interface_residues:
                if resnum == h.resnum:
                    hotspot_set.add((chain_id, resnum))
            # Also seed the canonical "no chain" tuple so it counts as a missed hotspot.
            hotspot_set.add(("", h.resnum))
    # Match counts hotspots whose residue number appears in interface_residues
    # (chain match is optional when the hotspot has no chain).
    matched: set[tuple[str, int]] = set()
    interface_resnums = {r for _, r in interface_residues}
    for h in hotspots:
        if h.chain_id:
            if (h.chain_id, h.resnum) in interface_residues:
                matched.add((h.chain_id, h.resnum))
        elif h.resnum in interface_resnums:
            matched.add(("", h.resnum))
    fraction = len(matched) / len(hotspots)
    # Off-target = interface residues that don't appear in any intended hotspot.
    intended_resnums = {h.resnum for h in hotspots}
    off_target = {(c, r) for c, r in interface_residues if r not in intended_resnums}
    return (fraction, matched, off_target)
