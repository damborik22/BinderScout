"""Build a deterministic three-engine refold pool on disk.

The 2.0 plan calls for a *golden pool* — a real archived campaign committed as a
fixture — so that `binder-compare report` can be proved to reproduce `rank`
byte-identically. That pool has to be copied from a machine that can refold,
which this box cannot do, and it is the longest-lead item in the plan.

The guarantee that actually matters does not need real data: it is that `rank`
is a function of the ranking inputs alone, and that it MOVES when the ranking
logic is mutated. A deterministic synthetic pool proves both, commits no
megabytes, and is replaced by the real pool when it arrives without any change
to the tests that consume it.

Deterministic by construction: fixed sequences, fixed metric values, fixed PAE
matrices. No RNG, so no seed to drift.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

TARGET = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"

# (binder_id, source_tool, sequence, boltz_iptm, af3_iptm, esmfold2_iptm)
# Engine values differ per design so the mean is not degenerate, and two designs
# are deliberately missing an engine so the --min-engines gate has something to
# bite on.
DESIGNS: list[tuple[str, str, str, float, float | None, float | None]] = [
    ("d01_mpnn1", "bindcraft", "MKWVTFISLLLLFSSAYSRGV", 0.91, 0.88, 0.86),
    ("d01_mpnn2", "bindcraft", "MKWVTFISLLLLFSSAYSRGW", 0.72, 0.70, 0.69),
    ("d02", "mosaic", "AEQKLISEEDLNSAVDHHHHHH", 0.85, 0.83, 0.80),
    ("d03", "boltzgen", "GSHMSDKIIHLTDDSFDTDVL", 0.64, 0.61, 0.60),
    ("d04_c1", "protein_hunter", "MGSSHHHHHHSSGLVPRGSHM", 0.78, 0.77, 0.75),
    ("d04_c2", "protein_hunter", "MGSSHHHHHHSSGLVPRGSHW", 0.55, 0.54, 0.52),
    ("d05", "rfd3", "MEEPQSDPSVEPPLSQETFSD", 0.88, 0.85, 0.84),
    ("d06", "pxdesign", "MADEEKLPPGWEKRMSRSSGR", 0.49, 0.47, None),  # 2 engines
    ("d07", "mosaic", "MSKGEELFTGVVPILVELDGD", 0.70, None, None),  # 1 engine
    ("d08", "rfd3", "MVSKGEELFTGVVPILVELDG", 0.81, 0.80, 0.79),
]

_ENGINES = {"boltz2": 3, "af3": 4, "esmfold2": 5}


def _pae(n_target: int, n_binder: int, level: float) -> np.ndarray:
    """A plausible PAE block matrix: low within chains, higher across."""
    n = n_target + n_binder
    m = np.full((n, n), level * 12.0, dtype=np.float32)
    m[:n_target, :n_target] = 2.0
    m[n_target:, n_target:] = 3.0
    np.fill_diagonal(m, 0.0)
    return m


def build(root: Path) -> dict[str, Path]:
    """Write the pool under *root*; return the paths report needs."""
    root.mkdir(parents=True, exist_ok=True)

    fasta = root / "sequences.fasta"
    fasta.write_text("".join(f">{bid}|{tool}\n{seq}\n" for bid, tool, seq, *_ in DESIGNS))

    out: dict[str, Path] = {"sequences": fasta}
    for engine, col in _ENGINES.items():
        pae_dir = root / engine / "pae"
        pae_dir.mkdir(parents=True, exist_ok=True)
        csv_path = root / engine / f"{engine}_results.csv"

        rows = []
        for bid, _tool, seq, *vals in DESIGNS:
            iptm = vals[col - 3]
            if iptm is None:
                continue  # this engine did not refold this design
            pae_path = pae_dir / f"{bid}.npy"
            np.save(pae_path, _pae(len(TARGET), len(seq), 1.0 - iptm))
            rows.append(
                {
                    "run_id": bid,
                    "sequence": seq,
                    "target_sequence": TARGET,
                    "binder_length": len(seq),
                    "iptm": iptm,
                    "ipsae_min": round(iptm * 0.95, 4),
                    "plddt_binder_mean": round(iptm * 0.98, 4),
                    "pae_max": round(20.0 * (1.0 - iptm), 4),
                    "pae_file": str(pae_path),
                }
            )

        with csv_path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        out[engine] = csv_path

    return out
