"""Each engine's PAE ordering is pinned, and a matrix that cannot be what it claims is refused.

Measured 2026-11-03 on the archived TfR1 pool (n=450 per engine): Boltz-2 saves the
binder block FIRST, AF3 and ESMFold2 save the target FIRST. The `ordering=` flag at
the call site in cli/report.py is what encodes that, and nothing pinned it -- flipping
AF3's moves its whole ipTM column by about +0.5, always UPWARD (the mis-sliced block
contains intra-chain PAE), so it would not look like a failure, it would look like
AF3 got better.

Likewise nothing checked that the matrix size equals binder_length + target length.
Miscounting binder_length by one residue inflates ipTM by up to +0.31; an all-zero
interface block scores a perfect 1.0; NaN used to become an ipsae of 0.0 ("Reject").
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.scoring import (  # noqa: E402
    add_iptm_from_pae_files,
    compute_ipsae_from_pae,
    compute_iptm_from_pae,
)

REPORT = Path(__file__).resolve().parents[2] / "Evaluator" / "binder_comparison" / "cli" / "report.py"
EXPECTED_ORDERING = {
    "boltz_pae_file": "binder_target",
    "af3_pae_file": "target_binder",
    "esmfold2_pae_file": "target_binder",
}

LB, LT = 20, 60


def _pae(first_block: str) -> np.ndarray:
    """A plausible binder: intra-chain PAE 3 A, cross-chain 18 A, with one good 8x12 patch (2 A)."""
    n = LB + LT
    pae = np.full((n, n), 18.0)
    binder = np.arange(LB) if first_block == "binder" else np.arange(LT, n)
    target = np.arange(LB, n) if first_block == "binder" else np.arange(LT)
    pae[np.ix_(binder, binder)] = 3.0
    pae[np.ix_(target, target)] = 3.0
    pae[np.ix_(binder[:8], target[:12])] = 2.0
    pae[np.ix_(target[:12], binder[:8])] = 2.0
    return pae


def test_report_passes_the_right_ordering_for_every_engine():
    tree = ast.parse(REPORT.read_text())
    seen: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id not in {"add_iptm_from_pae_files", "add_ipsae_from_pae_files"}:
            continue
        kw = {k.arg: k.value for k in node.keywords}
        col, order = kw.get("pae_file_col"), kw.get("ordering")
        if isinstance(col, ast.Constant) and isinstance(order, ast.Constant):
            seen.setdefault(col.value, set()).add(order.value)
    for col, expected in EXPECTED_ORDERING.items():
        assert seen.get(col) == {expected}, (
            f"{col}: report.py passes ordering {seen.get(col)}, expected only {expected!r}. "
            "A flipped flag inflates that engine's ipTM column by ~0.5 and looks like a better engine."
        )


def test_the_flag_means_what_the_table_says():
    """A target-first matrix is read correctly only under 'target_binder'."""
    right = compute_iptm_from_pae(_pae("target"), LB, ordering="target_binder")["iptm"]
    wrong = compute_iptm_from_pae(_pae("target"), LB, ordering="binder_target")["iptm"]
    assert right == pytest.approx(compute_iptm_from_pae(_pae("binder"), LB, ordering="binder_target")["iptm"])
    assert abs(wrong - right) > 0.05, (right, wrong)


def _frame(tmp_path, pae, binder_length, target_sequence="T" * LT):
    f = tmp_path / "x_pae.npy"
    np.save(f, pae)
    return pd.DataFrame([{"binder_length": binder_length, "target_sequence": target_sequence, "p": str(f)}])


def _score(df, ordering="binder_target"):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = add_iptm_from_pae_files(df, "p", ordering=ordering, prefix="e")
    return out["e_pae_iptm"].iloc[0], [str(x.message) for x in w]


def test_a_correctly_sized_matrix_scores(tmp_path):
    score, _ = _score(_frame(tmp_path, _pae("binder"), LB))
    assert score > 0.05


@pytest.mark.parametrize("delta", [1, -1, 3])
def test_a_miscounted_binder_length_is_refused_not_inflated(tmp_path, delta):
    """The wrong slice used to score (up to +0.31 per residue); now the row gets NaN and a named warning."""
    # binder_length wrong by `delta` while the target sequence is right: the sizes no longer add up.
    score, msgs = _score(_frame(tmp_path, _pae("binder"), LB + delta))
    assert np.isnan(score)
    assert any("refusing to guess" in m for m in msgs), msgs


def test_an_all_zero_interface_is_refused_not_perfect(tmp_path):
    score, msgs = _score(_frame(tmp_path, np.zeros((LB + LT, LB + LT)), LB))
    assert np.isnan(score), "a placeholder PAE file scored a perfect 1.0"
    assert any("identically zero" in m for m in msgs), msgs


def test_a_row_without_a_target_sequence_is_still_scored(tmp_path):
    """The size check needs the target; its absence must not silently disable scoring."""
    score, _ = _score(_frame(tmp_path, _pae("binder"), LB, target_sequence=None))
    assert score > 0.05


def test_non_finite_pae_is_missing_data_not_a_reject():
    bad = _pae("binder")
    bad[3, 40] = np.nan
    ip = compute_ipsae_from_pae(bad, LB)
    assert np.isnan(ip["ipsae_min"]), "unreadable data was filed as ipsae 0.0 (the Reject tier)"
    assert ip["ipsae_valid"] == 0
    assert np.isnan(compute_iptm_from_pae(bad, LB)["iptm"])
