"""Shared helpers for the per-candidate second-engine refold scripts.

Two things go wrong silently if these are wrong. A target-first PAE matrix read as
binder-first scores the wrong block (inflating ipTM, always upward); and a refold CSV whose
header differs from the AF3 one is not read by the merger the same way.
"""

from __future__ import annotations

import ast
import csv
from pathlib import Path

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.scoring import (  # noqa: E402
    add_iptm_from_pae_files,
    compute_iptm_from_pae,
)
from binder_comparison.refolding.second_engine import (  # noqa: E402
    REFOLD_CSV_FIELDS,
    to_binder_target_pae,
    write_refold_row,
)

AF3_SCRIPT = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts" / "refold_af3.py"
NB, NT = 2, 3


def _target_first() -> np.ndarray:
    """Asymmetric [target | binder] 5x5: every cell has a distinct value."""
    return np.arange(25, dtype=float).reshape(5, 5)


def test_target_first_matrix_is_reblocked_not_transposed():
    m = _target_first()
    out = to_binder_target_pae(m, NB, NT, order="target_binder")
    # [binder | target]: BB, BT / TB, TT -- each block moved whole, none transposed.
    assert np.array_equal(out[:NB, :NB], m[NT:, NT:])  # binder-binder
    assert np.array_equal(out[:NB, NB:], m[NT:, :NT])  # binder->target
    assert np.array_equal(out[NB:, :NB], m[:NT, NT:])  # target->binder
    assert np.array_equal(out[NB:, NB:], m[:NT, :NT])  # target-target
    assert not np.array_equal(out, m.T)
    assert out[0, NB] == m[NT, 0] == 15.0  # spot check: binder row 0 -> target col 0


def test_binder_first_matrix_is_returned_unchanged_as_a_copy():
    m = _target_first()
    out = to_binder_target_pae(m, NB, NT, order="binder_target")
    assert np.array_equal(out, m)
    out[0, 0] = -1.0
    assert m[0, 0] == 0.0


def test_reblock_matches_the_scoring_kernels_own_ordering():
    rng = np.random.default_rng(0)
    nb, nt = 7, 13
    m = rng.uniform(1.0, 30.0, size=(nb + nt, nb + nt))
    via_helper = compute_iptm_from_pae(to_binder_target_pae(m, nb, nt, order="target_binder"), nb)["iptm"]
    via_kernel = compute_iptm_from_pae(m, nb, ordering="target_binder")["iptm"]
    assert via_helper == pytest.approx(via_kernel)
    # and the unswapped reading is a different number, so this test can fail
    assert abs(compute_iptm_from_pae(m, nb, ordering="binder_target")["iptm"] - via_kernel) > 1e-6


def test_wrong_sized_matrix_is_refused():
    with pytest.raises(ValueError, match=r"\(n_binder \+ n_target\)"):
        to_binder_target_pae(np.zeros((6, 6)), NB, NT, order="target_binder")
    with pytest.raises(ValueError, match="6"):
        to_binder_target_pae(np.zeros((6, 6)), NB, NT, order="binder_target")


def test_non_square_or_non_2d_matrix_is_refused():
    with pytest.raises(ValueError):
        to_binder_target_pae(np.zeros((5, 4)), NB, NT, order="binder_target")
    with pytest.raises(ValueError):
        to_binder_target_pae(np.zeros(25), NB, NT, order="binder_target")


def test_unknown_order_is_refused():
    with pytest.raises(ValueError, match="order"):
        to_binder_target_pae(_target_first(), NB, NT, order="transposed")


def _af3_csv_fieldnames() -> list[str]:
    tree = ast.parse(AF3_SCRIPT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_csv_fieldnames":
            ret = next(n for n in ast.walk(node) if isinstance(n, ast.Return))
            return list(ast.literal_eval(ret.value))
    raise AssertionError("refold_af3.py has no _csv_fieldnames()")


def test_csv_header_is_exactly_the_af3_refold_header():
    assert list(REFOLD_CSV_FIELDS) == _af3_csv_fieldnames()


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def test_failed_design_row_is_blank_not_zero(tmp_path):
    out = tmp_path / "refold.csv"
    write_refold_row(
        out,
        {"run_id": "x_0001", "idx": "1", "sequence": "AAAA", "target_sequence": "CCCCC", "binder_length": "4"},
    )
    (row,) = _read(out)
    assert row["run_id"] == "x_0001" and row["binder_length"] == "4"
    for col in REFOLD_CSV_FIELDS[5:]:
        assert row[col] == "", col
    assert "error" not in row


def test_rows_append_and_header_is_written_once(tmp_path):
    out = tmp_path / "refold.csv"
    write_refold_row(out, {"run_id": "a", "idx": "0", "iptm": "0.5"})
    write_refold_row(out, {"run_id": "b", "idx": "1", "iptm": "0.6"})
    lines = out.read_text().splitlines()
    assert sum(ln.startswith("run_id,") for ln in lines) == 1
    assert [r["run_id"] for r in _read(out)] == ["a", "b"]


def test_header_is_written_to_an_existing_empty_file(tmp_path):
    out = tmp_path / "refold.csv"
    out.write_text("")
    write_refold_row(out, {"run_id": "a"})
    assert out.read_text().splitlines()[0] == ",".join(REFOLD_CSV_FIELDS)


def test_unknown_column_is_refused_and_named(tmp_path):
    out = tmp_path / "refold.csv"
    with pytest.raises(ValueError, match="error"):
        write_refold_row(out, {"run_id": "a", "error": "boom"})
    assert not out.exists() or out.read_text() == ""


def test_derived_column_carries_the_engine_name_given_at_merge_time(tmp_path):
    pae_path = tmp_path / "d0_pae.npy"
    nb, nt = 4, 6
    pae = np.full((nb + nt, nb + nt), 20.0)
    pae[:nb, nb:] = 3.0
    np.save(pae_path, pae)
    out = tmp_path / "refold.csv"
    write_refold_row(
        out,
        {
            "run_id": "d0",
            "idx": "0",
            "sequence": "A" * nb,
            "target_sequence": "C" * nt,
            "binder_length": str(nb),
            "pae_file": str(pae_path),
        },
    )
    df = pd.read_csv(out)
    merged = add_iptm_from_pae_files(df, "pae_file", ordering="binder_target", prefix="openfold3")
    assert "openfold3_pae_iptm" in merged.columns
    assert "af3_pae_iptm" not in merged.columns
    assert merged["openfold3_pae_iptm"].notna().all()
