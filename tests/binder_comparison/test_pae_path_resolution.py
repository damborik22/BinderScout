"""A pool moved off the machine that produced it must still find its PAE files.

Refold CSVs record ABSOLUTE paths (`/home/<user>/eval_workdir/.../x_pae.npy`).
The moment a campaign is archived and copied anywhere else — which is the normal
workflow: refold on a fleet box, analyse elsewhere — those paths do not exist.

The existing fallback was `base_dir / recorded`, which is a no-op for an
absolute path: pathlib returns the absolute operand. So resolution returned None
while the file sat in `base_dir` under the same relative layout. That is not a
cosmetic failure — without PAE there is no `*_pae_iptm`, so no design clears the
cross-engine gate and the whole ranking degrades.
"""

from pathlib import Path

from binder_comparison.comparison.scoring import _resolve_pae_path

RECORDED = "/home/someoneelse/eval_workdir/bc2_CALCA/af3_out/af3_0001_pae.npy"


def _pool(tmp_path: Path) -> Path:
    d = tmp_path / "refold" / "af3_out"
    d.mkdir(parents=True)
    (d / "af3_0001_pae.npy").write_bytes(b"x")
    return tmp_path / "refold"


def test_absolute_path_from_another_machine_resolves_under_base_dir(tmp_path):
    base = _pool(tmp_path)
    got = _resolve_pae_path(RECORDED, base)
    assert got is not None, "a transplanted pool lost its PAE files"
    assert got == base / "af3_out" / "af3_0001_pae.npy"


def test_an_existing_path_still_wins(tmp_path):
    """Never override a path that is actually there."""
    real = tmp_path / "here_pae.npy"
    real.write_bytes(b"x")
    assert _resolve_pae_path(str(real), _pool(tmp_path)) == real


def test_longest_matching_tail_wins_over_a_bare_basename(tmp_path):
    """Engines reuse basenames. Matching only the basename could hand back
    another engine's matrix, which would be worse than returning nothing."""
    base = tmp_path / "refold"
    for eng in ("af3_out", "esmfold2_out"):
        (base / eng).mkdir(parents=True)
        (base / eng / "pred_pae.npy").write_bytes(eng.encode())
    got = _resolve_pae_path("/elsewhere/run/esmfold2_out/pred_pae.npy", base)
    assert got == base / "esmfold2_out" / "pred_pae.npy"
    assert got.read_bytes() == b"esmfold2_out"


def test_genuinely_missing_file_still_returns_none(tmp_path):
    assert _resolve_pae_path("/elsewhere/nope_pae.npy", _pool(tmp_path)) is None


def test_no_base_dir_is_tolerated(tmp_path):
    assert _resolve_pae_path(RECORDED, None) is None
