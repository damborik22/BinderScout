"""An engine's ipTM only reaches the ranking if five hand-typed names agree.

`rank_designs` gates on `consensus_iptm_n`: how many of `boltz_pae_iptm`,
`af3_pae_iptm` and `esmfold2_pae_iptm` are non-NaN for a design. A design needs
`--min-engines` of them (default 3) to clear the gate; the rest are ranked last.
Nothing derives those names from one another. Each is assembled by string
concatenation across modules that share no code:

    scripts/refold_<engine>.py       writes a CSV column               `pae_file`
    merger._load_engine              prefixes it with the engine       `esmfold2_pae_file`
    cli/report.py                    guards on that name, then calls   add_iptm_from_pae_files(prefix="esmfold2")
    scoring.add_iptm_from_pae_files  writes                            `esmfold2_pae_iptm`
    scoring._ENGINE_IPTM_COLS        lists what the consensus reads    `esmfold2_pae_iptm`

If any link disagrees with the next, that engine contributes nothing and nothing
raises. The report finishes, exits 0 and writes a full-looking metrics.csv in which
`consensus_iptm_n` tops out at 2. With the default gate no design clears it and the
only sign is a `[rank] WARNING` notice on stdout; with `--min-engines 2` — the very
remedy that notice prints — the ranking is a two-engine one and nothing says so. This
class of bug has shipped before: `top30_candidates.csv` read hard-coded
`af3_pae_ipsae_min` / `protenix_pae_ipsae_min` columns that nothing in the repo ever
wrote, and AF3's ipSAE vanished from the wet-lab shortlist (CHANGELOG, 2026-07-26,
"ranking integrity").

Nothing joined the links. The ranking tests in test_scoring.py build
`<engine>_pae_iptm` by hand as a DataFrame column, so those tests and
`_ENGINE_IPTM_COLS` are the same typo twice. The merger tests pin the `boltz` and `af3`
prefixes through `iptm`, never feed the merger an ESMFold2 CSV, and never look at
`pae_file`. And no test drives `binder-compare report`'s column-building step.

These do. They write one raw refold CSV per engine, headed exactly as that engine's
runner writes it, run the real `binder-compare report` (`main` is the console-script
entry point) on them, and check that every engine's own ipTM and ipSAE — recomputed
from the PAE matrix saved for that engine — are in metrics.csv, and that the consensus
the gate counts was built from them.

The matrices are flat blocks, different for every engine and every design, and the
model-reported `iptm` column is a sentinel no PAE-derived value equals. So the wrong
file read for an engine, the wrong layout, and the model-reported column read in place
of the recomputed one each change a number instead of passing unnoticed.
"""

from __future__ import annotations

import ast
import contextlib
import csv
import io
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from binder_comparison.comparison.merger import merge_refold_results
from binder_comparison.comparison.scoring import (
    _ENGINE_IPSAE_COLS,
    compute_ipsae_from_pae,
    compute_iptm_from_pae,
)
from binder_comparison.main import main

_SCRIPTS = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts"

# Engine key (the prefix merger.py puts on its columns) -> (runner script, PAE layout the
# runner saves). Boltz-2's array is natively [binder | target]; AF3 and ESMFold2 are given
# the target first, so theirs is [target | binder] (runner docstrings, notes in cli/report.py).
_ENGINES = {
    "boltz": ("refold_boltz2.py", "binder_target"),
    "af3": ("refold_af3.py", "target_binder"),
    "esmfold2": ("refold_esmfold2.py", "target_binder"),
}

# The columns merger.py and cli/report.py read from a runner's CSV.
_CONTRACT_COLUMNS = {"run_id", "sequence", "target_sequence", "binder_length", "iptm", "pae_file"}

_L_BINDER, _L_TARGET = 12, 20
_TARGET = "A" * _L_TARGET
_BINDERS = ["MKTAYIAKQRQI", "GSHMLEDPVDAF", "ACDEFGHIKLMN"]
# What every runner reports as `iptm`. No PAE-derived value below can equal it.
_MODEL_REPORTED_IPTM = 0.99


def _runner_csv_header(script: str) -> list[str]:
    """The CSV header a refold runner writes, read from its source.

    The runners import gemmi / equinox / mosaic, which exist only inside their own conda
    envs, so they cannot be imported here. AF3 and ESMFold2 return the list from
    `_csv_fieldnames()`; Boltz-2 binds a local `csv_columns`.
    """
    tree = ast.parse((_SCRIPTS / script).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_csv_fieldnames":
            (returned,) = (n for n in ast.walk(node) if isinstance(n, ast.Return))
            return ast.literal_eval(returned.value)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "csv_columns" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(
        f"{script}: found neither a `_csv_fieldnames()` returning a list literal nor a "
        "`csv_columns = [...]` assignment, so its CSV header cannot be read. Teach "
        "_runner_csv_header where the runner declares it now."
    )


def _pae_matrix(bt: float, tb: float, ordering: str) -> np.ndarray:
    """A flat-block PAE matrix, laid out the way an engine saves it.

    The intra-chain blocks are far more confident than the interface, so an interface
    block read from the wrong place (the wrong `ordering`) moves the ipTM.
    """
    bb = np.full((_L_BINDER, _L_BINDER), 0.3)
    tt = np.full((_L_TARGET, _L_TARGET), 0.4)
    binder_to_target = np.full((_L_BINDER, _L_TARGET), bt)
    target_to_binder = np.full((_L_TARGET, _L_BINDER), tb)
    if ordering == "binder_target":
        return np.block([[bb, binder_to_target], [target_to_binder, tt]])
    return np.block([[tt, target_to_binder], [binder_to_target, bb]])


@pytest.fixture(scope="module")
def engines(tmp_path_factory) -> SimpleNamespace:
    """One raw refold CSV per engine, plus the ipTM / ipSAE each design must end up with.

    The CSVs are written with `csv.DictWriter` against the runner's own header, as the
    runners write them, so a column the runner no longer declares cannot slip through.
    Expected values come from the scoring kernels run on the very matrix saved for that
    engine, so they depend on which file is read and how, not on any column name.
    """
    root = tmp_path_factory.mktemp("engine_column_contract")
    csvs: dict[str, Path] = {}
    iptm: dict[str, dict[str, float]] = {}
    ipsae: dict[str, dict[str, float]] = {}

    for e, (engine, (script, ordering)) in enumerate(_ENGINES.items()):
        header = _runner_csv_header(script)
        absent = sorted(_CONTRACT_COLUMNS - set(header))
        assert not absent, (
            f"{script} no longer writes {absent}, columns that merger.py and cli/report.py read. If the rename "
            "is deliberate, change those readers and this test together (TestRunnerHeaders covers `pae_file`)."
        )

        iptm[engine], ipsae[engine] = {}, {}
        rows = []
        for i, seq in enumerate(_BINDERS):
            interface_pae = 0.6 + 0.3 * i + 0.1 * e  # nine distinct values, 0.6 .. 1.4 A
            # Binder->target is the more confident direction, so the two directions differ.
            pae = _pae_matrix(bt=interface_pae, tb=interface_pae + 0.5, ordering=ordering)
            pae_path = root / f"{engine}_{i:04d}_pae.npy"
            np.save(pae_path, pae)
            iptm[engine][seq] = compute_iptm_from_pae(pae, _L_BINDER, ordering=ordering)["iptm"]
            ipsae[engine][seq] = compute_ipsae_from_pae(pae, _L_BINDER, ordering=ordering)["ipsae_min"]
            row = dict.fromkeys(header, "")
            row.update(
                run_id=f"{engine}_{i:04d}",
                sequence=seq,
                target_sequence=_TARGET,
                binder_length=_L_BINDER,
                iptm=_MODEL_REPORTED_IPTM,
                pae_file=str(pae_path),
            )
            rows.append(row)

        csvs[engine] = root / f"{engine}_results.csv"
        with csvs[engine].open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)

    # The test's own premise: every expected ipTM differs from every other and from the sentinel.
    expected = [v for per_engine in iptm.values() for v in per_engine.values()]
    assert len({round(v, 6) for v in expected}) == len(expected)
    assert _MODEL_REPORTED_IPTM not in expected

    fasta = root / "sequences.fasta"
    fasta.write_text("".join(f">mosaic_{i} source=mosaic length={len(s)}\n{s}\n" for i, s in enumerate(_BINDERS)))
    return SimpleNamespace(csvs=csvs, fasta=fasta, iptm=iptm, ipsae=ipsae)


@pytest.fixture(scope="module")
def report(engines, tmp_path_factory) -> SimpleNamespace:
    """`binder-compare report` on the three engines' CSVs, as evaluate.sh invokes it.

    Returns metrics.csv indexed by sequence, and everything the run printed or warned.
    """
    out = tmp_path_factory.mktemp("report_out")
    log = io.StringIO()
    with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(log):
        warnings.simplefilter("always")
        main(
            [
                "report",
                "--boltz2-results",
                str(engines.csvs["boltz"]),
                "--af3-results",
                str(engines.csvs["af3"]),
                "--esmfold2-results",
                str(engines.csvs["esmfold2"]),
                "--sequences",
                str(engines.fasta),
                "--output",
                str(out),
            ]
        )
    printed = log.getvalue() + "".join(f"\n[warning] {w.message}" for w in caught)
    return SimpleNamespace(metrics=pd.read_csv(out / "metrics.csv").set_index("sequence"), log=printed)


class TestRunnerHeaders:
    """The first link: what the refold runners write. They cannot be imported, so it is read from source."""

    @pytest.mark.parametrize("engine", _ENGINES)
    def test_every_refold_runner_still_writes_a_pae_file_column(self, engine: str) -> None:
        """merger.py prefixes this name and cli/report.py looks the prefixed name up."""
        script = _ENGINES[engine][0]
        assert "pae_file" in _runner_csv_header(script), (
            f"{script} no longer has a `pae_file` column. merger.py would not produce `{engine}_pae_file`, "
            f"`binder-compare report` would skip {engine}'s ipTM and ipSAE, and the engine would drop out of "
            "the consensus without an error."
        )


class TestMergedColumns:
    """The second link: the name merger.py gives each engine's PAE column."""

    @pytest.mark.parametrize("engine", _ENGINES)
    def test_the_merger_names_each_engines_pae_column_the_way_the_report_looks_it_up(
        self, engines: SimpleNamespace, engine: str
    ) -> None:
        merged = merge_refold_results(
            boltz2_csv=engines.csvs["boltz"], af3_csv=engines.csvs["af3"], esmfold2_csv=engines.csvs["esmfold2"]
        )
        assert f"{engine}_pae_file" in merged.columns, (
            f"merge_refold_results produced no `{engine}_pae_file` (PAE columns it did produce: "
            f"{sorted(c for c in merged.columns if c.endswith('pae_file'))}). cli/report.py only computes "
            "an engine's ipTM when that column exists."
        )


class TestThroughTheRealReport:
    """Every link at once: runner CSV -> merge -> the report's loaders -> consensus -> gate."""

    @pytest.mark.parametrize("engine", _ENGINES)
    def test_each_engines_own_iptm_reaches_metrics_csv(
        self, report: SimpleNamespace, engines: SimpleNamespace, engine: str
    ) -> None:
        col = f"{engine}_pae_iptm"
        assert col in report.metrics.columns, f"metrics.csv has no `{col}`.\n{report.log}"
        want = pd.Series(engines.iptm[engine])
        assert report.metrics.loc[want.index, col].tolist() == pytest.approx(want.tolist())

    @pytest.mark.parametrize("engine", _ENGINES)
    def test_each_engines_own_ipsae_reaches_metrics_csv(
        self, report: SimpleNamespace, engines: SimpleNamespace, engine: str
    ) -> None:
        col = _ENGINE_IPSAE_COLS[engine]
        assert col in report.metrics.columns, f"metrics.csv has no `{col}`.\n{report.log}"
        want = pd.Series(engines.ipsae[engine])
        assert report.metrics.loc[want.index, col].tolist() == pytest.approx(want.tolist())

    def test_every_design_is_backed_by_all_three_engines(self, report: SimpleNamespace) -> None:
        assert report.metrics["consensus_iptm_n"].tolist() == [3] * len(_BINDERS), report.log

    def test_every_design_clears_the_default_cross_engine_gate(self, report: SimpleNamespace) -> None:
        """Three engines and a default gate of three: a pool this complete must not be re-rated."""
        assert report.metrics["passes_engine_gate"].all(), report.log

    def test_the_consensus_mean_averages_the_recomputed_iptms_not_the_model_reported_ones(
        self, report: SimpleNamespace, engines: SimpleNamespace
    ) -> None:
        """A list naming `esmfold2_iptm` for `esmfold2_pae_iptm` still counts 3 engines and gates every design."""
        want = pd.DataFrame(engines.iptm).mean(axis=1)
        assert report.metrics.loc[want.index, "consensus_iptm_mean"].tolist() == pytest.approx(want.tolist())
