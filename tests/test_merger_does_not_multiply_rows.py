"""Duplicate rows in a refold CSV must not cartesian-product through the merge.

`merge_refold_results` joins the engine CSVs with
``pd.merge(..., on="sequence", how="outer")``. That is a many-to-many join, so K
duplicate rows for one sequence in each of N engines produce **K**N** rows for
that single design.

Measured 2026-09-28 on the golden pool (6 designs), duplicating ONE sequence:

    2 rows in boltz2 only          ->  7 total,  that design occupies  2 rows
    2 rows in boltz2 + af3         ->  9 total,                        4 rows
    2 rows in all three            -> 13 total,                        8 rows
    3 rows in all three            -> 32 total,                       27 rows

Everything downstream is pool-relative -- percentiles, top-N, per-tool means,
z-scores and `rank` -- so one design counted 27 times corrupts all of them, and
the merger's own banner reports "13 unique sequences" when there are 6.

This is Part AC's seed hazard, and it was live: `merger.py` deduplicates the FASTA
metadata (`:129`) but not the engine frames. `cli/report.py:729` already had the
right shape -- drop_duplicates, warn, then `validate=` on the join so a future
regression errors rather than silently inflating -- and that is what is mirrored
here.

Reachability: `extract` deduplicates by sequence, so two tools emitting the same
binder cannot trigger it, and AF3 collapses its seeds into one row. What remains
is the documented append path -- CLAUDE.md, "refold_boltz2.py appends to CSV. If
rerun after partial failure, check for duplicate run_id entries."
"""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.merger import merge_refold_results  # noqa: E402

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "integration" / "golden_pool"
ENGINES = ("boltz2", "af3", "esmfold2")


def _pool_with_duplicates(tmp_path, dups: dict[str, int]) -> tuple[dict[str, Path], str, int]:
    """Copy the golden pool, repeating ONE shared sequence `dups[engine]` times."""
    target = pd.read_csv(GOLDEN / "boltz2_results.csv").iloc[0]["sequence"]
    paths = {}
    for engine in ENGINES:
        df = pd.read_csv(GOLDEN / f"{engine}_results.csv")
        row = df[df["sequence"] == target]
        assert not row.empty, f"{engine} golden CSV lost the shared sequence"
        out = tmp_path / f"{engine}.csv"
        pd.concat([df] + [row] * (dups.get(engine, 1) - 1), ignore_index=True).to_csv(out, index=False)
        paths[engine] = out
    return paths, target, len(pd.read_csv(GOLDEN / "boltz2_results.csv"))


def _merge(paths: dict[str, Path]):
    return merge_refold_results(boltz2_csv=paths["boltz2"], af3_csv=paths["af3"], esmfold2_csv=paths["esmfold2"])


def test_the_clean_pool_is_one_row_per_design(tmp_path):
    """Control: without duplicates the merge is already correct."""
    paths, target, n_designs = _pool_with_duplicates(tmp_path, {})
    merged = _merge(paths)
    assert len(merged) == n_designs
    assert int((merged["sequence"] == target).sum()) == 1


@pytest.mark.parametrize(
    "dups",
    [
        {"boltz2": 2},
        {"boltz2": 2, "af3": 2},
        {"boltz2": 2, "af3": 2, "esmfold2": 2},
        {"boltz2": 3, "af3": 3, "esmfold2": 3},
    ],
    ids=["one-engine", "two-engines", "all-three", "three-deep"],
)
def test_duplicates_never_multiply_the_pool(tmp_path, dups):
    paths, target, n_designs = _pool_with_duplicates(tmp_path, dups)
    with pytest.warns(UserWarning, match="duplicate"):
        merged = _merge(paths)

    occupies = int((merged["sequence"] == target).sum())
    assert occupies == 1, (
        f"one design occupies {occupies} rows after {dups} — the outer merge "
        "cartesian-producted it; every pool-relative statistic is now computed "
        "over an inflated pool"
    )
    assert len(merged) == n_designs, f"pool inflated from {n_designs} to {len(merged)} rows"


def test_the_operator_is_told_it_happened(tmp_path):
    """Silently dropping rows would hide a broken input CSV. The count and the
    engine must both be named, because the fix is to find the CSV that was
    appended to twice."""
    paths, _, _ = _pool_with_duplicates(tmp_path, {"boltz2": 3})
    with pytest.warns(UserWarning) as record:
        _merge(paths)
    text = " ".join(str(w.message) for w in record)
    assert "boltz" in text, f"the warning must name the engine: {text}"
    assert "2" in text, f"the warning must say how many rows were dropped: {text}"
