"""The private label registry (Part Y).

Three shadow-mode columns now ship — ``would_exclude_composition``,
``would_exclude_confidence``, ``would_exclude_self_consistency`` — and not one
can be promoted out of shadow mode without knowing which designs actually
expressed and bound. This registry is how a labelled pool is named, audited and
loaded without ever putting the labels in a public repo.

The split: the repo carries ``MANIFEST.json`` per pool, which is enough to AUDIT
a result (what the pool is, where it came from, how many rows, what the label
means, and the checksum of the file those numbers were computed from). The label
rows themselves live in a private store outside the tree, resolved by that
checksum.

What these tests pin is failure behaviour, because every failure mode here
produces a *wrong number attributed to the right name*:

* a missing store must raise something actionable, never an empty frame that
  silently scores 0 designs;
* a checksum mismatch must be an ERROR, not a warning — it means the numbers
  would be attributed to a pool that is not the one the manifest describes;
* the module must import and list pools on a machine with no private data at
  all, because that is every CI run and every fresh clone.
"""

from __future__ import annotations

import hashlib
import json

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison import benchmarks as bm  # noqa: E402

# Every row carries an explicit `outcome`; the loader refuses a pool without it, because an
# inference from a blank cell is what produced the 2026-10-03 label error.
_LABELS = "sequence,target,binds,outcome\nMKTAYIAK,CALCA,1,bound\nGGSGGSWE,CALCA,0,not_bound\n"


def _make_store(tmp_path, name="cao2022", body=_LABELS, filename="labels.csv"):
    """A private store holding one pool's labels, plus its true checksum."""
    pool = tmp_path / "store" / name
    pool.mkdir(parents=True)
    (pool / filename).write_text(body)
    return tmp_path / "store", hashlib.sha256(body.encode()).hexdigest()


def _make_registry(tmp_path, name="cao2022", checksum="x" * 64, filename="labels.csv", **extra):
    """A public registry entry: SCHEMA.json + one pool MANIFEST.json."""
    root = tmp_path / "benchmarks"
    (root / name).mkdir(parents=True)
    (root / "SCHEMA.json").write_text(json.dumps({"version": 1}))
    manifest = {
        "name": name,
        "description": "Cao 2022 minibinders, binary binding labels",
        "source": "Cao et al. 2022, Nature",
        "n_designs": 2,
        "label_column": "binds",
        "label_meaning": "1 = measured binder, 0 = measured non-binder",
        "outcome_column": "outcome",
        "labels": {"filename": filename, "sha256": checksum},
    }
    manifest.update(extra)
    (root / name / "MANIFEST.json").write_text(json.dumps(manifest))
    return root


def test_lists_pools_on_a_machine_with_no_private_data(tmp_path, monkeypatch):
    """Every CI run and every fresh clone is this case."""
    root = _make_registry(tmp_path)
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", root)
    monkeypatch.delenv(bm.STORE_ENV, raising=False)
    assert bm.list_benchmarks() == ["cao2022"]


def test_listing_an_empty_registry_is_empty_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", tmp_path / "nothing")
    assert bm.list_benchmarks() == []


def test_manifest_loads_and_carries_the_audit_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", _make_registry(tmp_path))
    m = bm.load_manifest("cao2022")
    assert m["label_column"] == "binds"
    assert m["labels"]["sha256"]


def test_an_unknown_pool_names_what_is_available(tmp_path, monkeypatch):
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", _make_registry(tmp_path))
    with pytest.raises(KeyError, match="cao2022"):
        bm.load_manifest("does_not_exist")


def test_a_manifest_missing_a_required_field_is_refused(tmp_path, monkeypatch):
    root = _make_registry(tmp_path)
    (root / "cao2022" / "MANIFEST.json").write_text(json.dumps({"name": "cao2022"}))
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", root)
    with pytest.raises(ValueError, match=r"label_column|labels|n_designs|outcome_column"):
        bm.load_manifest("cao2022")


def test_the_required_field_set_is_pinned_literally():
    """The required fields, written out — not read from the code under test.

    Mutation testing on 2026-10-04 found two layers of hollowness here. First, the only
    coverage of ``outcome_column`` asserted that the *registered* manifests carry it, so
    deleting it from ``REQUIRED_FIELDS`` broke nothing. Then the parametrised test below was
    added — and it *also* missed, because it iterates ``bm.REQUIRED_FIELDS`` itself, so removing
    an entry silently generates one fewer case instead of failing.

    A test whose expectation comes from the thing it is testing cannot detect a deletion. Hence
    this literal set. Adding a field is a deliberate act and should fail here too, so the
    assertion is equality.
    """
    assert set(bm.REQUIRED_FIELDS) == {
        "name",
        "n_designs",
        "label_column",
        "labels",
        "outcome_column",
    }


@pytest.mark.parametrize("field", bm.REQUIRED_FIELDS)
def test_each_required_field_is_individually_enforced(tmp_path, monkeypatch, field):
    """Drop exactly one field and the manifest must still be refused.

    The blanket test above passes a manifest missing almost everything, so it stays green even
    if a field is quietly dropped from REQUIRED_FIELDS -- which mutation testing caught on
    2026-10-04: removing ``outcome_column`` from the tuple broke nothing, because the only
    coverage was an assertion that the *registered* manifests happen to carry it. A pool could
    then be registered with no outcome column at all, which is the failure this field exists to
    prevent.
    """
    root = _make_registry(tmp_path)
    man = json.loads((root / "cao2022" / "MANIFEST.json").read_text())
    del man[field]
    (root / "cao2022" / "MANIFEST.json").write_text(json.dumps(man))
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", root)
    with pytest.raises(ValueError, match=field):
        bm.load_manifest("cao2022")


def test_loading_labels_without_a_store_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", _make_registry(tmp_path))
    monkeypatch.delenv(bm.STORE_ENV, raising=False)
    with pytest.raises(FileNotFoundError) as exc:
        bm.load_labels("cao2022")
    msg = str(exc.value)
    assert bm.STORE_ENV in msg, "the error must name the env var that fixes it"
    assert "cao2022" in msg


def test_loading_labels_verifies_the_checksum(tmp_path, monkeypatch):
    store, true_sum = _make_store(tmp_path)
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", _make_registry(tmp_path, checksum=true_sum))
    monkeypatch.setenv(bm.STORE_ENV, str(store))

    df = bm.load_labels("cao2022")
    assert list(df.columns) == ["sequence", "target", "binds", "outcome"]
    assert len(df) == 2


def test_a_checksum_mismatch_is_an_error_not_a_warning(tmp_path, monkeypatch):
    """The numbers would be attributed to a pool that is not this one."""
    store, _true = _make_store(tmp_path)
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", _make_registry(tmp_path, checksum="d" * 64))
    monkeypatch.setenv(bm.STORE_ENV, str(store))

    with pytest.raises(ValueError, match="checksum"):
        bm.load_labels("cao2022")


def test_row_count_disagreeing_with_the_manifest_is_an_error(tmp_path, monkeypatch):
    body = "sequence,target,binds\nMKTAYIAK,CALCA,1\n"  # 1 row, manifest says 2
    store, true_sum = _make_store(tmp_path, body=body)
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", _make_registry(tmp_path, checksum=true_sum))
    monkeypatch.setenv(bm.STORE_ENV, str(store))

    with pytest.raises(ValueError, match=r"n_designs|row"):
        bm.load_labels("cao2022")


def test_a_missing_label_column_is_an_error(tmp_path, monkeypatch):
    body = "sequence,target,outcome\nMKTAYIAK,CALCA,1\nGGSGGSWE,CALCA,0\n"
    store, true_sum = _make_store(tmp_path, body=body)
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", _make_registry(tmp_path, checksum=true_sum))
    monkeypatch.setenv(bm.STORE_ENV, str(store))

    with pytest.raises(ValueError, match="binds"):
        bm.load_labels("cao2022")


def test_the_loader_never_returns_an_empty_frame_silently(tmp_path, monkeypatch):
    """The failure mode this registry exists to prevent: a validation run that
    reports on zero designs and looks like it worked."""
    body = "sequence,target,binds\n"
    store, true_sum = _make_store(tmp_path, body=body)
    monkeypatch.setattr(bm, "BENCHMARKS_DIR", _make_registry(tmp_path, checksum=true_sum, n_designs=0))
    monkeypatch.setenv(bm.STORE_ENV, str(store))

    with pytest.raises(ValueError, match=r"no rows|empty"):
        bm.load_labels("cao2022")


def test_the_shipped_schema_is_valid_json_and_lists_the_required_fields():
    """SCHEMA.json is committed, so it is the public contract for a manifest."""
    schema = json.loads((bm.BENCHMARKS_DIR / "SCHEMA.json").read_text())
    required = set(schema["manifest_required_fields"])
    assert {"name", "n_designs", "label_column", "labels"} <= required
