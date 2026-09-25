"""Self-consistency RMSD — did the refold put the binder where the design did?

Every published RFdiffusion-family gate couples an interface-confidence term with
a self-consistency RMSD between the design model and its refold: RFD3's own gate
is ``target-aligned binder Cα-RMSD < 2.5 Å``, Bennett 2023 uses
``af2_complex_rmsd < 5``. It is the field's universal second axis, and we had
only the first.

**Superpose on the TARGET, not on the binder.** The target is the one molecule
that is the same in both structures, so aligning on it asks whether the binder is
in the same PLACE. Aligning the binder onto itself asks only whether it has the
same FOLD — and a binder that folds perfectly while docking on the wrong face
scores ~0 Å that way. Only the target-aligned number says whether the prediction
reproduced the designed complex.

Not ported: BindCraft's 3.5 Å binder-RMSD threshold. It is computed WITHOUT
superposition, on sub-poses in the trajectory frame, so it does not sit on a
scale anything here can reproduce. RFD3's 2.5 Å is target-aligned and transfers.
"""

from __future__ import annotations

import numpy as np

# RFD3's own protein-binder gate. NOTE: the RFD3 preprint states these cutoffs
# are taken "from [ref]" -- they are inherited, not RFD3-calibrated, and PMC
# strips the reference so the originating paper is not identifiable from it.
# Do not cite this as an RFD3-validated number.
SELF_CONSISTENCY_RMSD_MAX = 2.5


def _kabsch_transform(mobile: np.ndarray, reference: np.ndarray):
    """Rigid transform (rotation, mobile_centroid, reference_centroid) taking
    ``mobile`` onto ``reference``."""
    mc = mobile.mean(axis=0)
    rc = reference.mean(axis=0)
    cov = (mobile - mc).T @ (reference - rc)
    v, _s, wt = np.linalg.svd(cov)
    # Guard against a reflection: a mirrored "superposition" would report a small
    # RMSD for a mirror-image pose, which is not the same structure.
    d = np.sign(np.linalg.det(v @ wt))
    corr = np.diag([1.0, 1.0, d])
    rot = v @ corr @ wt
    return rot, mc, rc


def target_aligned_rmsd(
    design_target: np.ndarray,
    design_binder: np.ndarray,
    refold_target: np.ndarray,
    refold_binder: np.ndarray,
) -> float:
    """Binder Cα RMSD (Å) after superposing the refold onto the design BY TARGET.

    All four arrays are (N, 3) Cα coordinates. Returns NaN when a 1:1
    correspondence does not exist -- mismatched lengths or an empty set -- rather
    than a number from a partial comparison, which would be indistinguishable
    from a good score.
    """
    arrays = (design_target, design_binder, refold_target, refold_binder)
    if any(a is None or len(a) == 0 for a in arrays):
        return float("nan")
    if len(design_target) != len(refold_target) or len(design_binder) != len(refold_binder):
        return float("nan")

    rot, mobile_c, ref_c = _kabsch_transform(np.asarray(refold_target, float), np.asarray(design_target, float))
    moved = (np.asarray(refold_binder, float) - mobile_c) @ rot + ref_c
    # No second superposition: the transform came from the target, and applying
    # another one here is exactly the mistake this function exists to avoid.
    diff = moved - np.asarray(design_binder, float)
    return float(np.sqrt((diff * diff).sum() / len(diff)))


def passes_self_consistency(rmsd: float, threshold: float = SELF_CONSISTENCY_RMSD_MAX) -> bool | None:
    """True / False, or None when the RMSD could not be computed.

    None is not a failure: a design whose structures could not be compared has
    not been measured against this axis.
    """
    if rmsd is None or np.isnan(rmsd):
        return None
    return bool(rmsd <= threshold)


def _chains_from_pdb(pdb_text: str) -> dict[str, tuple[str, list[list[float]]]]:
    """{chain_id: (1-letter sequence, [Cα xyz, ...])} from PDB text.

    Pure text on purpose: gemmi is deliberately not a ``binder-eval`` dependency
    (see Evaluator/pyproject.toml), and this runs in the report path.
    """
    from .target_analysis import _THREE_TO_ONE

    chains: dict[str, tuple[list[str], list[list[float]]]] = {}
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        aa = _THREE_TO_ONE.get(line[17:20].strip().upper())
        if aa is None:
            continue
        cid = line[21:22].strip()
        seq, xyz = chains.setdefault(cid, ([], []))
        seq.append(aa)
        try:
            xyz.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        except ValueError:
            seq.pop()
    return {c: ("".join(s), x) for c, (s, x) in chains.items()}


def split_target_binder(pdb_text: str, binder_sequence: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (target Cα, binder Cα), finding the binder BY SEQUENCE.

    Chain letters differ by producer -- Boltz-2 puts the binder in A,
    AF3/ESMFold2 in B, and a design tool uses whatever it wrote -- and CLAUDE.md
    lists that mismatch as a live bug source. Matching on the sequence removes
    the convention entirely. Every chain that is not the binder is target, so a
    multi-chain target is not silently truncated to one chain.

    Returns two empty arrays when no chain carries the binder sequence.
    """
    want = "".join(binder_sequence.split()).upper()
    chains = _chains_from_pdb(pdb_text)

    binder_id = next((c for c, (seq, _) in chains.items() if seq == want), None)
    if binder_id is None:
        # Modelled residues can be a subset of the designed sequence.
        binder_id = next((c for c, (seq, _) in chains.items() if seq and (seq in want or want in seq)), None)
    if binder_id is None:
        return np.zeros((0, 3)), np.zeros((0, 3))

    binder = np.asarray(chains[binder_id][1], dtype=float)
    target_xyz = [xyz for c, (_seq, coords) in chains.items() if c != binder_id for xyz in coords]
    return np.asarray(target_xyz, dtype=float).reshape(-1, 3), binder


_ENGINE_PDB_COLS = {"boltz": "boltz_pdb", "af3": "af3_pdb", "esmfold2": "esmfold2_pdb"}


def _resolve(path: str, base_dir):
    """Find a recorded structure path, tolerating a transplanted pool.

    Refold CSVs record paths from the machine that produced them, so match on
    progressively shorter tails under base_dir -- the same approach the PAE
    loader uses.
    """
    from pathlib import Path

    if not path or (isinstance(path, float) and np.isnan(path)):
        return None
    p = Path(str(path))
    if p.is_absolute() and p.exists():
        return p
    base = Path(base_dir)
    parts = p.parts[1:] if p.is_absolute() else p.parts
    for start in range(len(parts)):
        candidate = base.joinpath(*parts[start:])
        if candidate.exists():
            return candidate
    return None


def _design_index(design_root) -> dict[str, object]:
    """{sequence: path} from the manifests collect_design_structures writes."""
    import csv
    from pathlib import Path

    root = Path(design_root)
    index: dict[str, object] = {}
    if not root.is_dir():
        return index
    for manifest in sorted(root.rglob("manifest.csv")):
        try:
            with manifest.open(newline="") as fh:
                for row in csv.DictReader(fh):
                    seq = (row.get("sequence") or "").strip().upper()
                    rel = (row.get("path") or "").strip()
                    if seq and rel:
                        index.setdefault(seq, manifest.parent / rel)
        except OSError:
            continue
    return index


def annotate_self_consistency(df, design_root, base_dir, threshold: float = SELF_CONSISTENCY_RMSD_MAX):
    """Add target-aligned design-vs-refold RMSD columns. Advisory: never drops.

    Per engine, ``<engine>_self_consistency_rmsd``; overall
    ``self_consistency_rmsd`` (the BEST agreement across engines, matching the
    field's best-of-N convention), ``passes_self_consistency`` (NA when no
    comparison was possible) and ``would_exclude_self_consistency``.
    """
    out = df.copy()
    index = _design_index(design_root)

    best: list[float] = []
    verdicts: list[bool | None] = []
    for _, row in out.iterrows():
        seq = str(row.get("sequence", "")).strip().upper()
        design_path = index.get(seq)
        design_text = None
        if design_path is not None:
            try:
                design_text = design_path.read_text()
            except OSError:
                design_text = None

        per_engine: list[float] = []
        for engine, col in _ENGINE_PDB_COLS.items():
            rmsd = float("nan")
            if design_text is not None and col in row.index:
                refold_path = _resolve(row.get(col), base_dir)
                if refold_path is not None:
                    try:
                        d_t, d_b = split_target_binder(design_text, seq)
                        r_t, r_b = split_target_binder(refold_path.read_text(), seq)
                        rmsd = target_aligned_rmsd(d_t, d_b, r_t, r_b)
                    except OSError:
                        rmsd = float("nan")
            if not np.isnan(rmsd):
                out.loc[row.name, f"{engine}_self_consistency_rmsd"] = round(rmsd, 3)
                per_engine.append(rmsd)

        overall = min(per_engine) if per_engine else float("nan")
        best.append(round(overall, 3) if per_engine else float("nan"))
        verdicts.append(passes_self_consistency(overall, threshold))

    out["self_consistency_rmsd"] = best
    out["passes_self_consistency"] = pd_array_boolean(verdicts)
    # Shadow mode: a design nothing could compare is never excluded.
    out["would_exclude_self_consistency"] = [v is False for v in verdicts]
    return out


def pd_array_boolean(values):
    """Nullable boolean column — True / False / NA kept distinct."""
    import pandas as pd

    return pd.array(values, dtype="boolean")
