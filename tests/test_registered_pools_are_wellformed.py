"""Every manifest actually committed to the registry must be loadable and auditable.

`test_benchmarks.py` covers the library against synthetic manifests under `tmp_path`.
Nothing checked the real ones, so a malformed manifest could be committed and would only
surface when someone tried to load that pool -- by which time the number it produced has
a right-looking name attached.

These run on a machine with no private data, which is every CI run and every fresh clone.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from binder_comparison import benchmarks as b

REPO = Path(__file__).resolve().parent.parent
REGISTERED = sorted(p.parent.name for p in (REPO / "Evaluator/benchmarks").glob("*/MANIFEST.json"))


def test_at_least_the_registry_directory_exists():
    assert (REPO / "Evaluator/benchmarks/SCHEMA.json").is_file(), "the registry's schema is gone"


@pytest.mark.skipif(not REGISTERED, reason="no pools registered yet")
@pytest.mark.parametrize("pool", REGISTERED)
class TestRegisteredPool:
    def test_manifest_loads_and_has_the_audit_fields(self, pool):
        m = b.load_manifest(pool)  # raises if a required field is missing
        for f in b.REQUIRED_FIELDS:
            assert f in m

    def test_name_matches_its_directory(self, pool):
        # load_manifest() interpolates the id into a path under both the public manifest
        # dir and the PRIVATE label store. A manifest whose name disagrees with its
        # directory loads one pool's provenance against another pool's rows.
        assert b.load_manifest(pool)["name"] == pool

    def test_checksum_is_a_real_sha256(self, pool):
        sha = b.load_manifest(pool)["labels"]["sha256"]
        assert re.fullmatch(r"[0-9a-f]{64}", sha), (
            f"{pool}: labels.sha256 is {sha!r}, not a 64-char lowercase hex digest. "
            "A placeholder here disables the one check that the rows are the right rows."
        )

    def test_n_designs_is_a_positive_int(self, pool):
        n = b.load_manifest(pool)["n_designs"]
        assert isinstance(n, int) and not isinstance(n, bool) and n > 0, f"{pool}: n_designs={n!r}"

    def test_the_label_file_is_not_in_the_repo(self, pool):
        """The rows are private; this repo is public, and publishing them is irreversible."""
        fn = b.load_manifest(pool)["labels"]["filename"]
        assert not (REPO / "Evaluator/benchmarks" / pool / fn).exists(), (
            f"{pool}: {fn} is sitting in the repo next to its manifest. The whole point of "
            "the split is that the rows live outside the tree."
        )
        hits = subprocess.run(
            ["git", "ls-files", "--", f"Evaluator/benchmarks/{pool}/{fn}"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        assert not hits, f"{pool}: {fn} is TRACKED by git — unpublish it and rotate the data"

    def test_the_label_filename_would_be_gitignored(self, pool):
        """Not just absent today: it must be impossible to add by accident.

        `git add` on an ignored path is refused without `-f`, so this is the guard that
        actually prevents the irreversible mistake.
        """
        fn = b.load_manifest(pool)["labels"]["filename"]
        rel = f"Evaluator/benchmarks/{pool}/{fn}"
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO, check=False)
        if r.returncode == 128:
            pytest.skip("git unavailable")
        assert r.returncode == 0, (
            f"{rel} is NOT gitignored, so `git add` would stage private label rows into a "
            "public repo. .gitignore carries data-extension rules under "
            "Evaluator/benchmarks/** with a negation for MANIFEST.json; this filename "
            "escapes them."
        )

    def test_loading_rows_without_a_store_is_an_error_naming_the_env_var(self, pool, monkeypatch):
        monkeypatch.delenv(b.STORE_ENV, raising=False)
        with pytest.raises(FileNotFoundError, match=b.STORE_ENV):
            b.load_labels(pool)

    def test_caveats_are_present_and_not_a_stub(self, pool):
        """Optional in the schema, required here.

        Every pool we have touched had a label-quality problem that changed a number:
        Cao's one-sided Kd, Adaptyv's non-expressed-as-non-binder, the labelled-vs-scored
        distinction. A pool registered with no caveats is far more likely to be
        under-documented than genuinely clean.
        """
        c = b.load_manifest(pool).get("caveats", "")
        assert isinstance(c, str) and len(c.strip()) >= 40, (
            f"{pool}: caveats is {c!r}. Record the known label-quality problems, or say "
            "explicitly that none are known and why."
        )


@pytest.mark.skipif("adaptyv" not in REGISTERED, reason="adaptyv not registered")
def test_adaptyv_records_the_two_bounds_that_limit_what_it_can_support():
    """The two facts that make an adaptyv number mean less than it looks.

    Pinned because both are easy to lose in a reword, and either one dropped turns a
    correctly-caveated pool into a misleading one: the 0.7113 is computed on 563 of the
    2018 designs, and the nipah labels disagree with the source table.
    """
    c = b.load_manifest("adaptyv")["caveats"].lower()
    assert "563" in c, "the labelled-vs-scored bound (563 of 2018) is gone from the caveats"
    assert "nipah" in c, "the unresolved nipah label discrepancy is gone from the caveats"


@pytest.mark.skipif(not REGISTERED, reason="no pools registered yet")
@pytest.mark.parametrize("pool", REGISTERED)
def test_manifest_declares_an_outcome_column(pool: str) -> None:
    """Every pool must name a column carrying an explicit experimental outcome.

    This is the structural form of the 2026-10-03 label error. A panel's empty Kd cells were
    read as "tested, did not bind" when they marked designs that had never been ordered; the
    sheet recorded that with a divider row, and the other panel used an explicit ``N/A`` for
    tested-and-not-bound which ``pd.read_csv`` silently converts to ``NaN``. Eleven such rows
    dragged a 114-design AUC from 0.706 to 0.4835, caught only because a reviewer noticed they
    outranked 81 % of the confirmed binders.

    An inference from a blank cell is what failed, so the outcome is a required column with no
    default and no fallback.
    """
    m = b.load_manifest(pool)
    assert "outcome_column" in m, f"{pool}: no outcome_column — a blank cell must never imply a negative"
    assert isinstance(m["outcome_column"], str) and m["outcome_column"].strip()


def test_the_loader_refuses_a_row_with_no_outcome(tmp_path, monkeypatch) -> None:
    """The guard has to fire on data, not just exist in the manifest."""
    import json

    import pandas as pd

    reg = tmp_path / "benchmarks" / "p"
    reg.mkdir(parents=True)
    store = tmp_path / "store" / "p"
    store.mkdir(parents=True)
    rows = pd.DataFrame({"id": ["a", "b"], "binds": [1, 0], "outcome": ["bound", ""]})
    f = store / "labels.csv"
    rows.to_csv(f, index=False)
    import hashlib

    (reg / "MANIFEST.json").write_text(
        json.dumps(
            {
                "name": "p",
                "n_designs": 2,
                "label_column": "binds",
                "outcome_column": "outcome",
                "labels": {"filename": "labels.csv", "sha256": hashlib.sha256(f.read_bytes()).hexdigest()},
            }
        )
    )
    monkeypatch.setattr(b, "BENCHMARKS_DIR", tmp_path / "benchmarks")
    monkeypatch.setenv(b.STORE_ENV, str(tmp_path / "store"))
    with pytest.raises(ValueError, match="empty"):
        b.load_labels("p")


def test_the_loader_refuses_an_unrecognised_outcome(tmp_path, monkeypatch) -> None:
    """ "probably didn't bind" is not an outcome."""
    import hashlib
    import json

    import pandas as pd

    reg = tmp_path / "benchmarks" / "p"
    reg.mkdir(parents=True)
    store = tmp_path / "store" / "p"
    store.mkdir(parents=True)
    f = store / "labels.csv"
    pd.DataFrame({"id": ["a"], "binds": [0], "outcome": ["maybe"]}).to_csv(f, index=False)
    (reg / "MANIFEST.json").write_text(
        json.dumps(
            {
                "name": "p",
                "n_designs": 1,
                "label_column": "binds",
                "outcome_column": "outcome",
                "labels": {"filename": "labels.csv", "sha256": hashlib.sha256(f.read_bytes()).hexdigest()},
            }
        )
    )
    monkeypatch.setattr(b, "BENCHMARKS_DIR", tmp_path / "benchmarks")
    monkeypatch.setenv(b.STORE_ENV, str(tmp_path / "store"))
    with pytest.raises(ValueError, match="unrecognised"):
        b.load_labels("p")
    # ...but excluded:<reason> is
    pd.DataFrame({"id": ["a"], "binds": [0], "outcome": ["excluded:never ordered"]}).to_csv(f, index=False)
    man = json.loads((reg / "MANIFEST.json").read_text())
    man["labels"]["sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()
    (reg / "MANIFEST.json").write_text(json.dumps(man))
    assert len(b.load_labels("p")) == 1
