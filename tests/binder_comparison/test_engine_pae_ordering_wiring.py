"""Each refold engine's PAE file must be read in the layout that engine wrote it.

Boltz-2 writes PAE as [binder | target]; AF3 and ESMFold2 are given the target first, so
theirs is [target | binder]. The kernels take an `ordering=` argument and
test_scoring_kernels.py pins them exhaustively, but every one of those tests supplies
`ordering=` itself: they prove the kernel honours the argument and say nothing about which
argument each engine is handed. That is decided by a string literal per engine (five in
cli/report.py, one in cli/prefilter.py, and a `binder_target` hard-coded inside
`add_boltz_ipsae_from_files`), and the two generic loaders default in opposite directions
(`add_ipsae_from_pae_files` to target_binder, `add_iptm_from_pae_files` to binder_target).
The `ordering=` that is redundant on three of the five report calls is load-bearing on the
other two, so stripping them all "for consistency" flips AF3's and ESMFold2's ipTM.

Flip any one and nothing fails: no exception, no NaN, every number stays in [0, 1]. The
loader slices the wrong rows, which lets the confident INTRA-chain blocks leak into the
"interface", so a poorly bound design scores like a good one. `{engine}_pae_iptm` is the
only input to `consensus_iptm_mean` (the ranking key) and `{engine}_ipsae_min` sets each
engine's pass flag and `agreement_count`, so the shortlist reorders and the report reads
as an ordinary cross-engine disagreement.

A forward pin, not a fix: the wiring is correct today, and what established that was a
read-through (docs/INVESTIGATION_RANKING_DISCREPANCY.md, 2.7) that nothing re-runs.
report.py's `run()` has had per-engine wiring wrong before: its hard-coded shortlist
columns `af3_pae_ipsae_min` / `protenix_pae_ipsae_min` were never written by anything, so
AF3's ipSAE silently vanished from the wet-lab shortlist.

So these tests run the real `binder-compare report` and `prefilter` on refold CSVs whose
PAE files are laid out the way each engine lays them out, and compare every PAE-derived
column with the answer for the correctly oriented prediction. Only the HTML renderer, which
runs after metrics.csv is written, is stubbed. Each engine gets its own prediction, so a
column fed from the wrong engine's file fails too.
"""

from __future__ import annotations

import functools
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from binder_comparison.cli import report as report_cli
from binder_comparison.comparison.scoring import _ENGINE_IPSAE_COLS, compute_ipsae_from_pae, compute_iptm_from_pae
from binder_comparison.main import main

_BINDERS = (
    "MKTAYIAKQRQISFVKSHFSRQLEERLGLI",
    "GSDEVQLVESGGGLVQPGGSLRLSCAASGF",
    "WYTRNMDQPAEKSLHCIVFGTYRNQEDLHK",
)
_TARGET = "ACDEFGHIKLMNPQRSTVWY" * 3
L_B, L_T = len(_BINDERS[0]), len(_TARGET)
N = L_B + L_T

# The layout each refolder writes its PAE .npy in (refolding/af3_runner.py, esmfold2_runner.py).
_WRITES = {"boltz": "binder_target", "af3": "target_binder", "esmfold2": "target_binder"}
_THE_OTHER_WAY_ROUND = {"binder_target": "target_binder", "target_binder": "binder_target"}

# Where each engine's numbers land in metrics.csv: ipSAE binder->target, ipSAE target->binder,
# ipSAE min, ipTM. Only Boltz-2's ipSAE columns carry the extra "pae_" infix.
_COLUMNS = {
    "boltz": ["boltz_pae_bt_ipsae", "boltz_pae_tb_ipsae", "boltz_pae_ipsae_min", "boltz_pae_iptm"],
    "af3": ["af3_bt_ipsae", "af3_tb_ipsae", "af3_ipsae_min", "af3_pae_iptm"],
    "esmfold2": ["esmfold2_bt_ipsae", "esmfold2_tb_ipsae", "esmfold2_ipsae_min", "esmfold2_pae_iptm"],
}


def _physical_pae(engine: str, design: int) -> np.ndarray:
    """One engine's PAE for one design, in [binder | target] order.

    A poorly bound complex: confident inside each chain (0.5-3 A), unsure between them
    (binder->target 2-14 A, target->binder 3-22 A). That is what makes a mis-oriented read
    expensive, because the quadrants it picks up by mistake are the confident ones.
    """
    rng = np.random.default_rng(100 * (list(_COLUMNS).index(engine) + 1) + design)
    pae = np.empty((N, N))
    pae[:L_B, :L_B] = rng.uniform(0.5, 3.0, (L_B, L_B))
    pae[L_B:, L_B:] = rng.uniform(0.5, 3.0, (L_T, L_T))
    pae[:L_B, L_B:] = rng.uniform(2.0, 14.0, (L_B, L_T))
    pae[L_B:, :L_B] = rng.uniform(3.0, 22.0, (L_T, L_B))
    np.fill_diagonal(pae, 0.0)
    return pae


def _on_disk(engine: str, pae: np.ndarray) -> np.ndarray:
    """`pae` ([binder | target]) as `engine` writes it: untouched for Boltz-2, chains swapped for AF3 and ESMFold2.

    Done by re-indexing rather than with the evaluator's own `np.block`, so a slip in the
    kernel's re-blocking cannot cancel against the same slip here.
    """
    if _WRITES[engine] == "binder_target":
        return pae
    order = [*range(L_B, N), *range(L_B)]
    return pae[np.ix_(order, order)]


def _scores(engine: str, matrices: list[np.ndarray], ordering: str) -> pd.DataFrame:
    """The four metrics of `_COLUMNS[engine]` for each design, reading its matrix with `ordering`."""
    rows = {}
    for sequence, matrix in zip(_BINDERS, matrices):
        ipsae = compute_ipsae_from_pae(matrix, L_B, ordering=ordering)
        iptm = compute_iptm_from_pae(matrix, L_B, ordering=ordering)
        rows[sequence] = [ipsae["bt_ipsae"], ipsae["tb_ipsae"], ipsae["ipsae_min"], iptm["iptm"]]
    return pd.DataFrame.from_dict(rows, orient="index", columns=_COLUMNS[engine]).rename_axis("sequence")


@functools.cache
def _expected(engine: str) -> pd.DataFrame:
    """What `engine`'s columns must hold: the prediction in [binder | target] order, nothing transposed anywhere."""
    matrices = [_physical_pae(engine, design) for design in range(len(_BINDERS))]
    return _scores(engine, matrices, "binder_target")


@functools.cache
def _misread(engine: str) -> pd.DataFrame:
    """What the columns would hold if `engine`'s file were read in the other layout."""
    matrices = [_on_disk(engine, _physical_pae(engine, design)) for design in range(len(_BINDERS))]
    return _scores(engine, matrices, _THE_OTHER_WAY_ROUND[_WRITES[engine]])


@pytest.fixture(scope="module")
def refold_csvs(tmp_path_factory) -> dict[str, Path]:
    """One raw refold CSV per engine, each row naming a PAE .npy written in that engine's layout."""
    root = tmp_path_factory.mktemp("refold_outputs")
    csvs = {}
    for engine in _COLUMNS:
        rows = []
        for design, sequence in enumerate(_BINDERS):
            npy = root / f"{engine}_design{design}_pae.npy"
            np.save(npy, _on_disk(engine, _physical_pae(engine, design)))
            rows.append(
                {
                    "run_id": f"design{design}",
                    "idx": design,
                    "sequence": sequence,
                    "target_sequence": _TARGET,
                    "binder_length": L_B,
                    "iptm": 0.5,
                    "plddt_binder_mean": 0.8,
                    "pae_file": str(npy),
                }
            )
        csvs[engine] = root / f"{engine}_results.csv"
        pd.DataFrame(rows).to_csv(csvs[engine], index=False)
    return csvs


@pytest.fixture(scope="module")
def report_metrics(refold_csvs, tmp_path_factory) -> pd.DataFrame:
    """metrics.csv from a real `binder-compare report` over all three engines, indexed by sequence."""
    root = tmp_path_factory.mktemp("report")
    fasta = root / "sequences.fasta"
    fasta.write_text("".join(f">design{k} source=mosaic\n{seq}\n" for k, seq in enumerate(_BINDERS)))
    with pytest.MonkeyPatch.context() as patch:
        # The HTML renderer runs after metrics.csv is written; a rendering change must not
        # masquerade as an ordering regression.
        patch.setattr(report_cli, "generate_report", lambda **_: None)
        main(
            [
                "report",
                "--boltz2-results",
                str(refold_csvs["boltz"]),
                "--af3-results",
                str(refold_csvs["af3"]),
                "--esmfold2-results",
                str(refold_csvs["esmfold2"]),
                "--sequences",
                str(fasta),
                "--output",
                str(root / "out"),
            ]
        )
    return pd.read_csv(root / "out" / "metrics.csv").set_index("sequence")


class TestTheFixtureIsNotVacuous:
    """Guards the guard: the tests below would pass for nothing if a misread scored like a correct read, or if
    the pipeline scored an engine this file never feeds."""

    @pytest.mark.parametrize("engine", list(_COLUMNS))
    def test_misreading_the_file_moves_every_metric_by_a_wide_margin(self, engine):
        margin = (_misread(engine) - _expected(engine)).abs()
        assert (margin > 0.1).all(axis=None), f"a misread barely moves {engine}'s metrics:\n{margin}"

    def test_the_engines_wired_here_are_the_engines_the_pipeline_scores(self):
        """A fourth engine added to the report would otherwise get an `ordering=` that nothing checks."""
        assert {engine: columns[2] for engine, columns in _COLUMNS.items()} == _ENGINE_IPSAE_COLS


class TestReportReadsEachEnginesPaeInTheLayoutItWasWritten:
    @pytest.mark.parametrize("engine", list(_COLUMNS))
    def test_every_pae_derived_metric_matches_the_correctly_oriented_prediction(self, report_metrics, engine):
        got = report_metrics.loc[list(_BINDERS), _COLUMNS[engine]]
        pd.testing.assert_frame_equal(got, _expected(engine), check_exact=False, rtol=1e-9)

    def test_the_ranking_key_is_the_mean_of_the_correctly_oriented_iptms(self, report_metrics):
        want = sum(_expected(engine)[_COLUMNS[engine][3]] for engine in _COLUMNS) / len(_COLUMNS)
        got = report_metrics.loc[list(_BINDERS), "consensus_iptm_mean"]
        pd.testing.assert_series_equal(got, want, check_names=False, check_exact=False, rtol=1e-9)


class TestPrefilterReadsBoltz2PaeBinderFirst:
    """`prefilter` picks which designs from tools with no native interface metric (chiefly RFD3) go on to the
    expensive cross-engine refold, so a misread here sends the wrong ones."""

    def test_the_fold_back_scores_match_the_correctly_oriented_prediction(self, refold_csvs, tmp_path):
        out = tmp_path / "selection.csv"
        main(["prefilter", "--boltz2-results", str(refold_csvs["boltz"]), "--metric", "iptm", "--output", str(out)])
        columns = ["boltz_pae_ipsae_min", "boltz_pae_iptm"]
        got = pd.read_csv(out).set_index("sequence").loc[list(_BINDERS), columns]
        # prefilter rounds what it writes to 4 places
        pd.testing.assert_frame_equal(got, _expected("boltz")[columns], check_exact=False, rtol=0, atol=1e-4)
