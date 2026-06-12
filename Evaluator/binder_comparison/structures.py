"""Structure helpers: index design structures by binder sequence + collect them.

Used by ``binder-compare extract --collect-structures`` to gather each design's
ORIGINAL complex structure into a per-tool folder alongside the FASTA — so the
report can show the tool's own design (matched by binder *sequence*, independent
of filename/folder layout). Everything is written out as PDB (cif/.gz converted
via gemmi) so the report's PDB parser can read it.
"""

from __future__ import annotations

import warnings
from pathlib import Path

_AA = set("ACDEFGHIKLMNPQRSTVWY")
_STRUCT_GLOBS = ("*.pdb", "*.cif", "*.pdb.gz", "*.cif.gz")


def _clean(seq: str) -> str:
    return "".join(c for c in seq.upper() if c in _AA)


def _chain_sequences(path: Path) -> dict[str, str]:
    """Return {chain_id: cleaned 1-letter sequence} via gemmi (handles pdb/cif/.gz)."""
    import gemmi

    try:
        st = gemmi.read_structure(str(path))
    except Exception:
        return {}
    if len(st) == 0:
        return {}
    st.setup_entities()
    out: dict[str, str] = {}
    for chain in st[0]:
        try:
            s = _clean(chain.get_polymer().make_one_letter_sequence())
        except Exception:
            s = ""
        if s:
            out[chain.name] = s
    return out


def seq_to_structure_index(struct_dir: str | Path, max_files: int = 8000) -> dict[str, Path]:
    """Build {chain_sequence -> structure_path} over all structures under *struct_dir*.

    Indexes every chain (first-seen wins). A design's binder sequence is then a
    direct key lookup; because the binder sequence differs from the target, it
    resolves to the structure containing that binder.
    """
    struct_dir = Path(struct_dir)
    files: list[Path] = []
    for g in _STRUCT_GLOBS:
        files += list(struct_dir.rglob(g))
    index: dict[str, Path] = {}
    for p in files[:max_files]:
        if "MONOMER_ONLY" in p.name:
            continue
        for s in _chain_sequences(p).values():
            index.setdefault(s, p)
    return index


def collect_design_structures(
    input_dir: str | Path,
    sequences,
    out_dir: str | Path,
    *,
    max_files: int = 8000,
) -> int:
    """Copy each design's ORIGINAL complex structure (matched by binder sequence)
    into *out_dir* as PDB. Returns the number matched + written.

    Tools whose structures don't carry the design sequence (e.g. RFD3 diffusion
    backbones) simply match nothing → 0 collected → the report falls back to the
    refold structure for them, which is correct.
    """
    import gemmi

    out_dir = Path(out_dir)
    index = seq_to_structure_index(input_dir, max_files=max_files)
    if not index:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    written: set[str] = set()
    n = 0
    for i, seq in enumerate(sequences):
        key = _clean(seq)
        hit = index.get(key)
        if hit is None or key in written:
            continue
        dest = out_dir / f"design_{i:04d}.pdb"
        try:
            if hit.suffix.lower() == ".pdb" and not hit.name.endswith(".gz"):
                dest.write_text(hit.read_text())
            else:
                st = gemmi.read_structure(str(hit))
                st.setup_entities()
                dest.write_text(st.make_pdb_string())
            written.add(key)
            n += 1
        except Exception as exc:  # pragma: no cover - defensive
            warnings.warn(f"collect_design_structures: failed on {hit}: {exc}")
    return n
