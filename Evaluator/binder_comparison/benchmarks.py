"""Private label registry — name, audit and load a labelled design pool (Part Y).

Three shadow-mode columns ship today (``would_exclude_composition``,
``would_exclude_confidence``, ``would_exclude_self_consistency``) and none can
leave shadow mode without knowing which designs actually expressed and bound.
This is how such a pool is referred to by name without the labels ever entering
a public repository.

**The split.** The repo carries ``Evaluator/benchmarks/<pool>/MANIFEST.json``,
which is everything needed to AUDIT a result: what the pool is, where it came
from, how many rows, what the label means, and the SHA-256 of the file those
numbers were computed from. The label rows live in a private store outside the
tree, located by ``$BINDERSCOUT_BENCHMARK_STORE`` and verified against that
checksum.

**Why the failure behaviour is the interesting part.** Every way this can go
wrong produces a wrong number attached to a right-looking name, so each is an
exception rather than a warning or an empty frame:

* no store configured → ``FileNotFoundError`` naming the env var and the pool;
* checksum mismatch → ``ValueError``; the rows are not the ones the manifest
  describes, so any metric computed from them is mis-attributed;
* row count or label column disagreeing with the manifest → ``ValueError``;
* zero rows → ``ValueError``, because a validation run over an empty pool
  reports cleanly and means nothing.

This module is a library. Nothing in the shipping pipeline imports it, and it
must remain importable — and ``list_benchmarks()`` must work — on a machine
holding no private data at all, which is every CI run and every fresh clone.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "benchmarks"

#: Where the private label rows live. Set per machine; never committed.
STORE_ENV = "BINDERSCOUT_BENCHMARK_STORE"

#: A manifest without these cannot be audited, so it is refused rather than
#: half-trusted. Mirrors ``manifest_required_fields`` in SCHEMA.json.
REQUIRED_FIELDS = ("name", "n_designs", "label_column", "labels")


def list_benchmarks() -> list[str]:
    """Names of every pool with a manifest. Empty when the registry is absent."""
    if not BENCHMARKS_DIR.is_dir():
        return []
    return sorted(p.parent.name for p in BENCHMARKS_DIR.glob("*/MANIFEST.json"))


def load_manifest(name: str) -> dict:
    """The public, auditable description of one pool."""
    path = BENCHMARKS_DIR / name / "MANIFEST.json"
    if not path.is_file():
        available = list_benchmarks()
        raise KeyError(
            f"No benchmark manifest for {name!r} at {path}. "
            f"Available: {', '.join(available) if available else '(none)'}"
        )
    manifest = json.loads(path.read_text())
    missing = [f for f in REQUIRED_FIELDS if f not in manifest]
    if missing:
        raise ValueError(
            f"{path} is missing required field(s): {', '.join(missing)}. "
            "A manifest that cannot be audited is refused rather than half-trusted; "
            "see Evaluator/benchmarks/SCHEMA.json."
        )
    return manifest


def store_root() -> Path | None:
    """The configured private store, or None when unset."""
    raw = os.environ.get(STORE_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def labels_path(name: str) -> Path:
    """Where this pool's label rows should be. Raises if the store is unset."""
    manifest = load_manifest(name)
    root = store_root()
    if root is None:
        raise FileNotFoundError(
            f"Cannot load labels for {name!r}: the private label store is not configured. "
            f"Set {STORE_ENV} to the directory holding <pool>/<labels file>. "
            f"This pool expects {name}/{manifest['labels']['filename']}. "
            "The rows are deliberately outside the repo — it is public."
        )
    return root / name / manifest["labels"]["filename"]


def load_labels(name: str):
    """Load one pool's label rows, verifying them against its manifest.

    Returns a DataFrame. Raises rather than degrading: see the module docstring
    for why each failure mode here is an error.
    """
    import pandas as pd

    manifest = load_manifest(name)
    path = labels_path(name)
    if not path.is_file():
        raise FileNotFoundError(
            f"Labels for {name!r} not found at {path}. "
            f"{STORE_ENV} is set to {store_root()}; the pool directory or file is missing."
        )

    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    expected = manifest["labels"]["sha256"]
    if actual != expected:
        raise ValueError(
            f"Label checksum mismatch for {name!r}.\n"
            f"  expected (MANIFEST.json): {expected}\n"
            f"  actual   ({path}): {actual}\n"
            "These rows are not the ones the manifest describes, so any metric computed "
            "from them would be attributed to the wrong pool."
        )

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(
            f"{path} has no rows. A validation run over an empty pool reports cleanly "
            "and means nothing, so this is an error rather than an empty result."
        )
    if len(df) != int(manifest["n_designs"]):
        raise ValueError(
            f"{name!r}: manifest says n_designs={manifest['n_designs']} but the file has {len(df)} row(s)."
        )
    label_col = manifest["label_column"]
    if label_col not in df.columns:
        raise ValueError(
            f"{name!r}: manifest's label_column {label_col!r} is not in {path} "
            f"(columns: {', '.join(map(str, df.columns))})."
        )
    return df
