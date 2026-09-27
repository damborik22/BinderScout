"""Completed Boltz-2 folds must reach the caller's CSV even if the run later dies.

``refold_batch`` writes each finished design to ``refold_designs.csv`` immediately, but
the copy to the caller's ``--output`` path used to happen only once ``refold_batch``
RETURNED. Anything that kills the process inside it therefore stranded finished work
under a filename the rest of the pipeline does not read.

Measured 2026-09-27 on a 12 GB card: all 8 CALCA designs folded and were written, then
XLA aborted in allocator teardown --
``bfc_allocator.cc:1065 Check failed: central_gap_ == kInvalidChunkHandle`` -- and the
requested CSV was never created. ``--resume`` did not rescue it: it correctly skipped all
8 and hit the same CHECK, 2 runs out of 2. A ``try/finally`` cannot rescue it either,
because a C++ ``CHECK`` raises SIGABRT, which Python never sees. The only thing that
works is publishing what is already on disk BEFORE folding, so a re-run recovers.

These tests exercise ``_publish_csv`` directly; the runner's own call sites are two lines
around it. Importing the runner needs pandas only, not torch or jax, so they run in CI.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from binder_comparison.refolding.boltz2_runner import _publish_csv

_ROW = {
    "run_id": "abc123",
    "idx": "1",
    "sequence": "AAAA",
    "iptm": "0.83",
    "pdb": "structures/refold1_abc123.pdb",
    "pae_file": "structures/refold1_abc123_pae.npy",
    "plddt_file": "structures/refold1_abc123_plddt.csv",
}


def _write_generated(out_dir: Path) -> Path:
    (out_dir / "structures").mkdir(parents=True, exist_ok=True)
    for key in ("pdb", "pae_file", "plddt_file"):
        (out_dir / _ROW[key]).write_text("x")
    generated = out_dir / "refold_designs.csv"
    with generated.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(_ROW))
        w.writeheader()
        w.writerow(_ROW)
    return generated


def test_nothing_to_publish_is_not_an_error(tmp_path):
    """The normal state on a first run, before any design has folded."""
    assert _publish_csv(tmp_path / "refold_designs.csv", tmp_path / "out.csv", tmp_path) is False
    assert not (tmp_path / "out.csv").exists()


def test_existing_rows_are_published(tmp_path):
    out_dir = tmp_path / "work"
    generated = _write_generated(out_dir)
    target = tmp_path / "results" / "boltz2.csv"

    assert _publish_csv(generated, target, out_dir) is True
    rows = list(csv.DictReader(target.open()))
    assert len(rows) == 1, "the completed fold did not reach the caller's CSV"


def test_published_paths_are_absolute_and_resolve(tmp_path):
    """Relative paths in the inner CSV are meaningless to a downstream tool with a
    different CWD, so publishing must absolutise them -- and they must point at files
    that exist, which is what makes the recovered CSV usable rather than merely present.
    """
    out_dir = tmp_path / "work"
    generated = _write_generated(out_dir)
    target = tmp_path / "boltz2.csv"
    _publish_csv(generated, target, out_dir)

    row = next(csv.DictReader(target.open()))
    for key in ("pdb", "pae_file", "plddt_file"):
        value = Path(row[key])
        assert value.is_absolute(), f"{key} was left relative: {row[key]}"
        assert value.is_file(), f"{key} does not resolve to a real file: {row[key]}"


def test_publishing_twice_is_idempotent(tmp_path):
    """It is called before AND after folding, so the second call must not corrupt the
    first (double-absolutised paths were the obvious way to get this wrong)."""
    out_dir = tmp_path / "work"
    generated = _write_generated(out_dir)
    target = tmp_path / "boltz2.csv"

    _publish_csv(generated, target, out_dir)
    first = target.read_text()
    _publish_csv(generated, target, out_dir)
    assert target.read_text() == first, "a second publish changed the output"


def test_a_fatal_fold_still_leaves_the_earlier_work_published(tmp_path, monkeypatch):
    """The behavioural test: prior folds must be in the caller's CSV even when the fold
    step dies. A raising refold_batch stands in for the SIGABRT, which cannot be
    simulated in-process -- the point under test is the ORDER of the two calls, and this
    fails if publishing happens only after folding.
    """
    import sys
    import types

    from binder_comparison.refolding import boltz2_runner

    out_dir = tmp_path / "work"
    _write_generated(out_dir)  # an earlier run's completed design
    target = tmp_path / "results" / "boltz2.csv"

    fake = types.ModuleType("refold_boltz2")

    def _explode(**kwargs):
        raise RuntimeError("stand-in for the XLA allocator CHECK")

    fake.refold_batch = _explode
    monkeypatch.setitem(sys.modules, "refold_boltz2", fake)

    with pytest.raises(RuntimeError, match="XLA allocator CHECK"):
        boltz2_runner.run_boltz2_refold(
            sequences=["CCCC"],
            target_sequence="MMMM",
            output_dir=out_dir,
            output_csv=target,
        )

    assert target.is_file(), (
        "the fold died and took the earlier completed design with it — "
        "_publish_csv must run BEFORE refold_batch, not only after"
    )
    assert len(list(csv.DictReader(target.open()))) == 1
