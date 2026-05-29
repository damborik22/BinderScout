"""Standalone SoluProt batch scorer.

Run inside the ``binder-eval-soluprot`` conda env. Functionally equivalent to
``binder-compare filter-soluprot`` — kept in scripts/ to match the existing
pattern (refold_boltz2.py, refold_protenix.py, refold_af3.py, refold_esmfold2.py
all have a script form alongside the CLI form).

Usage:
    conda run -n binder-eval-soluprot python Evaluator/scripts/filter_soluprot.py \\
        --sequences sequences.fasta \\
        --output    soluprot_results.csv \\
        [--threshold 0.5] \\
        [--scripts-path /path/to/soluprot]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add the package to sys.path so this script can be run standalone (no
# `pip install -e Evaluator/` required at smoke-test time).
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "Evaluator"))

from binder_comparison.refolding.soluprot_runner import (  # noqa: E402
    DEFAULT_THRESHOLD,
    run_soluprot_filter,
)


def _read_fasta(path: Path) -> tuple[list[str], list[str]]:
    """Minimal FASTA reader (no biopython dep at script invocation time)."""
    headers: list[str] = []
    sequences: list[str] = []
    cur_h: str | None = None
    cur_s: list[str] = []
    with path.open() as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if cur_h is not None:
                    headers.append(cur_h)
                    sequences.append("".join(cur_s))
                cur_h = line[1:].split()[0] or f"seq{len(headers):06d}"
                cur_s = []
            elif line:
                cur_s.append(line.strip())
        if cur_h is not None:
            headers.append(cur_h)
            sequences.append("".join(cur_s))
    return headers, sequences


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score binders with SoluProt 1.0 and write a per-sequence CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--sequences", required=True, help="Input FASTA")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Pass threshold (default {DEFAULT_THRESHOLD}, paper value).",
    )
    parser.add_argument(
        "--scripts-path",
        default=None,
        help="Override path to the SoluProt distribution (containing soluprot.py).",
    )
    args = parser.parse_args()

    fasta_path = Path(args.sequences)
    if not fasta_path.exists():
        print(f"[filter-soluprot] ERROR: input not found: {fasta_path}", file=sys.stderr)
        sys.exit(1)

    headers, sequences = _read_fasta(fasta_path)
    if not sequences:
        print(f"[filter-soluprot] ERROR: no sequences in {fasta_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[filter-soluprot] {len(sequences)} sequence(s) from {fasta_path}")
    run_soluprot_filter(
        sequences=sequences,
        output_csv=args.output,
        threshold=args.threshold,
        scripts_path=args.scripts_path,
        binder_ids=headers,
    )


if __name__ == "__main__":
    main()
