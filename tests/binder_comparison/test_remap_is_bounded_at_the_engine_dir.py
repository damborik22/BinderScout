"""A remapped path must not fall through to another run's file of the same name.

Export names are ``<binder_id>_<engine>.pdb`` with no per-run uuid, so two runs of one
design write identically named files. The tail-strip that finds a transplanted pool's
files used to run all the way down to a bare basename: a design whose own file was
missing from the moved pool was bound, silently, to a same-named file of a different run
that happened to sit in the results directory.

The strip is now bounded at the engine's own output directory, and a remap says so once
per column, with the prefix it dropped.
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from binder_comparison.comparison.scoring import (
    _resolve_pae_path,
    add_iptm_from_pae_files,
    remap_structure_paths,
)

GONE = "/srv/other_account/runs/pool1"


def _touch(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestTheStripStopsAtTheEngineDirectory:
    def test_a_missing_own_file_does_not_bind_to_another_runs_same_named_file(self, tmp_path):
        # This pool's d1 is here; its d2 failed to copy. A DIFFERENT run left a d2 of the
        # same name at the top of `structures/`.
        _touch(tmp_path / "refold_boltz2" / "structures" / "d1_boltz2.pdb", "this pool")
        _touch(tmp_path / "structures" / "d2_boltz2.pdb", "another run")

        own = _resolve_pae_path(f"{GONE}/refold_boltz2/structures/d1_boltz2.pdb", tmp_path)
        assert own == tmp_path / "refold_boltz2" / "structures" / "d1_boltz2.pdb"
        assert _resolve_pae_path(f"{GONE}/refold_boltz2/structures/d2_boltz2.pdb", tmp_path) is None

    def test_two_refold_directories_with_same_named_files_never_cross(self, tmp_path):
        _touch(tmp_path / "refold_boltz2" / "d1_pae.npy", "boltz2")
        _touch(tmp_path / "refold_esmfold2" / "d1_pae.npy", "esmfold2")

        got = _resolve_pae_path(f"{GONE}/refold_esmfold2/d1_pae.npy", tmp_path)
        assert got == tmp_path / "refold_esmfold2" / "d1_pae.npy"
        assert got.read_text() == "esmfold2"
        # AF3's directory did not travel: that is a miss, not the other engines' file.
        assert _resolve_pae_path(f"{GONE}/refold_af3/d1_pae.npy", tmp_path) is None

    def test_a_basename_alone_is_never_enough_even_without_an_engine_directory(self, tmp_path):
        _touch(tmp_path / "d1_pae.npy", "someone else's")
        assert _resolve_pae_path(f"{GONE}/af3_out/d1_pae.npy", tmp_path) is None

    def test_parent_directory_plus_file_still_remaps_a_custom_layout(self, tmp_path):
        _touch(tmp_path / "af3_out" / "d1_pae.npy", "mine")
        assert _resolve_pae_path(f"{GONE}/af3_out/d1_pae.npy", tmp_path) == tmp_path / "af3_out" / "d1_pae.npy"

    def test_a_deeper_prefix_above_the_engine_directory_is_still_shed(self, tmp_path):
        _touch(tmp_path / "pool1" / "refold_af3" / "af3_0001_model.cif", "mine")
        got = _resolve_pae_path(f"{GONE}/refold_af3/af3_0001_model.cif", tmp_path / "pool1")
        assert got == tmp_path / "pool1" / "refold_af3" / "af3_0001_model.cif"


def _frame(n=3, directory="refold_boltz2"):
    return pd.DataFrame({"boltz_pdb": [f"{GONE}/{directory}/d{i}_boltz2.pdb" for i in range(1, n + 1)]})


class TestARemapIsSaidOncePerColumn:
    def test_structure_column_reports_count_and_dropped_prefix(self, tmp_path):
        for i in (1, 2, 3):
            _touch(tmp_path / "refold_boltz2" / f"d{i}_boltz2.pdb", "x")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = remap_structure_paths(_frame(), {"boltz": tmp_path})
        remap = [w for w in caught if "REMAPPED" in str(w.message)]
        assert len(remap) == 1, [str(w.message) for w in caught]
        msg = str(remap[0].message)
        assert "3/3" in msg and "'boltz_pdb'" in msg and GONE in msg
        assert out["boltz_pdb"].iloc[0] == str(tmp_path / "refold_boltz2" / "d1_boltz2.pdb")

    def test_a_path_that_exists_as_written_is_not_called_a_remap(self, tmp_path):
        real = _touch(tmp_path / "refold_boltz2" / "d1_boltz2.pdb", "x")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            remap_structure_paths(pd.DataFrame({"boltz_pdb": [str(real)]}), {"boltz": tmp_path})
        assert not [w for w in caught if "REMAPPED" in str(w.message)]

    def test_only_the_cells_that_were_remapped_are_counted(self, tmp_path):
        real = _touch(tmp_path / "elsewhere" / "d9_boltz2.pdb", "x")
        _touch(tmp_path / "refold_boltz2" / "d1_boltz2.pdb", "x")
        df = pd.DataFrame(
            {"boltz_pdb": [str(real), f"{GONE}/refold_boltz2/d1_boltz2.pdb", f"{GONE}/refold_boltz2/nope.pdb"]}
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            remap_structure_paths(df, {"boltz": tmp_path})
        remap = [str(w.message) for w in caught if "REMAPPED" in str(w.message)]
        assert len(remap) == 1 and "1/3" in remap[0]

    def test_the_pae_loader_says_it_too(self, tmp_path):
        _touch(tmp_path / "refold_boltz2" / "d1_pae.npy", "x")
        np.save(tmp_path / "refold_boltz2" / "d1_pae.npy", np.full((30, 30), 3.0, dtype=np.float32))
        df = pd.DataFrame({"boltz_pae_file": [f"{GONE}/refold_boltz2/d1_pae.npy"], "binder_length": [10]})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            add_iptm_from_pae_files(
                df, pae_file_col="boltz_pae_file", prefix="boltz", ordering="binder_target", base_dir=tmp_path
            )
        remap = [str(w.message) for w in caught if "REMAPPED" in str(w.message)]
        assert len(remap) == 1 and "1/1" in remap[0] and "'boltz_pae_file'" in remap[0]
