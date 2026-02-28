"""CLI subcommand: binder-compare validate

Sanity-check input sequences before running the full refolding pipeline.

Usage:
    binder-compare validate --sequences sequences.fasta
    binder-compare validate --sequences seqs.csv --target-pdb target.pdb
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_STANDARD_AAS = set("ACDEFGHIKLMNPQRSTVWY")


def run(args: argparse.Namespace) -> None:
    sequences = _load_sequences(args.sequences)
    target_seq = _load_target(args) if (args.target_seq or args.target_pdb) else None

    checks = _run_checks(sequences, target_seq)

    if args.json:
        print(json.dumps(checks, indent=2))
    else:
        _print_summary(checks)

    all_pass = all(c["pass"] for c in checks["checks"])
    sys.exit(0 if all_pass else 1)


def _load_sequences(path: str) -> list[str]:
    """Load sequences from FASTA, CSV, or plain text file."""
    p = Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    text = p.read_text()
    lines = text.strip().splitlines()

    # FASTA format
    if any(line.startswith(">") for line in lines):
        seqs = []
        current: list[str] = []
        for line in lines:
            if line.startswith(">"):
                if current:
                    seqs.append("".join(current).strip().upper())
                    current = []
            else:
                current.append(line.strip())
        if current:
            seqs.append("".join(current).strip().upper())
        return seqs

    # CSV format — look for a 'sequence' column
    if "," in lines[0] and "sequence" in lines[0].lower():
        import csv
        import io
        reader = csv.DictReader(io.StringIO(text))
        seq_col = None
        for col in reader.fieldnames or []:
            if col.lower() == "sequence":
                seq_col = col
                break
        if seq_col:
            return [row[seq_col].strip().upper() for row in reader if row[seq_col].strip()]

    # Plain text — one sequence per line
    return [line.strip().upper() for line in lines if line.strip() and not line.startswith("#")]


def _load_target(args: argparse.Namespace) -> str | None:
    """Load target sequence from --target-seq or --target-pdb."""
    if args.target_seq:
        return args.target_seq.strip().upper()
    if args.target_pdb:
        try:
            from ..io.read import extract_sequence_from_pdb
            return extract_sequence_from_pdb(args.target_pdb)
        except Exception as e:
            return f"ERROR: {e}"
    return None


def _run_checks(sequences: list[str], target_seq: str | None) -> dict:
    """Run all validation checks and return a structured report."""
    checks = []

    # Check 1: no empty sequences
    empty = [i for i, s in enumerate(sequences) if not s]
    checks.append({
        "name": "no_empty_sequences",
        "pass": len(empty) == 0,
        "detail": f"{len(empty)} empty sequence(s)" if empty else "all sequences non-empty",
        "indices": empty,
    })

    # Check 2: standard amino acids only
    non_standard = []
    for i, seq in enumerate(sequences):
        invalid = set(seq) - _STANDARD_AAS
        if invalid:
            non_standard.append({"index": i, "invalid_chars": sorted(invalid)})
    checks.append({
        "name": "standard_amino_acids",
        "pass": len(non_standard) == 0,
        "detail": (f"{len(non_standard)} sequence(s) with non-standard characters"
                   if non_standard else "all sequences use standard amino acids"),
        "violations": non_standard[:10],
    })

    # Check 3: reasonable length range (10-2000 aa)
    out_of_range = []
    for i, seq in enumerate(sequences):
        if len(seq) < 10 or len(seq) > 2000:
            out_of_range.append({"index": i, "length": len(seq)})
    checks.append({
        "name": "length_range",
        "pass": len(out_of_range) == 0,
        "detail": (f"{len(out_of_range)} sequence(s) outside 10-2000 aa range"
                   if out_of_range else "all sequences within 10-2000 aa"),
        "violations": out_of_range[:10],
    })

    # Check 4: no duplicates
    seen: dict[str, int] = {}
    duplicates = []
    for i, seq in enumerate(sequences):
        if seq in seen:
            duplicates.append({"index": i, "duplicate_of": seen[seq]})
        else:
            seen[seq] = i
    checks.append({
        "name": "no_duplicates",
        "pass": len(duplicates) == 0,
        "detail": (f"{len(duplicates)} duplicate sequence(s)"
                   if duplicates else "no duplicate sequences"),
        "violations": duplicates[:10],
    })

    # Check 5: target sequence/PDB parseable (if provided)
    if target_seq is not None:
        if target_seq.startswith("ERROR:"):
            checks.append({
                "name": "target_parseable",
                "pass": False,
                "detail": target_seq,
            })
        else:
            target_invalid = set(target_seq) - _STANDARD_AAS
            checks.append({
                "name": "target_parseable",
                "pass": len(target_invalid) == 0 and len(target_seq) > 0,
                "detail": (f"target sequence OK ({len(target_seq)} aa)"
                           if not target_invalid else
                           f"target has non-standard chars: {sorted(target_invalid)}"),
            })

    # Check 6: warn if binder > target length (unusual)
    warnings = []
    if target_seq and not target_seq.startswith("ERROR:"):
        for i, seq in enumerate(sequences):
            if len(seq) > len(target_seq):
                warnings.append({"index": i, "binder_len": len(seq), "target_len": len(target_seq)})
        if warnings:
            checks.append({
                "name": "binder_shorter_than_target",
                "pass": True,
                "detail": f"{len(warnings)} binder(s) longer than target ({len(target_seq)} aa) — unusual for binder design",
                "warnings": warnings[:10],
            })

    return {
        "total_sequences": len(sequences),
        "checks": checks,
    }


def _print_summary(report: dict) -> None:
    """Print a human-readable validation summary."""
    print(f"Validated {report['total_sequences']} sequence(s):\n")
    all_pass = True
    for check in report["checks"]:
        status = "PASS" if check["pass"] else "FAIL"
        marker = "  " if check["pass"] else "  "
        if not check["pass"]:
            all_pass = False
        print(f"  [{status}] {check['name']}: {check['detail']}")

        # Show first few violations
        for key in ("violations", "warnings", "indices"):
            items = check.get(key, [])
            if items and isinstance(items, list):
                for item in items[:3]:
                    print(f"         {item}")
                if len(items) > 3:
                    print(f"         ... and {len(items) - 3} more")

    print()
    if all_pass:
        print("All checks passed.")
    else:
        print("Some checks failed. Review the issues above before proceeding.")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "validate",
        help="Sanity-check input sequences before refolding.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--sequences", "-s", required=True, metavar="FILE",
                   help="Input file (FASTA, CSV with 'sequence' column, or plain text)")
    p.add_argument("--target-seq", metavar="SEQ",
                   help="Target protein sequence (amino acid string)")
    p.add_argument("--target-pdb", metavar="PDB",
                   help="Target PDB file (to extract sequence for length comparison)")
    p.add_argument("--json", action="store_true",
                   help="Output results as JSON instead of text summary")
    p.set_defaults(func=run)
