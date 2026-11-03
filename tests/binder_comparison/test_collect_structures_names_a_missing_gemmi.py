"""`extract --collect-structures` reported a bare "collected 0/N" for every mmCIF-writing tool
when gemmi was absent (it is deliberately absent from binder-eval). The explanatory warning
sat behind an early `return 0` and could never fire. Found in the v2.0.3 end-to-end run.
"""

from __future__ import annotations

import sys
import warnings

import pytest

pytest.importorskip("pandas")

from binder_comparison.structures import collect_design_structures  # noqa: E402

CIF = "data_x\n_cell.length_a 1\n"


def test_mmcif_structures_that_cannot_be_read_are_named_not_counted_as_zero(tmp_path, monkeypatch):
    src = tmp_path / "designs"
    src.mkdir()
    (src / "d1.cif").write_text(CIF)
    (src / "d2.cif").write_text(CIF)
    monkeypatch.setitem(sys.modules, "gemmi", None)  # makes `import gemmi` raise ImportError
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        n = collect_design_structures(src, ["MK"], tmp_path / "out")
    assert n == 0
    text = " ".join(str(w.message) for w in caught)
    assert "gemmi is not installed" in text and "2 mmCIF" in text, text


def test_control_a_directory_without_any_mmcif_stays_quiet(tmp_path, monkeypatch):
    """The warning must not fire for tools that simply write nothing we can match."""
    src = tmp_path / "designs"
    src.mkdir()
    (src / "notes.txt").write_text("nothing")
    monkeypatch.setitem(sys.modules, "gemmi", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert collect_design_structures(src, ["MK"], tmp_path / "out") == 0
    assert not [w for w in caught if "gemmi" in str(w.message)]
