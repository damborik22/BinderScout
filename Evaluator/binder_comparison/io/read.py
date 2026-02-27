"""Input readers for FASTA, CSV, NPY, and NPZ files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd


def read_fasta(path: str | Path) -> list[tuple[str, str]]:
    """Parse a FASTA file.

    Returns a list of (header, sequence) tuples.
    The header does NOT include the leading '>'.
    Supports multi-line sequences and FASTA-style enriched headers
    (e.g. '>id  key=val  key2=val2').
    """
    path = Path(path)
    entries: list[tuple[str, str]] = []
    header = None
    seq_parts: list[str] = []

    with path.open() as fh:
        for line in fh:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    entries.append((header, "".join(seq_parts)))
                header = line[1:]
                seq_parts = []
            else:
                seq_parts.append(line.strip())

    if header is not None:
        entries.append((header, "".join(seq_parts)))

    return entries


def iter_fasta_sequences(path: str | Path) -> Iterator[tuple[str, str]]:
    """Lazily yield (header, sequence) from a FASTA file."""
    yield from read_fasta(path)


def read_csv_safe(path: str | Path, **kwargs) -> pd.DataFrame:
    """Read a CSV, returning an empty DataFrame on failure."""
    try:
        return pd.read_csv(path, **kwargs)
    except Exception as exc:
        import warnings
        warnings.warn(f"Could not read {path}: {exc}")
        return pd.DataFrame()


def read_npy(path: str | Path) -> np.ndarray:
    """Load a .npy file."""
    return np.load(str(path), allow_pickle=False)


def read_npz(path: str | Path) -> dict[str, np.ndarray]:
    """Load a .npz file, returning a dict of arrays."""
    data = np.load(str(path), allow_pickle=False)
    return dict(data)


def parse_sequences_any_format(
    path: str | Path,
) -> list[tuple[str, str]]:
    """Parse binder sequences from any common input format.

    Supported formats (auto-detected):
      - FASTA (.fasta / .fa / .faa, or any file whose first sequence line starts with '>')
      - CSV / TSV with a 'sequence' column (with optional 'id'/'name' column)
      - One sequence per line (plain text)
      - Comma-separated sequences (all on one line or spread across lines)
      - Semicolon-separated sequences

    Returns a list of (id, sequence) tuples with upper-cased sequences.
    Rows that are not valid amino-acid sequences are silently skipped.
    """
    _AA = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYXUBZOacdefghiklmnpqrstvwyxubzo]+$")

    def _is_seq(s: str) -> bool:
        s = s.strip()
        return len(s) >= 5 and bool(_AA.match(s))

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = [ln.rstrip() for ln in text.splitlines()]
    nonempty = [ln for ln in lines if ln.strip()]

    if not nonempty:
        return []

    # ------------------------------------------------------------------ FASTA
    if any(ln.startswith(">") for ln in nonempty):
        return read_fasta(path)

    # -------------------------------------------------------------- CSV / TSV
    first = nonempty[0].lower()
    sep = "\t" if "\t" in first else ","
    if sep in first and any(kw in first for kw in ("sequence", "seq", "binder")):
        import io as _io
        df = pd.read_csv(_io.StringIO(text), sep=sep)
        df.columns = df.columns.str.strip().str.lower()
        seq_col = next(
            (c for c in df.columns if c in ("sequence", "seq", "binder_seq",
                                             "binder_sequence")),
            None,
        )
        if seq_col:
            id_col = next(
                (c for c in df.columns if c in ("id", "name", "binder_id",
                                                 "design_id")),
                None,
            )
            result = []
            for i, row in df.iterrows():
                seq = str(row[seq_col]).strip().upper()
                if not _is_seq(seq):
                    continue
                sid = str(row[id_col]).strip() if id_col else f"seq_{i+1:04d}"
                result.append((sid, seq))
            return result

    # ---------------------------------------- comma / semicolon separated
    flat_text = " ".join(nonempty)
    for delim in (",", ";"):
        if delim in flat_text:
            parts = [p.strip().upper() for p in flat_text.split(delim)]
            result = []
            for i, p in enumerate(parts):
                if _is_seq(p):
                    result.append((f"seq_{i+1:04d}", p))
            if result:
                return result

    # ---------------------------------------- one sequence per line
    result = []
    idx = 1
    for ln in nonempty:
        seq = ln.strip().upper()
        if _is_seq(seq):
            result.append((f"seq_{idx:04d}", seq))
            idx += 1
    return result


_THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "SEC": "U", "PYL": "O", "MSE": "M", "HSD": "H", "HSE": "H",
    "HSP": "H", "HIE": "H", "HID": "H", "HIP": "H",
}


def parse_pdb_sequence(path: str | Path) -> str:
    """Extract the target amino acid sequence from a PDB or mmCIF file.

    For PDB: tries SEQRES records first, falls back to ATOM CA records.
    For CIF: reads _entity_poly sequence fields, falls back to _atom_site CA records.
    Returns a single uppercase string of one-letter codes.
    Raises ValueError if no sequence can be extracted.
    """
    path = Path(path)
    if path.suffix.lower() in (".cif", ".mmcif"):
        return _sequence_from_cif(path)
    return _sequence_from_pdb(path)


def _sequence_from_pdb(path: Path) -> str:
    lines = path.read_text(errors="replace").splitlines()

    # Try SEQRES first
    seqres: dict[str, list[str]] = {}
    for ln in lines:
        if ln.startswith("SEQRES"):
            chain = ln[11].strip()
            seqres.setdefault(chain, []).extend(ln[19:].split())

    if seqres:
        longest = max(seqres.values(), key=len)
        seq = "".join(_THREE_TO_ONE.get(r, "X") for r in longest)
        if len(seq) >= 5:
            return seq

    # Fallback: ATOM CA records
    seen: dict[tuple[str, int], str] = {}
    for ln in lines:
        if ln.startswith(("ATOM  ", "HETATM")) and ln[12:16].strip() == "CA":
            chain = ln[21]
            try:
                resnum = int(ln[22:26])
            except ValueError:
                continue
            key = (chain, resnum)
            if key not in seen:
                seen[key] = _THREE_TO_ONE.get(ln[17:20].strip(), "X")

    if not seen:
        raise ValueError(f"No sequence found in {path}")
    return "".join(seen[k] for k in sorted(seen))


def _cif_tokenize(text: str) -> list[str]:
    """Tokenize an mmCIF file into a flat list of string tokens.

    Handles:
    - Multi-line semicolon-delimited values (';' at start of line)
    - Single- and double-quoted inline strings
    - Inline comments (#)
    """
    tokens: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Multi-line text value: starts with ; at column 0
        if line.startswith(";"):
            parts = [line[1:]]
            i += 1
            while i < len(lines) and not lines[i].startswith(";"):
                parts.append(lines[i])
                i += 1
            tokens.append("\n".join(parts).rstrip())
            i += 1  # skip closing ;
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
                break  # inline comment — rest of line ignored
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


def _sequence_from_cif(path: Path) -> str:
    text = path.read_text(errors="replace")

    # Try parsing the _entity_poly loop_ block with a proper tokenizer
    seq = _cif_entity_poly_seq(text)
    if seq and len(seq) >= 5:
        return seq

    # Fallback: parse _atom_site CA records via tokenizer
    return _cif_atom_site_seq(text, path)


def _cif_entity_poly_seq(text: str) -> str | None:
    """Extract the longest pdbx_seq_one_letter_code_can from the _entity_poly loop."""
    tokens = _cif_tokenize(text)
    i = 0
    while i < len(tokens):
        if tokens[i].lower() != "loop_":
            i += 1
            continue
        i += 1
        # Collect column names
        cols: list[str] = []
        while i < len(tokens) and tokens[i].startswith("_"):
            cols.append(tokens[i].lower())
            i += 1
        if not any(c.startswith("_entity_poly.") for c in cols):
            continue
        # Find the preferred sequence column
        seq_col: int | None = None
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
        seqs: list[str] = []
        while i < len(tokens):
            tok = tokens[i]
            # End of this loop block
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


def _cif_atom_site_seq(text: str, path: Path) -> str:
    """Fallback: extract sequence from _atom_site CA records using the tokenizer."""
    tokens = _cif_tokenize(text)
    i = 0
    while i < len(tokens):
        if tokens[i].lower() != "loop_":
            i += 1
            continue
        i += 1
        cols: list[str] = []
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
        seen: dict[tuple[str, int], str] = {}
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
                    seen[key] = _THREE_TO_ONE.get(resname, "X")
            i += n_cols
        if seen:
            return "".join(seen[k] for k in sorted(seen))
    raise ValueError(f"No sequence found in {path}")


def convert_cif_to_pdb(cif_path: str | Path, pdb_path: str | Path) -> Path:
    """Convert an mmCIF file to PDB format using BioPython.

    BioPython is available in the binder-eval-af2 environment (via colabdesign).
    Raises ImportError if BioPython is not installed.
    """
    from Bio.PDB import MMCIFParser, PDBIO  # type: ignore

    cif_path = Path(cif_path)
    pdb_path = Path(pdb_path)
    pdb_path.parent.mkdir(parents=True, exist_ok=True)

    parser = MMCIFParser(QUIET=True)
    structure = parser.get_structure(cif_path.stem, str(cif_path))

    io = PDBIO()
    io.set_structure(structure)
    io.save(str(pdb_path))
    return pdb_path


def parse_fasta_header_tags(header: str) -> dict[str, str]:
    """Extract key=value tags from an enriched FASTA header.

    Example:
        '>refold1_abc  iptm=0.8120  bt_ipsae=0.6500  pdb=foo.pdb'
    Returns {'iptm': '0.8120', 'bt_ipsae': '0.6500', 'pdb': 'foo.pdb'}
    """
    return dict(re.findall(r"(\w+)=(\S+)", header))
