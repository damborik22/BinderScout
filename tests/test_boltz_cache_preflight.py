"""A half-downloaded ~/.boltz cache must be refused with a readable message.

``boltz.main.download_boltz2`` decides what to fetch by whether a path EXISTS -- not
by size, not by integrity. An interrupted download is therefore permanently sticky:
re-running the documented bootstrap prints its normal "Downloading ..." banner, skips
every incomplete artifact, and reports success.

Measured 2026-09-27 on a cache interrupted three days earlier:

  * ``boltz2_conf.ckpt``  0.21 GB of ~2.3 GB, not a valid zip
  * ``boltz2_aff.ckpt``   absent
  * ``mols/``             2,949 of 45,227 entries -- ALA, GLY, SER, LYS all missing
                          while GLU was present

Each broken path had to be deleted by hand before the downloader would replace it. The
failures point nowhere near the cause: a truncated checkpoint surfaces as
``PytorchStreamReader failed reading zip archive: failed finding central directory``
from inside pytorch_lightning, and missing canonical residues as ``ValueError: CCD
component ALA not found!`` from the tokenizer.

The helper is extracted from the script's source rather than imported, so these run
in CI: importing ``refold_boltz2`` needs jax, equinox, torch and mosaic, none of which
are present in ``binder-eval``.
"""

from __future__ import annotations

import os
import pathlib
import zipfile

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "Evaluator" / "scripts" / "refold_boltz2.py"


@pytest.fixture(scope="module")
def check():
    src = _SCRIPT.read_text()
    assert "def _check_boltz_cache(" in src, "refold_boltz2 lost its cache preflight"
    start = src.index("def _check_boltz_cache(")
    end = src.index("def refold_batch(")
    namespace: dict = {"os": os}
    exec(compile(src[start:end], str(_SCRIPT), "exec"), namespace)
    return namespace["_check_boltz_cache"]


def test_an_absent_cache_is_not_a_problem(check, tmp_path):
    """Boltz downloads on first use, so 'nothing there yet' must stay silent."""
    check(tmp_path / "does-not-exist")


def test_a_complete_cache_passes(check, tmp_path):
    mols = tmp_path / "mols"
    mols.mkdir()
    for residue in ("ALA", "GLY", "SER", "LYS", "GLU", "TRP"):
        (mols / f"{residue}.pkl").write_bytes(b"x")
    ckpt = tmp_path / "boltz2_conf.ckpt"
    with zipfile.ZipFile(ckpt, "w") as zf:
        zf.writestr("data.pkl", "x")
    check(tmp_path)


def test_a_truncated_checkpoint_is_refused(check, tmp_path):
    (tmp_path / "boltz2_conf.ckpt").write_bytes(b"not a zip archive")
    with pytest.raises(RuntimeError) as err:
        check(tmp_path)
    msg = str(err.value)
    assert "boltz2_conf.ckpt" in msg
    assert "will NOT repair" in msg, "the message must say re-running the downloader is not enough"
    assert "rm -rf" in msg, "the message must give the deletion step that actually fixes it"


def test_missing_canonical_residues_are_refused_even_when_some_exist(check, tmp_path):
    """The exact observed shape: GLU present, ALA absent. A single spot-check on one
    residue would have passed this cache, which is why every canonical residue is
    probed."""
    mols = tmp_path / "mols"
    mols.mkdir()
    (mols / "GLU.pkl").write_bytes(b"x")
    with pytest.raises(RuntimeError) as err:
        check(tmp_path)
    msg = str(err.value)
    assert "ALA" in msg and "canonical residues" in msg
    assert "GLU" not in msg.split("missing canonical residues")[1].split("(")[0], (
        "GLU was present and must not be listed as missing"
    )


def test_it_reports_every_broken_artifact_at_once(check, tmp_path):
    """Two round trips to discover two faults is how this took three attempts to fix."""
    (tmp_path / "boltz2_conf.ckpt").write_bytes(b"nope")
    (tmp_path / "mols").mkdir()
    with pytest.raises(RuntimeError) as err:
        check(tmp_path)
    msg = str(err.value)
    assert "boltz2_conf.ckpt" in msg and "canonical residues" in msg, (
        f"both faults should be named in one refusal, got: {msg}"
    )
