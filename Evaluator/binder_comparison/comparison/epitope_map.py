"""Target binding-map analysis — *where* on the target the pool binds.

Pure functions (no NGL/HTML). Consumes the per-design target-side interface
residues produced by ``binder-compare epitope`` and produces:

- **Aggregate footprint**: per-residue contact frequency across the whole pool —
  "how many designs touch this target residue" (the heatmap data).
- **Binding modes**: designs grouped by *footprint* similarity (Jaccard on the
  contacted-residue sets), each summarised by its consensus residues + a
  representative design. This is the structural analogue of the sequence
  ``family_id`` clustering — two designs land in the same mode when they bind the
  same patch, regardless of sequence.

Cluster-by-footprint (not by sequence) is the meaningful grouping for "which
families bind where": at a 0.7 sequence-Jaccard the pool is near-all-singletons,
but many of those distinct sequences converge on the same epitope.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable, Mapping


def parse_residue_tokens(value: object) -> set[int]:
    """Parse a comma list of residue tokens to a set of residue numbers.

    Handles both bare (``18``) and chain-prefixed (``A18``) tokens — the epitope
    CSV mixes them (matched residues are bare, off-target keep the chain letter).
    """
    out: set[int] = set()
    if not isinstance(value, str):
        return out
    for tok in value.split(","):
        tok = tok.strip()
        i = 0
        while i < len(tok) and tok[i].isalpha():
            i += 1
        num = tok[i:]
        if num.isdigit():
            out.add(int(num))
    return out


def design_footprints(rows: Iterable[Mapping]) -> dict[str, set[int]]:
    """Map binder_id -> set of contacted target residues (matched ∪ off-target)."""
    footprints: dict[str, set[int]] = {}
    for r in rows:
        residues = parse_residue_tokens(r.get("epitope_matched_residues")) | parse_residue_tokens(
            r.get("epitope_off_target_residues")
        )
        bid = str(r.get("binder_id", "")).strip()
        if bid and residues:
            footprints[bid] = residues
    return footprints


def residue_frequency(footprints: Mapping[str, set[int]]) -> dict[int, int]:
    """Per-residue contact count across all designs."""
    counter: collections.Counter[int] = collections.Counter()
    for residues in footprints.values():
        counter.update(residues)
    return dict(counter)


def _jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def cluster_binding_modes(footprints: Mapping[str, set[int]], threshold: float = 0.5) -> list[dict]:
    """Greedy footprint clustering. Largest-footprint designs seed modes; each
    subsequent design joins the first mode whose seed it overlaps ≥ ``threshold``
    (Jaccard), else seeds a new mode. Returns modes sorted largest-first.
    """
    items = sorted(footprints.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    modes: list[dict] = []
    for bid, fp in items:
        placed = False
        for mode in modes:
            if _jaccard(fp, mode["seed_fp"]) >= threshold:
                mode["members"].append(bid)
                placed = True
                break
        if not placed:
            modes.append({"seed": bid, "seed_fp": fp, "members": [bid]})
    modes.sort(key=lambda m: (-len(m["members"]), m["seed"]))
    return modes


def mode_consensus(footprints: Mapping[str, set[int]], members: list[str], frac: float = 0.5) -> list[int]:
    """Residues contacted by at least ``frac`` of a mode's members, sorted."""
    counter: collections.Counter[int] = collections.Counter()
    for bid in members:
        counter.update(footprints.get(bid, set()))
    n = len(members)
    cutoff = max(1, frac * n)
    return sorted(r for r, c in counter.items() if c >= cutoff)
