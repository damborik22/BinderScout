"""CLI subcommand: binder-compare refold-protenix

Refold sequences from a FASTA file with Protenix v1.x (bytedance/Protenix), a candidate
second engine in place of AlphaFold 3. Run this INSIDE the Protenix environment, where
the ``protenix`` console script and ``binder_comparison`` are both importable. Only the
v1.x checkpoints (Apache-2.0 code and parameters) are accepted; Protenix-v2 and any other
name are refused by the adapter. Always runs with the torch kernels and torch layernorm:
no proprietary NVIDIA ops at runtime.

Usage:
    binder-compare refold-protenix \\
        --sequences sequences.fasta \\
        --target-seq "MKTAYIAKQRQ..." \\
        --output protenix_results.csv \\
        --output-dir ./refold_protenix/

Exit codes: 0 success; 1 error (including an unlicensed model); 2 no target MSA or an
invalid sequence; 3 partial failure (rows for the designs that did fold are on disk).
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Callable
from pathlib import Path

# The adapter takes these three from us and nothing else: the CLI never lets a caller
# change them (R5), so the options exist below only to be refused with a clear message.
_FIXED_KERNEL_ARGS = ["--trimul-kernel", "torch", "--triatt-kernel", "torch", "--layernorm-type", "torch"]
_REFUSED_FLAGS = {
    "trimul_kernel": "--trimul-kernel",
    "triatt_kernel": "--triatt-kernel",
    "layernorm_type": "--layernorm-type",
}


def _resolve_scripts_path(override: str | Path | None) -> Path:
    if override is not None:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"scripts path not found: {p}")
        return p
    candidate = Path(__file__).parent.parent.parent / "scripts"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Could not locate scripts directory at {candidate}. Pass --scripts-path explicitly.")


def _load_adapter_main(scripts_path: str | Path | None) -> Callable[[list[str]], int]:
    """Import scripts/refold_protenix_v1.py (as refold-af3 does refold_af3.py) and return its ``main``."""
    scripts_dir = str(_resolve_scripts_path(scripts_path))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return importlib.import_module("refold_protenix_v1").main


def _adapter_argv(args: argparse.Namespace) -> list[str]:
    argv = [
        "--sequences",
        args.sequences,
        "--target-seq",
        args.target_seq,
        "--output",
        args.output,
        "--output-dir",
        args.output_dir,
        "--num-seeds",
        str(args.num_seeds),
        "--num-samples",
        str(args.num_samples),
        *_FIXED_KERNEL_ARGS,
    ]
    model_dir = args.model_dir or os.environ.get("PROTENIX_MODEL_DIR")
    if model_dir:
        argv += ["--model-dir", model_dir]
    if args.resume:
        argv.append("--resume")
    if args.no_msa:
        argv.append("--no-msa")
    if args.allow_no_msa:
        argv.append("--allow-no-msa")
    if args.msa_cache_dir:
        argv += ["--msa-cache-dir", args.msa_cache_dir]
    return argv


def run(args: argparse.Namespace) -> None:
    for dest, flag in _REFUSED_FLAGS.items():
        if getattr(args, dest) is not None:
            print(
                f"[refold-protenix] ERROR: {flag} cannot be set: Protenix always runs with "
                "--trimul-kernel torch --triatt-kernel torch --layernorm-type torch "
                "(no proprietary NVIDIA ops at runtime).",
                file=sys.stderr,
            )
            sys.exit(2)

    rc = _load_adapter_main(args.scripts_path)(_adapter_argv(args))
    if rc:
        # Passed through unchanged: 3 means rows for the designs that DID fold are on disk,
        # so a wrapper re-runs the named indices instead of treating the env as broken.
        sys.exit(rc)


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "refold-protenix",
        help="Refold sequences with Protenix v1.x (run in the Protenix environment; only the Apache-2.0 v1.x "
        "checkpoints are accepted).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--sequences", "-s", required=True, metavar="FASTA", help="Input FASTA (e.g. from 'binder-compare extract')"
    )
    p.add_argument("--target-seq", required=True, metavar="SEQ", help="Target protein amino acid sequence")
    p.add_argument(
        "--output", "-o", required=True, metavar="CSV", help="Output CSV path for metrics (e.g. protenix_results.csv)"
    )
    p.add_argument(
        "--output-dir",
        default="./refold_protenix",
        metavar="DIR",
        help="Directory for Protenix predictions and structure files (default: ./refold_protenix)",
    )
    p.add_argument("--num-seeds", type=int, default=1, metavar="N", help="Number of random seeds (default: 1)")
    p.add_argument("--num-samples", type=int, default=5, metavar="N", help="Diffusion samples per seed (default: 5)")
    p.add_argument(
        "--model-dir",
        default=None,
        metavar="DIR",
        help="Protenix data root, holds checkpoint/<model>.pt and common/ "
        "(default: $PROTENIX_MODEL_DIR; else Protenix's own default)",
    )
    p.add_argument(
        "--scripts-path", default=None, metavar="DIR", help="Path to scripts/ directory (auto-detected if not set)"
    )
    p.add_argument(
        "--allow-no-msa",
        action="store_true",
        help="Proceed with a single-sequence target when the MSA cannot be obtained "
        "(default: abort). Scores from an MSA-less engine are NOT comparable to engines "
        "that used one, so this is opt-in and is recorded in target_msa_mode.json.",
    )
    p.add_argument("--resume", action="store_true", help="Skip binders already present in existing output CSV")
    p.add_argument(
        "--no-msa",
        action="store_true",
        help="Disable target MSA (single-sequence mode)",
    )
    p.add_argument(
        "--msa-cache-dir",
        default=None,
        metavar="DIR",
        help="MSA cache directory (default: $BINDERSCOUT_MSA_CACHE or ~/.cache/binderscout/target_msa)",
    )
    # Declared only so that passing one is refused with a message rather than silently overridden
    # (or reported as an unknown option); hidden because there is nothing to choose.
    for dest, flag in _REFUSED_FLAGS.items():
        p.add_argument(flag, dest=dest, default=None, help=argparse.SUPPRESS)
    p.set_defaults(func=run)
