"""Sequence-only advisory columns, computed before any GPU time (2.0 Part AA).

Two panels, both derived from the ``sequence`` column that is already in the
frame:

* **ProtParam panel** (item D7) — molecular weight, pI, extinction coefficient,
  GRAVY, aromatic fraction. The computation already existed in
  :mod:`binder_comparison.comparison.wetlab`; it was only ever used to build the
  wet-lab plan, so none of it reached ``metrics.csv``.

* **Composition gate** (item D8) — the per-sequence form of the pool-level check
  in ``tools/rfd3_gate.py``. That one averages over a whole pool and returns a
  single bool, which cannot annotate a design.

Neither panel joins anything. They are computed from a column the frame already
has, which is what keeps them clear of the row-multiplication defect that
corrupted ``rank`` (see ``cli/report.py::_merge_by_sequence``).

**Shadow mode.** ``annotate_composition`` emits ``would_exclude_composition``
and excludes nothing. Per the 2.0 plan a pre-GPU filter may only begin excluding
once it has been shown to remove zero confirmed binders on a calibration pool,
and the number that decides is the false-negative rate on confirmed binders, not
accuracy. No such pool exists yet, so this stays mark-only.
"""

from __future__ import annotations

import collections
import math

import pandas as pd

from .wetlab import sequence_properties

# Thresholds carried over from tools/rfd3_gate.py, which recorded them against a
# validated pool and a known-broken one. The Pro+Gly and hydrophobic bounds are
# the load-bearing pair: CLAUDE.md records that a Pro/Gly coil scores Ala 0.016
# and Shannon entropy 2.47 and so passes both of those checks, which is why the
# gate must not be built on alanine and entropy alone.
COMPOSITION_THRESHOLDS: dict[str, float] = {
    "max_ala_frac": 0.20,  # validated pool 0.102
    "max_pro_gly_frac": 0.12,  # validated 0.055; broken pool 0.286
    "max_glu_arg_frac": 0.36,  # poly-Glu is where an alanine bias relocates
    "min_hydrophobic_frac": 0.40,  # validated ~0.50; broken pool 0.243
    "min_entropy": 2.40,  # NOT sufficient alone - see above
}

_HYDROPHOBIC = "AVILMFWY"

# Column names deliberately avoid native_dG / native_dSASA /
# native_shape_complementarity: compute_composite_scores() and
# apply_screening_thresholds() in scoring.py fire on the PRESENCE of those
# names, so an advisory column named into them would silently become a ranking
# input.
_PANEL_COLUMNS = {
    "length": "native_length",
    "molecular_weight": "native_mw",
    "isoelectric_point": "native_pi",
    "extinction_280": "native_extinction_280",
    "gravy": "native_gravy",
    "aromatic_fraction": "native_aromatic_fraction",
}


def _fraction(seq: str, residues: str) -> float:
    if not seq:
        return 0.0
    return sum(seq.count(a) for a in residues) / len(seq)


def _shannon_entropy(seq: str) -> float:
    if not seq:
        return 0.0
    n = len(seq)
    counts = collections.Counter(seq)
    return -sum((v / n) * math.log(v / n) for v in counts.values())


def composition_features(seq: str) -> dict:
    """Per-sequence composition features. Pool-independent by construction."""
    seq = (seq or "").strip().upper()
    return {
        "comp_ala_frac": round(_fraction(seq, "A"), 4),
        "comp_pro_gly_frac": round(_fraction(seq, "PG"), 4),
        "comp_glu_arg_frac": round(_fraction(seq, "ER"), 4),
        "comp_hydrophobic_frac": round(_fraction(seq, _HYDROPHOBIC), 4),
        "comp_entropy": round(_shannon_entropy(seq), 4),
        "comp_has_gggg": "GGGG" in seq,
    }


def composition_verdict(features: dict) -> tuple[bool, str]:
    """(would_exclude, reason). Reason names every failing check, not just the
    first — a design usually fails several and the others are informative."""
    t = COMPOSITION_THRESHOLDS
    reasons = []
    if features["comp_ala_frac"] > t["max_ala_frac"]:
        reasons.append("ala")
    if features["comp_pro_gly_frac"] > t["max_pro_gly_frac"]:
        reasons.append("pro_gly")
    if features["comp_glu_arg_frac"] > t["max_glu_arg_frac"]:
        reasons.append("glu_arg")
    if features["comp_hydrophobic_frac"] < t["min_hydrophobic_frac"]:
        reasons.append("hydrophobic")
    if features["comp_entropy"] < t["min_entropy"]:
        reasons.append("entropy")
    if features["comp_has_gggg"]:
        reasons.append("gggg_run")
    return bool(reasons), ",".join(reasons)


def annotate_sequence_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Add the ProtParam panel. Row count is never changed."""
    if "sequence" not in df.columns or df.empty:
        return df
    out = df.copy()
    props = [sequence_properties(s if isinstance(s, str) else "") for s in out["sequence"]]
    for src, dest in _PANEL_COLUMNS.items():
        out[dest] = [p.get(src) for p in props]
    return out


def annotate_composition(df: pd.DataFrame) -> pd.DataFrame:
    """Add the composition features plus the shadow-mode flag and its reason."""
    if "sequence" not in df.columns or df.empty:
        return df
    out = df.copy()
    feats = [composition_features(s if isinstance(s, str) else "") for s in out["sequence"]]
    for key in feats[0]:
        out[key] = [f[key] for f in feats]
    verdicts = [composition_verdict(f) for f in feats]
    out["would_exclude_composition"] = [v[0] for v in verdicts]
    out["composition_reason"] = [v[1] for v in verdicts]
    return out
