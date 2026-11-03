"""rfd3_gate.check_geometry on a binder below its CA-count floor.

The shipped smoke binder is 24 aa; the gate kept a backbone only at >= 25 CA atoms and then
printed "no chain-B CA atoms found -- CANNOT VERIFY", which is false: its own parser finds all 24.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "tools" / "rfd3_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("rfd3_gate_under_test", GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_cif(path: Path, n_chain_b: int) -> Path:
    """Minimal mmCIF: a short chain A and a helical chain B of ``n_chain_b`` CA atoms."""
    lines = [
        "data_x",
        "loop_",
        "_atom_site.label_atom_id",
        "_atom_site.label_asym_id",
        "_atom_site.Cartn_x",
        "_atom_site.Cartn_y",
        "_atom_site.Cartn_z",
    ]
    for i in range(5):
        lines.append(f"CA A {i * 3.8:.3f} 20.000 0.000")
    for i in range(n_chain_b):
        a = i * 100 * math.pi / 180
        lines.append(f"CA B {2.3 * math.cos(a):.3f} {2.3 * math.sin(a):.3f} {1.5 * i:.3f}")
    lines.append("#")
    path.write_text("\n".join(lines) + "\n")
    return path


class TestShortBinderIsNotReportedAsMissing:
    def test_24_aa_binder_is_named_as_too_short_not_as_absent(self, tmp_path, capsys):
        gate = _load_gate()
        _write_cif(tmp_path / "d0.cif", 24)
        verdict = gate.check_geometry(str(tmp_path / "*.cif"))
        out = capsys.readouterr().out
        assert verdict is None, "a binder under the floor is 'cannot verify', not a pass and not a failure"
        assert "no chain-B CA atoms" not in out, "the 24 chain-B CA atoms are there; saying otherwise is false"
        assert "24 aa" in out and "minimum" in out

    def test_no_chain_b_still_says_so(self, tmp_path, capsys):
        """Control: the genuine empty case keeps its message."""
        gate = _load_gate()
        _write_cif(tmp_path / "d0.cif", 0)
        assert gate.check_geometry(str(tmp_path / "*.cif")) is None
        assert "no chain-B CA atoms" in capsys.readouterr().out

    def test_binder_at_the_floor_is_still_measured(self, tmp_path, capsys):
        """Control: the floor itself did not move."""
        gate = _load_gate()
        _write_cif(tmp_path / "d0.cif", 25)
        assert gate.check_geometry(str(tmp_path / "*.cif")) is not None
        assert "backbones checked" in capsys.readouterr().out
