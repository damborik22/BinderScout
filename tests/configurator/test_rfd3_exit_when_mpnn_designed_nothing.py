"""run_rfd3.sh must not exit 0 when ProteinMPNN produced no sequence for any backbone.

The aggregation step used to print a warning and `exit 0`, and the mpnn calls ran with their output
sent to /dev/null, so a run where every mpnn call failed finished "successfully" with no
sequences.csv and no log to read. Found in the v2.0.3 end-to-end run (a latent risk there; the run
itself worked) and fixed under the standing rule that silent success is a failure.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "binderscout_examples" / "run_rfd3.sh.template"

PDB = "".join(
    f"ATOM  {i:5d}  CA  ALA A{i:4d}    {float(i):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C\n"
    for i in range(1, 6)
)


@pytest.fixture
def generated(tmp_path):
    run_dir = tmp_path / "runs" / "t"
    run_dir.mkdir(parents=True)
    pdb = tmp_path / "target.pdb"
    pdb.write_text(PDB)
    cfg = {
        "name": "t",
        "run_dir": run_dir,
        "target_pdb": pdb,
        "target_pdb_src": str(pdb),
        "target_sequence": "AAAAA",
        "chains": "A",
        "hotspots": "1,2",
        "min_length": 20,
        "max_length": 30,
        "n_designs": 1,
    }
    script = run_dir / "run_rfd3.sh"
    conf.write_run_rfd3(script, cfg)
    return script


def _aggregate(script_text: str, mpnn_dir: Path, out_dir: Path):
    lines = script_text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith('python3 - "$MPNN_DIR"'))
    end = next(i for i in range(start, len(lines)) if lines[i] == "PYEOF")
    program = "\n".join(lines[start + 1 : end])
    return subprocess.run(
        [sys.executable, "-c", program, str(mpnn_dir), str(out_dir), "AAAAA"], capture_output=True, text=True
    )


def test_no_sequence_from_any_backbone_is_a_failure(generated, tmp_path):
    mpnn = tmp_path / "mpnn"
    mpnn.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    proc = _aggregate(generated.read_text(), mpnn, out)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "nothing was designed" in proc.stderr


def test_control_a_real_mpnn_file_still_aggregates(generated, tmp_path):
    """Without this the test above would pass for a script whose aggregation cannot run at all."""
    mpnn = tmp_path / "mpnn"
    mpnn.mkdir()
    (mpnn / "bb1.fa").write_text(">bb1, sequence_recovery=0.2\nAAAAAMKLVEDLKQ\n")
    out = tmp_path / "out"
    out.mkdir()
    proc = _aggregate(generated.read_text(), mpnn, out)
    assert proc.returncode == 0, proc.stderr
    assert "MKLVEDLKQ" in (out / "sequences.csv").read_text()


@pytest.mark.parametrize("source", ["generated", "template"])
def test_mpnn_output_is_kept_per_backbone_not_discarded(source, generated):
    text = generated.read_text() if source == "generated" else TEMPLATE.read_text()
    assert "> /dev/null 2>&1 || {" not in text, "mpnn output is still discarded"
    assert ".log" in text and "mpnn failed for" in text


def test_the_template_also_refuses_an_empty_pool():
    assert "nothing was designed" in TEMPLATE.read_text()
