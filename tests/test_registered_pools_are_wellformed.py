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
