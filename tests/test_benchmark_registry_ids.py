"""A pool id is a path component, so the registry must police it.

`load_manifest` resolves `BENCHMARKS_DIR / name / "MANIFEST.json"` and `labels_path`
resolves `store_root() / name / <filename>`. The id is interpolated straight into both,
which the 2.0 plan flagged as item 9: *"The Overath pool has two ids and two doc
filenames, and `pool_id` is a path component in Y's design — so `load_pool('overath')`
and `load_pool('overath2025')` are different pools."*

Two consequences, both guarded here.

**Aliasing.** The same rows registered under two ids are two independent pools as far
as the registry is concerned. Nothing compares checksums *across* pools, so a
cross-pool aggregate would double-count them and a citation of one would silently mean
the other. The labels decide every number computed from them, so an ambiguous registry
is refused rather than resolved by guessing which id was meant.

**Traversal.** An id is not validated as a single path component, so `..` escapes into
the rest of the private store — which holds pools this caller may not have meant to
read. Low severity (ids come from our own code) and one line to prevent, and this repo
is public.
"""

from __future__ import annotations

import hashlib
import json

import pytest

pytest.importorskip("pandas")

from binder_comparison import benchmarks  # noqa: E402

_ROWS_A = "design_id,is_binder\nd1,1\nd2,0\n"
_ROWS_B = "design_id,is_binder\nd9,1\nd8,0\n"


def _register(tmp_path, monkeypatch, pools: dict[str, str]) -> None:
    """Write a manifest + label file per pool, and point the registry at them."""
    bench = tmp_path / "benchmarks"
    store = tmp_path / "store"
    for name, rows in pools.items():
        (bench / name).mkdir(parents=True)
        (store / name).mkdir(parents=True)
        (store / name / "labels.csv").write_text(rows)
        (bench / name / "MANIFEST.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "n_designs": rows.count("\n") - 1,
                    "label_column": "is_binder",
                    "labels": {
                        "filename": "labels.csv",
                        "sha256": hashlib.sha256(rows.encode()).hexdigest(),
                    },
                }
            )
        )
    monkeypatch.setattr(benchmarks, "BENCHMARKS_DIR", bench)
    monkeypatch.setenv(benchmarks.STORE_ENV, str(store))


def test_distinct_pools_load_normally(tmp_path, monkeypatch):
    """Control: two genuinely different pools are fine."""
    _register(tmp_path, monkeypatch, {"cao2022": _ROWS_A, "adaptyv": _ROWS_B})
    assert len(benchmarks.load_labels("cao2022")) == 2
    assert len(benchmarks.load_labels("adaptyv")) == 2


def test_the_same_rows_under_two_ids_is_refused(tmp_path, monkeypatch):
    """The Overath hazard: one pool, two ids, identical checksums."""
    _register(tmp_path, monkeypatch, {"overath": _ROWS_A, "overath2025": _ROWS_A})
    with pytest.raises(ValueError, match="(?i)same|alias|duplicate"):
        benchmarks.load_labels("overath")


def test_the_refusal_names_both_ids(tmp_path, monkeypatch):
    """Naming only one id would leave the reader to find the other by hand, and the
    fix is to delete or merge a specific manifest."""
    _register(tmp_path, monkeypatch, {"overath": _ROWS_A, "overath2025": _ROWS_A})
    with pytest.raises(ValueError) as err:
        benchmarks.load_labels("overath2025")
    msg = str(err.value)
    assert "overath" in msg and "overath2025" in msg, f"both ids must be named: {msg}"


@pytest.mark.parametrize(
    "bad",
    ["../secret", "a/b", "..", ".", "", "/abs", "x/../y"],
    ids=["parent", "nested", "dotdot", "dot", "empty", "absolute", "embedded"],
)
def test_an_id_must_be_a_single_path_component(tmp_path, monkeypatch, bad):
    _register(tmp_path, monkeypatch, {"cao2022": _ROWS_A})
    with pytest.raises((ValueError, KeyError)) as err:
        benchmarks.load_manifest(bad)
    assert "KeyError" not in type(err.value).__name__ or bad not in ("../secret", "a/b", ".."), (
        f"{bad!r} must be rejected as a malformed id, not merely missed as a lookup"
    )
