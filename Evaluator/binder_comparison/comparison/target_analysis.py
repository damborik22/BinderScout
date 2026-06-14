"""Target analysis — turn a target structure into autosize/campaign suggestions.

Grafted from BindMaster 2's Target Analyst. It produces an **advisory** 0–1 difficulty
score and, from it, suggested autosize parameters (per-tool N, gate tier, extra tools),
a binder-length range, and candidate hotspots. BindMaster 2 never pinned the difficulty
formula, so the one here is explicit and documented — a heuristic to *seed* a campaign,
not an oracle. Geometry uses Cα neighbor density (a dependency-free SASA proxy): few
neighbours = exposed/flat, a middle band = concave pocket rim, many = buried core.
"""

from __future__ import annotations

import numpy as np

# Difficulty sub-score weights (sum to 1.0). Documented so they can be tuned.
_W_LENGTH, _W_DISORDER, _W_FLAT = 0.45, 0.25, 0.30


def neighbor_counts(coords, radius: float = 10.0) -> np.ndarray:
    """Per-residue count of other Cα within ``radius`` Å (self excluded)."""
    c = np.asarray(coords, dtype=float)
    if c.ndim != 2 or c.shape[1] != 3:
        raise ValueError(f"coords must be (N,3), got {c.shape}")
    if c.shape[0] == 0:
        return np.zeros(0, dtype=int)
    d = np.linalg.norm(c[:, None, :] - c[None, :, :], axis=-1)
    return (d <= radius).sum(axis=1) - 1  # minus self


def flat_surface_fraction(counts, exposed_max: int = 9) -> float:
    """Fraction of residues that are exposed/flat (few neighbours ≤ ``exposed_max``)."""
    counts = np.asarray(counts)
    if counts.size == 0:
        return 0.0
    return float((counts <= exposed_max).mean())


def difficulty_score(*, length: int, disorder_fraction: float = 0.0, flat_fraction: float = 0.0) -> float:
    """Advisory 0–1 target difficulty.

    Larger targets, more disorder, and flatter (pocket-less) surfaces are harder. Each
    sub-score is clamped to [0,1] then weighted (length 0.45, disorder 0.25, flat 0.30):
    length maps 100 aa → 0 and 400 aa → 1.
    """
    f_len = min(max((length - 100) / 300.0, 0.0), 1.0)
    f_dis = min(max(disorder_fraction, 0.0), 1.0)
    f_flat = min(max(flat_fraction, 0.0), 1.0)
    return round(_W_LENGTH * f_len + _W_DISORDER * f_dis + _W_FLAT * f_flat, 3)


def classify_difficulty(score: float) -> str:
    """``easy`` (<0.4), ``medium`` (0.4–0.7), ``hard`` (>0.7)."""
    if score < 0.4:
        return "easy"
    if score <= 0.7:
        return "medium"
    return "hard"


def suggest_campaign(score: float) -> dict:
    """Suggested autosize params from difficulty: easier → more designs, stricter gate.

    Harder targets get a smaller per-tool target, a more permissive gate (you can't be
    picky), and extra diverse tools.
    """
    band = classify_difficulty(score)
    table = {
        "easy": {"n_target": 250, "gate_tier": "strict", "add_tools": []},
        "medium": {"n_target": 100, "gate_tier": "default", "add_tools": ["proteina-complexa"]},
        "hard": {
            "n_target": 50,
            "gate_tier": "permissive",
            "add_tools": ["proteina-complexa", "rfd3", "protein-hunter"],
        },
    }
    return {"difficulty_band": band, **table[band]}


def suggest_binder_length(score: float) -> tuple[int, int]:
    """Suggested binder length range (aa); harder targets allow longer binders."""
    band = classify_difficulty(score)
    return {"easy": (60, 100), "medium": (70, 130), "hard": (80, 160)}[band]


def pick_hotspots(counts, residue_ids, n: int = 4, pocket_lo: int = 10, pocket_hi: int = 18) -> list:
    """Candidate hotspot residues: surface residues in the concave 'pocket-rim' neighbour band.

    Returns up to ``n`` residue ids whose neighbour count is in ``[pocket_lo, pocket_hi]``,
    most-concave (highest count in band) first — accessible but pocket-like.
    """
    counts = np.asarray(counts)
    candidates = [(int(c), rid) for c, rid in zip(counts, residue_ids) if pocket_lo <= c <= pocket_hi]
    candidates.sort(key=lambda cr: -cr[0])  # most concave first
    return [rid for _, rid in candidates[:n]]
