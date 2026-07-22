"""Detect binder-into-target β-sheet intercalation (β-augmentation) via DSSP.

A binder that threads a β-strand into the target's β-sheet has binder-chain
residues in β-conformation whose DSSP bridge partners are TARGET residues. A
genuine surface binder has ~0. This is a common gaming mode for β-sheet-rich
targets (serpins, Ig folds): it inflates iPTM/interface metrics but is
non-physical — the target is already folded, so a strand cannot insert into its
sheet. Especially non-physical when the binder strand is bridged on BOTH sides
(sandwiched between two target strands = interior intercalation).

Requires ``mkdssp`` on PATH (DSSP 4.x). Returns (n_xbridge, n_xbridge2,
n_binder_res): binder residues β-bridged to the target (any side / both sides)
and the binder residue count.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def count_cross_chain_bridges(
    pdb: str | Path, target_chain: str = "A", binder_chain: str = "B"
) -> tuple[int, int, int]:
    """Count binder residues β-bridged to the target chain in *pdb*.

    Returns ``(n_xbridge, n_xbridge2, n_binder_res)``; ``(-1, -1, 0)`` if DSSP
    fails or the file is unreadable.
    """
    out = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".dssp", delete=False) as tf:
            out = tf.name
        subprocess.run(
            ["mkdssp", "--output-format", "dssp", str(pdb), out],
            capture_output=True,
            timeout=180,
            check=False,
        )
        lines = Path(out).read_text().splitlines()
    except Exception:
        return (-1, -1, 0)
    finally:
        if out:
            Path(out).unlink(missing_ok=True)

    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("  #  RESIDUE")) + 1
    except StopIteration:
        return (-1, -1, 0)

    chain_of: dict[int, str] = {}
    rows: list[tuple[int, str, str, int, int]] = []
    for ln in lines[start:]:
        if len(ln) < 34 or ln[13] == "!":
            continue
        try:
            didx = int(ln[0:5])
        except ValueError:
            continue

        def _bp(a: int, b: int) -> int:
            s = ln[a:b].strip()  # noqa: B023
            return int(s) if s and s != "0" else 0

        rows.append((didx, ln[11], ln[16], _bp(25, 29), _bp(29, 33)))
        chain_of[didx] = ln[11]

    n1 = n2 = binder_res = 0
    for _didx, chain, ss, bp1, bp2 in rows:
        if chain != binder_chain:
            continue
        binder_res += 1
        if ss not in ("E", "B"):
            continue
        t1 = bp1 > 0 and chain_of.get(bp1) == target_chain
        t2 = bp2 > 0 and chain_of.get(bp2) == target_chain
        if t1 or t2:
            n1 += 1
        if t1 and t2:
            n2 += 1
    return (n1, n2, binder_res)


def is_intercalating(n_xbridge: int, n_xbridge2: int, *, min_both_side: int = 2, min_xbridge: int | None = None) -> bool:
    """True when the binder threads a strand INTO the target sheet (interior intercalation).

    A residue counted in ``n_xbridge2`` is β-bridged to the target on *both* sides — i.e.
    inserted between two target strands. That two-sided ladder is the mechanistic signature
    of β-augmentation. One-sided (edge) β-contacts counted in ``n_xbridge`` are a normal
    binding mode, NOT augmentation (a handful of scattered edge bridges on a long binder, or
    even a short edge-paired strand, does not thread the sheet), so the legacy single-sided
    trigger is opt-in only: pass ``min_xbridge`` to re-enable it; by default it is off.
    """
    if n_xbridge < 0:
        return False  # unknown (DSSP failed) — don't drop on missing data
    if n_xbridge2 >= min_both_side:
        return True
    return min_xbridge is not None and n_xbridge >= min_xbridge
