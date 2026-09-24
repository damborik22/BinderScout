"""RFD3 must refuse to generate a run whose binders would be mislabelled.

`run_rfd3.sh` recovers the binder by stripping `len(target)` characters from the
front of each MPNN sequence, because RFD3's MPNN designs the whole complex. If
that length is 0, nothing is stripped and every delivered "binder" is the full
target+binder concatenation.

Nothing downstream notices: the campaign completes, prints its success line and
exits 0; `extract --rfd3` ingests it; even `validate` passes, because
`binder_shorter_than_target` is true of a concatenation. The human gets
mislabelled sequences after hours of GPU.

The subtlety is that an empty `target_sequence` is NOT sufficient to cause this.
`write_run_rfd3` already falls back to counting CA atoms on the primary chain,
and that fallback is correct and worth keeping. The failure needs the fallback
to ALSO yield zero — a chain letter that matches no atoms (the wizard does not
validate it) or an unreadable PDB. So the guard belongs on the computed length,
not on the config key.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

TARGET = "MKTAYIAKQRQ"
# Three CA atoms on chain A, so the fallback can recover a length of 3.
PDB_CHAIN_A = "".join(
    f"ATOM  {i:5d}  CA  ALA A {i:3d}       0.000   0.000   0.000  1.00  0.00           C\n" for i in (1, 2, 3)
)


def _cfg(tmp_path, **over):
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    pdb = tmp_path / "t.pdb"
    pdb.write_text(PDB_CHAIN_A)
    cfg = {"name": "T", "run_dir": str(run), "target_pdb": str(pdb), "target_sequence": TARGET}
    cfg.update(over)
    return cfg


def test_the_ca_count_fallback_still_works(tmp_path):
    """An empty target_sequence is fine when the chain is real — do not break
    this path by guarding on the config key instead of the computed length."""
    cfg = _cfg(tmp_path, target_sequence="", chains="A")
    out = Path(cfg["run_dir"]) / "run_rfd3.sh"
    conf.write_run_rfd3(out, cfg)
    assert out.exists()


@pytest.mark.parametrize(
    ("label", "over"),
    [
        ("chain matches no atoms", {"target_sequence": "", "chains": "Z"}),
        ("unreadable structure", {"target_sequence": "", "target_pdb": "/nonexistent/x.pdb"}),
        ("explicit null sequence", {"target_sequence": None, "chains": "Z"}),
    ],
)
def test_a_zero_target_length_is_refused(tmp_path, label, over):
    cfg = _cfg(tmp_path, **over)
    with pytest.raises(RuntimeError, match="target"):
        conf.write_run_rfd3(Path(cfg["run_dir"]) / "run.sh", cfg)


def test_the_refusal_explains_the_consequence(tmp_path):
    """A bare 'missing value' would not tell anyone why it matters."""
    cfg = _cfg(tmp_path, target_sequence="", chains="Z")
    with pytest.raises(RuntimeError) as exc:
        conf.write_run_rfd3(Path(cfg["run_dir"]) / "run.sh", cfg)
    msg = str(exc.value).lower()
    assert "binder" in msg
    assert "chain" in msg, "the likely cause is a wrong chain letter — say so"


def test_protein_hunter_keeps_its_own_guard(tmp_path):
    cfg = _cfg(tmp_path, target_sequence="")
    with pytest.raises(RuntimeError, match="target_sequence"):
        conf.write_run_protein_hunter(Path(cfg["run_dir"]) / "run.sh", cfg)
