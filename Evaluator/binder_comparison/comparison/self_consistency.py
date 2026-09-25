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
