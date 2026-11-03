"""A pool folded on one account and reported on another keeps its old absolute paths.

The refold runners write ABSOLUTE paths into the refold CSVs (``pdb``, ``cif``,
``pae_file``). When the results directory is copied to another machine or account
those paths point at a tree that does not exist here. PAE paths were already
checked and warned about; the structure paths were not resolved at all, so the
report quietly lost the 3D viewer, ``top20_structures/`` and ``view_top20.pml`` --
exit 0, every metric present, nothing said.
"""

import math
import warnings
from pathlib import Path

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.cli.report import (  # noqa: E402
    _STRUCTURE_PATH_COLUMNS,
    remap_structure_paths,
)
from binder_comparison.comparison.scoring import (  # noqa: E402
    _resolve_pae_path,
    add_iptm_from_pae_files,
)

# A path that cannot exist on the machine running the tests: the "other account".
FOREIGN = "/srv/other_account/runs/pool1"


def _results_dir(tmp_path: Path) -> Path:
    """<tmp>/results with a refold output dir sitting next to where the CSV would be."""
    root = tmp_path / "results"
    (root / "refold_boltz2").mkdir(parents=True)
    (root / "refold_boltz2" / "d1_boltz2.pdb").write_text("ATOM\n")
    return root


class TestResolverRemapsAbsolutePaths:
    def test_foreign_absolute_path_is_found_under_base_dir(self, tmp_path):
        root = _results_dir(tmp_path)
        got = _resolve_pae_path(f"{FOREIGN}/refold_boltz2/d1_boltz2.pdb", root)
        assert got == root / "refold_boltz2" / "d1_boltz2.pdb"

    def test_a_path_that_exists_as_written_is_returned_untouched(self, tmp_path):
        real = tmp_path / "x.npy"
        real.write_bytes(b"")
        assert _resolve_pae_path(str(real), tmp_path / "elsewhere") == real

    def test_nothing_to_remap_onto_is_none(self, tmp_path):
        assert _resolve_pae_path(f"{FOREIGN}/nope.pdb", tmp_path) is None
        assert _resolve_pae_path(f"{FOREIGN}/nope.pdb", None) is None

    def test_pae_loader_follows_the_same_remap(self, tmp_path):
        """PAE shared the old 'relative to base_dir' rule, which cannot remap an absolute path."""
        root = tmp_path / "results"
        (root / "refold_boltz2").mkdir(parents=True)
        np.save(root / "refold_boltz2" / "d1_pae.npy", np.full((30, 30), 3.0, dtype=np.float32))
        df = pd.DataFrame({"boltz_pae_file": [f"{FOREIGN}/refold_boltz2/d1_pae.npy"], "binder_length": [10]})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            out = add_iptm_from_pae_files(
                df, pae_file_col="boltz_pae_file", prefix="boltz", ordering="binder_target", base_dir=root
            )
        assert not math.isnan(out["boltz_pae_iptm"].iloc[0])


class TestRemapStructurePaths:
    def _df(self, **cols):
        return pd.DataFrame({"binder_id": ["d1", "d2"], **cols})

    def test_foreign_paths_are_rewritten_to_where_the_files_are_now(self, tmp_path):
        root = _results_dir(tmp_path)
        df = self._df(boltz_pdb=[f"{FOREIGN}/refold_boltz2/d1_boltz2.pdb", None])
        out = remap_structure_paths(df, {"boltz": root})
        assert Path(out["boltz_pdb"].iloc[0]) == root / "refold_boltz2" / "d1_boltz2.pdb"
        assert Path(out["boltz_pdb"].iloc[0]).exists()

    def test_input_frame_is_not_mutated(self, tmp_path):
        root = _results_dir(tmp_path)
        original = f"{FOREIGN}/refold_boltz2/d1_boltz2.pdb"
        df = self._df(boltz_pdb=[original, None])
        remap_structure_paths(df, {"boltz": root})
        assert df["boltz_pdb"].iloc[0] == original

    def test_unresolved_paths_warn_once_per_column_with_the_count(self, tmp_path):
        root = _results_dir(tmp_path)
        df = self._df(boltz_pdb=[f"{FOREIGN}/gone_a.pdb", f"{FOREIGN}/gone_b.pdb"])
        with pytest.warns(UserWarning) as rec:
            remap_structure_paths(df, {"boltz": root})
        msgs = [str(w.message) for w in rec if "[structure]" in str(w.message)]
        assert len(msgs) == 1
        assert "2/2" in msgs[0]
        assert "'boltz_pdb'" in msgs[0]
        assert str(root) in msgs[0]
        assert "top20_structures" in msgs[0]

    def test_unresolved_cell_is_left_as_it_was(self, tmp_path):
        df = self._df(boltz_pdb=[f"{FOREIGN}/gone_a.pdb", None])
        with pytest.warns(UserWarning):
            out = remap_structure_paths(df, {"boltz": tmp_path})
        assert out["boltz_pdb"].iloc[0] == f"{FOREIGN}/gone_a.pdb"

    def test_blank_cells_are_not_counted_as_lost_files(self, tmp_path):
        """A blank cell means that engine never folded the design -- not a lost file."""
        df = self._df(af3_cif=[None, float("nan")])
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            remap_structure_paths(df, {"af3": tmp_path})

    def test_each_engine_uses_its_own_csv_directory(self, tmp_path):
        boltz_root = _results_dir(tmp_path)
        af3_root = tmp_path / "af3_results"
        (af3_root / "refold_af3").mkdir(parents=True)
        (af3_root / "refold_af3" / "d1_af3.cif").write_text("data_x\n")
        df = self._df(
            boltz_pdb=[f"{FOREIGN}/refold_boltz2/d1_boltz2.pdb", None],
            af3_cif=[f"{FOREIGN}/refold_af3/d1_af3.cif", None],
        )
        out = remap_structure_paths(df, {"boltz": boltz_root, "af3": af3_root})
        assert Path(out["af3_cif"].iloc[0]) == af3_root / "refold_af3" / "d1_af3.cif"
        assert Path(out["boltz_pdb"].iloc[0]) == boltz_root / "refold_boltz2" / "d1_boltz2.pdb"

    def test_every_column_the_viewers_read_is_covered(self):
        """The viewer / top20 / epitope code prefers these columns by name."""
        needed = {"boltz_pdb", "af3_pdb", "af3_cif", "esmfold2_pdb", "esmfold2_cif", "pdb"}
        assert needed <= set(_STRUCTURE_PATH_COLUMNS)

    def test_columns_absent_from_the_frame_are_ignored(self, tmp_path):
        out = remap_structure_paths(self._df(sequence=["A", "B"]), {"boltz": tmp_path})
        assert list(out.columns) == ["binder_id", "sequence"]


class TestReportOnATransplantedPool:
    """The call site, not just the helper: `report.run` is what loses the viewer."""

    def _pool(self, tmp_path: Path, *, keep_structures: bool = True) -> Path:
        root = tmp_path / "results"
        (root / "refold_boltz2").mkdir(parents=True)
        rows = []
        for i, binder in enumerate(["MKVLAAGIVG", "MKVLAAGIVA", "MKVLAAGIVL"]):
            np.save(root / "refold_boltz2" / f"d{i}_pae.npy", np.full((30, 30), 2.0 + i, dtype=np.float32))
            if keep_structures:
                (root / "refold_boltz2" / f"d{i}_boltz2.pdb").write_text(
                    "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n"
                )
            rows.append(
                {
                    "sequence": binder,
                    "target_sequence": "ACDEFGHIKLMNPQRSTVWY",
                    "binder_length": 10,
                    "iptm": 0.8 - 0.1 * i,
                    "plddt_binder_mean": 0.8,
                    "pdb": f"{FOREIGN}/refold_boltz2/d{i}_boltz2.pdb",
                    "pae_file": f"{FOREIGN}/refold_boltz2/d{i}_pae.npy",
                }
            )
        pd.DataFrame(rows).to_csv(root / "boltz2_results.csv", index=False)
        fasta = "".join(f">d{i} source=mosaic\n{r['sequence']}\n" for i, r in enumerate(rows))
        (tmp_path / "seqs.fasta").write_text(fasta)
        return root

    def _run(self, tmp_path: Path, root: Path) -> Path:
        import argparse

        from binder_comparison.cli import report

        parser = argparse.ArgumentParser()
        report.add_parser(parser.add_subparsers())
        out = tmp_path / "out"
        args = parser.parse_args(
            [
                "report",
                "--boltz2-results",
                str(root / "boltz2_results.csv"),
                "--sequences",
                str(tmp_path / "seqs.fasta"),
                "-o",
                str(out),
                "--min-engines",
                "2",
            ]
        )
        report.run(args)
        return out

    def test_viewer_inputs_survive_the_move(self, tmp_path):
        out = self._run(tmp_path, self._pool(tmp_path))
        assert len(sorted((out / "top20_structures").glob("rank*.pdb"))) == 3
        assert (out / "top20_structures" / "view_top20.pml").exists()
        # the PAE-derived column proves the same remap reached the PAE loaders
        metrics = pd.read_csv(out / "metrics.csv")
        assert metrics["boltz_pae_iptm"].notna().all()

    def test_lost_structures_are_reported_not_silent(self, tmp_path):
        root = self._pool(tmp_path, keep_structures=False)
        with pytest.warns(UserWarning, match=r"\[structure\] 3/3 structure files listed in 'boltz_pdb'"):
            self._run(tmp_path, root)
