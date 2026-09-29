"""Pairwise TM-scores between designed binders, via Foldseek.

Supplies the ``tm_lookup`` that :func:`design_families.annotate_structural_families`
needs. Kept apart from that module so the grouping logic stays pure and testable and all
the I/O -- binary discovery, chain extraction, subprocess, parsing -- lives here.

Three things this gets right that are easy to get wrong:

**The binder chain is found BY SEQUENCE, never by letter.** ``self_consistency`` records
why: Boltz-2 writes the binder as chain A, AF3 and ESMFold2 as chain B, and a design tool
uses whatever it likes. CLAUDE.md lists that mismatch as a live bug source.

**Only the binder chain is compared.** Every complex in a pool shares the same target, so
clustering whole complexes measures the target, not the designs -- it returns "everything
is similar" and the answer is meaningless. This was got wrong once, on 2026-09-28, and it
produced the exact opposite of the correct result.

**Absence is not failure.** Foldseek ships only inside ``Proteina-Complexa/.venv`` on
x86, there is none on aarch64, and refold PDBs exist only where an engine ran. Any of
those returns ``None`` and the structural columns become NA. A diagnostic that cannot be
computed must never fail a report.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..io.design_ids import safe_stem

#: Where to look for the binary, in order. ``$FOLDSEEK_BIN`` wins, then anything on
#: PATH, then Proteina-Complexa's venv -- a *design* tool's environment, which is the
#: wrong home for a shared utility and is used only as a last resort.
_PC_VENV_FOLDSEEK = "Proteina-Complexa/.venv/bin/foldseek"


def find_foldseek(repo_root: Path | None = None) -> str | None:
    """Locate a usable foldseek, or None."""
    explicit = os.environ.get("FOLDSEEK_BIN")
    if explicit and Path(explicit).is_file() and os.access(explicit, os.X_OK):
        return explicit
    on_path = shutil.which("foldseek")
    if on_path:
        return on_path
    root = repo_root or Path(__file__).resolve().parents[3]
    candidate = root / _PC_VENV_FOLDSEEK
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _binder_only_pdb(pdb_text: str, binder_sequence: str) -> str | None:
    """The ATOM records of the chain whose sequence is *binder_sequence*.

    Returns None when no chain matches -- a structure whose binder cannot be identified
    is skipped rather than guessed at.
    """
    from .self_consistency import _chains_from_pdb

    target = "".join(ch for ch in str(binder_sequence).upper() if ch.isalpha())
    if not target:
        return None
    try:
        chains = _chains_from_pdb(pdb_text)
    except Exception:
        return None

    best = None
    for chain_id, (seq, _coords) in chains.items():
        if seq == target:
            best = chain_id
            break
        # Refolded chains can differ from the requested sequence by terminal handling,
        # so fall back to containment before giving up.
        if best is None and target and (target in seq or seq in target) and len(seq) >= 0.8 * len(target):
            best = chain_id
    if best is None:
        return None

    keep = [ln for ln in pdb_text.splitlines() if ln.startswith(("ATOM", "HETATM")) and ln[21:22] == best]
    return "\n".join(keep) + "\nEND\n" if keep else None


def build_tm_lookup(
    df,
    *,
    base_dir,
    pdb_cols: tuple[str, ...] = ("boltz_pdb", "af3_pdb", "esmfold2_pdb", "pdb"),
    id_col: str = "binder_id",
    sequence_col: str = "sequence",
    foldseek_bin: str | None = None,
    timeout: int = 900,
):
    """Return ``f(id_a, id_b) -> float`` over binder-chain TM-scores, or None.

    None means "not computable here" -- no foldseek, no resolvable structures, or fewer
    than two binders with an identifiable binder chain.
    """
    from .self_consistency import _resolve

    binary = foldseek_bin or find_foldseek()
    if binary is None or df is None or len(df) < 2:
        return None
    if id_col not in df.columns or sequence_col not in df.columns:
        return None

    workdir = Path(tempfile.mkdtemp(prefix="binderscout_foldseek_"))
    pdb_dir = workdir / "binders"
    pdb_dir.mkdir()

    written = 0
    for _, row in df.iterrows():
        text = None
        for col in pdb_cols:
            if col not in df.columns:
                continue
            resolved = _resolve(row.get(col), base_dir)
            if resolved is not None:
                try:
                    text = Path(resolved).read_text()
                    break
                except OSError:
                    continue
        if text is None:
            continue
        only = _binder_only_pdb(text, row.get(sequence_col, ""))
        if only is None:
            continue
        # The file stem is the join key, so it must survive a round trip through
        # foldseek's output unchanged. Shared with the refold engines, which name their
        # saved structures with the same function.
        (pdb_dir / f"{safe_stem(row[id_col])}.pdb").write_text(only)
        written += 1

    if written < 2:
        shutil.rmtree(workdir, ignore_errors=True)
        return None

    aln = workdir / "aln.tsv"
    try:
        subprocess.run(
            [
                binary,
                "easy-search",
                str(pdb_dir),
                str(pdb_dir),
                str(aln),
                str(workdir / "tmp"),
                "--format-output",
                "query,target,alntmscore",
                "-e",
                "1000",
                "--exhaustive-search",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(workdir, ignore_errors=True)
        return None

    scores: dict[tuple[str, str], float] = {}
    try:
        for line in aln.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            q, t, tm = parts[0], parts[1], parts[2]
            if q == t:
                continue
            try:
                value = float(tm)
            except ValueError:
                continue
            key = (q, t) if q < t else (t, q)
            # Foldseek reports each pair twice, once per direction; keep the stronger.
            scores[key] = max(scores.get(key, 0.0), value)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if not scores:
        return None

    def lookup(a: str, b: str) -> float:
        sa, sb = safe_stem(a), safe_stem(b)
        return scores.get((sa, sb) if sa < sb else (sb, sa), 0.0)

    return lookup
