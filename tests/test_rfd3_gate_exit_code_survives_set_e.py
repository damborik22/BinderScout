"""The shell that reads the RFD3 gate's exit code (template and configurator emitter).

The scripts run under ``set -euo pipefail`` and called the gate as a bare command whose
status was read with ``case $?``. Exit 2 ("could not verify") trips ``set -e`` first, so the
documented ``[warn] ... Continuing`` branch and RFD3_IGNORE_GATE were unreachable and
ProteinMPNN never ran (RFD3 yielded 0 designs).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "binderscout_examples" / "run_rfd3.sh.template"

sys.path.insert(0, str(REPO / "configurator"))
import configurator as conf  # noqa: E402

STUB = """\
import os, sys
sys.exit(int(os.environ["STUB_" + sys.argv[1].upper()]))
"""


def _block_from_template() -> str:
    text = TEMPLATE.read_text()
    return text[text.index('GATE="$BMDIR/tools/rfd3_gate.py"') : text.index("# ── Stage 2")]


def _block_from_emitter(tmp_path: Path) -> str:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    target = tmp_path / "t.pdb"
    target.write_text("ATOM ...")
    cfg = {
        "name": "t",
        "run_dir": run_dir,
        "target_pdb": target,
        "target_pdb_src": str(target),
        "target_sequence": "MAEVKLSYVL",
        "chains": "A",
        "hotspots": "10,20,30",
        "min_length": 65,
        "max_length": 150,
        "n_designs": 10,
    }
    script = tmp_path / "run_rfd3.sh"
    conf.write_run_rfd3(script, cfg)
    text = script.read_text()
    return text[text.index('GATE="') : text.index("# ── Stage 2")]


def _run(block: str, tmp_path: Path, origin: int, geometry: int, ignore: bool = False):
    stub = tmp_path / "stub_gate.py"
    stub.write_text(STUB)
    lines = block.splitlines()
    gate_line = next(i for i, ln in enumerate(lines) if ln.startswith("GATE="))
    lines[gate_line] = f'GATE="{stub}"'
    script = "set -euo pipefail\nDIFF_DIR=/nonexistent\n" + "\n".join(lines) + "\necho REACHED\n"
    env = {k: v for k, v in os.environ.items() if k != "RFD3_IGNORE_GATE"}
    env.update(STUB_ORIGIN=str(origin), STUB_GEOMETRY=str(geometry))
    if ignore:
        env["RFD3_IGNORE_GATE"] = "1"
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


@pytest.fixture(params=["template", "emitter"])
def block(request, tmp_path):
    if request.param == "template":
        return _block_from_template()
    return _block_from_emitter(tmp_path)


def test_the_set_e_trap_is_real():
    """Control: the OLD pattern really does die before the case."""
    old = 'set -euo pipefail; python3 -c "import sys;sys.exit(2)"; case $? in 2) ;; esac; echo REACHED'
    p = subprocess.run(["bash", "-c", old], capture_output=True, text=True)
    assert p.returncode == 2 and "REACHED" not in p.stdout


def test_exit_0_passes_silently(block, tmp_path):
    p = _run(block, tmp_path, 0, 0)
    assert p.returncode == 0 and "REACHED" in p.stdout
    assert "[warn]" not in p.stdout


@pytest.mark.parametrize(("origin", "geometry"), [(2, 2), (0, 2), (2, 0)])
def test_exit_2_warns_and_continues(block, tmp_path, origin, geometry):
    p = _run(block, tmp_path, origin, geometry)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "REACHED" in p.stdout, "ProteinMPNN would never run"
    assert "[warn] The geometry gate could not verify" in p.stdout
    assert "Continuing" in p.stdout


def test_exit_1_fails_the_run(block, tmp_path):
    p = _run(block, tmp_path, 0, 1)
    assert p.returncode == 1 and "REACHED" not in p.stdout
    assert "look like coils" in p.stdout


def test_exit_1_is_overridable_by_ignore_gate(block, tmp_path):
    p = _run(block, tmp_path, 1, 0, ignore=True)
    assert p.returncode == 0 and "REACHED" in p.stdout
    assert "RFD3_IGNORE_GATE set" in p.stdout


def test_a_failure_outranks_an_unverified_check(block, tmp_path):
    p = _run(block, tmp_path, 2, 1)
    assert p.returncode == 1 and "REACHED" not in p.stdout
