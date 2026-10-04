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
REQUIRED_FIELDS = ("name", "n_designs", "label_column", "labels", "outcome_column")

#: The only outcomes a labelled row may carry. ``excluded:`` takes a free-text reason.
#:
#: There is deliberately NO default and no fallback. On 2026-10-03 a panel's blank Kd cells
#: were read as "tested, did not bind" when they were in fact designs that had never been
#: ordered -- the sheet recorded it with a divider row, and one of the two panels even used an
#: explicit ``N/A`` for tested-and-not-bound, which ``pd.read_csv`` silently turns into NaN.
#: Eleven such rows dragged a 114-design AUC from 0.706 to 0.4835, and they were only caught
#: because a reviewer noticed they outranked 81% of the confirmed binders. A design with no
#: experimental outcome must be structurally incapable of becoming a negative, which means the
#: distinction has to be a required, explicit, non-defaulting column rather than an inference
#: from an empty cell.
OUTCOMES = ("bound", "not_bound", "not_tested")
_EXCLUDED_PREFIX = "excluded:"


def _check_outcomes(name: str, df, column: str) -> None:
    """Refuse the pool unless every row carries an explicit, recognised outcome."""
    if column not in df.columns:
        raise ValueError(
            f"{name!r}: manifest declares outcome_column {column!r}, which is not in the label "
            f"file (columns: {', '.join(map(str, df.columns))}). Every row must state its "
            "experimental outcome explicitly; it is never inferred from a blank cell."
        )
    vals = df[column].astype("string")
    blank = vals.isna() | (vals.str.strip() == "")
    if blank.any():
        raise ValueError(
            f"{name!r}: {int(blank.sum())} row(s) have an empty {column!r}. A row without an "
            f"outcome cannot be scored as a negative -- label it {'/'.join(OUTCOMES)} or "
            f"'{_EXCLUDED_PREFIX}<reason>'. Rows: {list(df.index[blank][:5])}"
        )
    bad = ~(vals.isin(OUTCOMES) | vals.str.startswith(_EXCLUDED_PREFIX))
    if bad.any():
        raise ValueError(
            f"{name!r}: unrecognised {column!r} value(s) {sorted(set(vals[bad]))[:5]}. "
            f"Allowed: {', '.join(OUTCOMES)}, or '{_EXCLUDED_PREFIX}<reason>'."
        )


def list_benchmarks() -> list[str]:
    """Names of every pool with a manifest. Empty when the registry is absent."""
    if not BENCHMARKS_DIR.is_dir():
        return []
    return sorted(p.parent.name for p in BENCHMARKS_DIR.glob("*/MANIFEST.json"))


def _check_id(name: str) -> None:
    """A pool id becomes a directory name, so it must be one path component.

    `load_manifest` and `labels_path` both interpolate the id straight into a path, and
    the label store is private and holds other pools. An id of `..` would read outside
    the pool the caller named. Ids come from our own code, so this is cheap insurance
    rather than a live exploit -- but it is one line, and this repo is public.
    """
    if not name or name in {".", ".."} or "/" in name or "\\" in name or Path(name).name != name:
        raise ValueError(
            f"Invalid benchmark pool id {name!r}. An id is a single directory name — "
            "no separators, no '.' or '..' — because it is used as a path component "
            "under both the public manifest directory and the private label store."
        )


def load_manifest(name: str) -> dict:
    """The public, auditable description of one pool."""
    _check_id(name)
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

    # One pool registered under two ids is two pools as far as every path here is
    # concerned, and nothing else compares checksums ACROSS pools. A cross-pool
    # aggregate would then double-count the same rows, and a citation of one id would
    # silently mean the other. Plan item 9 records the real case: the Overath pool has
    # two ids and two doc filenames. Refused rather than resolved by guessing which id
    # was meant -- the labels decide every number computed from them.
    expected_sha = manifest["labels"]["sha256"]
    aliases = sorted(
        other
        for other in list_benchmarks()
        if other != name and load_manifest(other)["labels"]["sha256"] == expected_sha
    )
    if aliases:
        raise ValueError(
            f"Benchmark pool {name!r} declares the same label checksum as "
            f"{', '.join(repr(a) for a in aliases)} — these ids are aliases for one pool. "
            "Merge or delete the duplicate manifest(s) before computing anything: two ids "
            "for one pool double-count in any cross-pool aggregate, and a result citing "
            "one of them is indistinguishable from a result citing the other."
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
    _check_outcomes(name, df, manifest["outcome_column"])
    return df
