"""AggreProt — aggregation-prone-region (APR) screen, reduced to comparable columns.

AggreProt (Loschmidt Lab, NAR 2024 52(W1):W159,
https://loschmidt.chemi.muni.cz/aggreprot/) predicts aggregation-prone regions
with an ensemble of five deep networks. Item D3 of the 2.0 assessment routes it
to Part AA with the verdict *test before building*, on the concern that it
restates SoluProt's hydrophobicity/charge signal.

**Two things about D3's test are not as the assessment assumed.**

First, its test — "rank correlation vs ``soluprot_score``" — is not executable
as written. AggreProt emits a **per-residue profile**, not a score, and a
profile cannot be rank-correlated against a scalar until it is reduced. *Which*
reduction is an open design decision that the assessment never names, and
different reductions are different signals: a protein with one long sticky patch
and one with five scattered hot spots can share an APR fraction while meaning
very different things for engineering.

This module therefore computes **every defensible reduction** and leaves the
choice downstream. The decorrelation test should be run against all of them at
once — that answers D3 and picks the reduction from the same run.

Second, the premise behind D3 should be measured rather than assumed. The same
concern was raised for TmProt (D1), and on a real 2VDY pool of 436 designs
TmProt vs SoluProt came out at Spearman -0.090 — essentially uncorrelated. See
docs/PLAN_binderscout_v2_corrections.md.

**Status of the tool side.** AggreProt has no public code repository (both
likely GitHub paths 404) and the web server accepts at most three sequences per
submission, so it cannot score a campaign pool. The model is the group's own, so
obtaining it is an internal matter rather than a licensing one. Until it is in
hand:

* :func:`reduce_profile` is complete, exact and tested — it is pure arithmetic.
* :func:`parse_profile_csv` is a tolerant parser written against the *described*
  output (per-residue rows). **It has not been validated against real AggreProt
  output** and must be checked when the model arrives.
* :func:`run_aggreprot` shells out to ``$AGGREPROT_BIN``; its argument list is a
  placeholder for the same reason.

Nothing here ranks or drops a design: every column is advisory, like the rest of
the pre-GPU screen bank.
"""

from __future__ import annotations

import csv
from pathlib import Path

# Per-residue score at or above which a residue counts as aggregation-prone.
# Decides three of the five reductions, so it is a named constant rather than a
# literal buried in a comprehension. Confirm against the paper's own cutoff when
# the model is in hand.
APR_THRESHOLD = 0.5

_REDUCTION_KEYS = (
    "aggreprot_max",
    "aggreprot_mean",
    "aggreprot_apr_fraction",
    "aggreprot_apr_count",
    "aggreprot_apr_longest",
)


def _runs_above(profile: list[float], threshold: float) -> list[int]:
    """Lengths of each maximal run of residues at or above *threshold*."""
    runs: list[int] = []
    current = 0
    for v in profile:
        if v >= threshold:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def reduce_profile(profile: list[float], threshold: float = APR_THRESHOLD) -> dict:
    """Reduce a per-residue aggregation profile to five comparable scalars.

    All five are returned deliberately: which one to present is an open decision
    (D3), and running the decorrelation test against all of them answers the
    redundancy question and picks the reduction in one pass.

    * ``aggreprot_max`` / ``aggreprot_mean`` — profile summary statistics.
    * ``aggreprot_apr_fraction`` — share of residues inside an APR.
    * ``aggreprot_apr_count`` — number of distinct APRs (regions, not residues).
    * ``aggreprot_apr_longest`` — length of the longest contiguous APR.

    An empty profile returns all ``None`` rather than zeros: a sequence
    AggreProt did not score must stay distinguishable from one it scored as
    perfectly soluble.
    """
    if not profile:
        return dict.fromkeys(_REDUCTION_KEYS)
    runs = _runs_above(profile, threshold)
    n_apr_residues = sum(runs)
    return {
        "aggreprot_max": max(profile),
        "aggreprot_mean": sum(profile) / len(profile),
        "aggreprot_apr_fraction": n_apr_residues / len(profile),
        "aggreprot_apr_count": len(runs),
        "aggreprot_apr_longest": max(runs) if runs else 0,
    }


# Column spellings a per-residue AggreProt export might plausibly use. Written
# against the published DESCRIPTION of the output, not against a real file --
# see the module docstring.
_SCORE_CANDIDATES = ("aggregation", "aggregation_score", "agg_score", "score", "apr_score", "value")
_ID_CANDIDATES = ("id", "sequence_id", "protein", "name")
_POS_CANDIDATES = ("position", "pos", "residue_index", "index", "resi")


def parse_profile_csv(path: str | Path) -> dict[str, list[float]]:
    """Read per-residue rows into ``{sequence_id: [score, ...]}`` in position order.

    UNVALIDATED against real AggreProt output. Column names are matched
    case-insensitively against the candidate lists above; if the real export
    differs, extend those lists rather than rewriting callers.
    """
    path = Path(path)
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
        score_key = next((cols[c] for c in _SCORE_CANDIDATES if c in cols), None)
        id_key = next((cols[c] for c in _ID_CANDIDATES if c in cols), None)
        pos_key = next((cols[c] for c in _POS_CANDIDATES if c in cols), None)
        if score_key is None or id_key is None:
            raise ValueError(
                f"{path} does not look like a per-residue AggreProt export: need an id column "
                f"({_ID_CANDIDATES}) and a score column ({_SCORE_CANDIDATES}); got {reader.fieldnames}"
            )
        rows: dict[str, list[tuple[int, float]]] = {}
        for i, row in enumerate(reader):
            sid = (row.get(id_key) or "").strip()
            try:
                score = float((row.get(score_key) or "").strip())
            except ValueError:
                continue
            try:
                pos = int(float((row.get(pos_key) or "").strip())) if pos_key else i
            except ValueError:
                pos = i
            rows.setdefault(sid, []).append((pos, score))
    return {sid: [s for _, s in sorted(vals)] for sid, vals in rows.items()}
