"""An engine that failed on EVERY design must raise, not leave a finished-looking run behind.

AF3 and ESMFold2 catch each per-binder failure, write a row that carries the binder
sequence and no metrics, and move on; Boltz-2 skips the design instead. Either way a
*total* failure looks like a completed batch. Each of these happened:

  * AF3, 2026-08-20: evaluate.sh exported `JAX_PLATFORMS=cpu` on aarch64, so
    run_alphafold.py could not see the GPU and 6 of 6 binders died.
  * ESMFold2, 2026-09-18: a 24 GB card ran out of memory at 900 tokens (the engine
    wants ~28.7 GB) and printed "Wrote 1 row(s)" with exit code 0.
  * Boltz-2, 2026-07-28: a Mosaic checkout without the msa_path patch skipped all 512
    designs of a shard, on two machines, and reported success.

Nothing downstream can tell. evaluate.sh asks only that the engine CSV gained rows and
that the pool's sequences appear in it, and a blank row still carries its sequence, so
it prints "ok -- 65/65 pool design(s)" over a column of blanks. Every design is then
silently down to two engines, fails the default 3-engine gate and is ranked last: a
hardware fault read as a quality judgement.

The RuntimeError at the end of each `refold_batch` is the only thing between that and
the report, and no test ran it. The three guards (`n_failed == len(jobs)` in AF3 and
ESMFold2, `n_skipped == n_todo` in Boltz-2) could be deleted, or turned into
`n_failed > len(jobs)`, with the suite staying green.

These tests run the real `refold_batch` of each standalone script. Only the model call
is replaced, so the per-design loop, the blank row, the failure count and the guard are
the shipped code. Every guard is pinned to fire when every design failed and when every
design of a RESUMED batch failed; AF3's and ESMFold2's are also pinned not to fire on
one bad design.

The scripts import gemmi / jax / mosaic at module scope and none of it is installed in
CI (which is why test_af3_env.py skips there), so those imports are replaced with mocks;
nothing here needs a GPU.
"""

from __future__ import annotations

import csv
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts"

# Imports the scripts make at module scope that CI cannot satisfy.
_STAND_INS = {
    "refold_af3": ["gemmi"],
    "refold_esmfold2": ["gemmi"],
    "refold_boltz2": [
        "equinox",
        "gemmi",
        "jax",
        "jax.numpy",
        "mosaic",
        "mosaic.common",
        "mosaic.losses",
        "mosaic.losses.structure_prediction",
        "mosaic.models",
        "mosaic.models.boltz2",
        "mosaic.structure_prediction",
        "boltz",
        "boltz.main",
    ],
}

TARGET = "MKTAYIAKQRQISFVKSHFSRQ"
# Equal lengths: ESMFold2 and Boltz-2 sort by length, and the order should not matter here.
POOL = ["ACDEFGHIKL", "MNPQRSTVWY", "GHIKLMNPQR", "STVWYACDEF"]


def _load(monkeypatch: pytest.MonkeyPatch, name: str):
    """Exec Evaluator/scripts/<name>.py with its GPU-only imports replaced by mocks."""
    for dep in _STAND_INS[name]:
        monkeypatch.setitem(sys.modules, dep, mock.MagicMock(name=dep))
    spec = importlib.util.spec_from_file_location(f"_all_failed_{name}", _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep everything the scripts do inside tmp_path.

    refold_boltz2 sets XLA_* env vars at import and writes refold_designs.csv to the
    CWD; refold_af3 makes a JAX compile cache under $HOME.
    """
    with mock.patch.dict(os.environ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AF3_JAX_CACHE_DIR", str(tmp_path / "jax_cache"))
        yield


# ---------------------------------------------------------------------------
# Engine drivers: `run(sequences, outcome, skip_indices=None)` calls the real
# refold_batch; `outcome(binder_seq)` stands in for the model on each design.
# ---------------------------------------------------------------------------


@pytest.fixture
def af3(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    script = _load(monkeypatch, "refold_af3")
    models = tmp_path / "af3_models"
    models.mkdir()

    def run(sequences, outcome, *, skip_indices=None):
        # The seam is _run_single, the subprocess that is AF3 itself. _extract_ca_plddt
        # and _cif_to_pdb read a real mmCIF with gemmi, so they are replaced as well.
        monkeypatch.setattr(script, "_run_single", lambda *, binder_seq, **_: outcome(binder_seq))
        monkeypatch.setattr(script, "_extract_ca_plddt", lambda cif_path, atom_plddts: atom_plddts)
        monkeypatch.setattr(script, "_cif_to_pdb", lambda cif_path, pdb_path: None)
        csv_path = tmp_path / "af3.csv"
        script.refold_batch(
            sequences,
            TARGET,
            tmp_path / "af3_out",
            csv_path,
            model_dir=str(models),
            skip_indices=skip_indices,
            use_msa=False,
        )
        return csv_path

    return run


@pytest.fixture
def esmfold2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    script = _load(monkeypatch, "refold_esmfold2")

    def run(sequences, outcome, *, skip_indices=None):
        # The seam is the fold call; loading the weights needs torch and a GPU.
        def load_model_and_builder(repo_id, *, target_msa=None):
            return object(), lambda *, binder_seq, **_: outcome(binder_seq)

        monkeypatch.setattr(script, "_load_model_and_builder", load_model_and_builder)
        monkeypatch.setattr(script, "_free_torch_cache", lambda: None)  # would import torch and touch CUDA
        csv_path = tmp_path / "esmfold2.csv"
        script.refold_batch(
            sequences, TARGET, tmp_path / "esmfold2_out", csv_path, skip_indices=skip_indices, use_msa=False
        )
        return csv_path

    return run


@pytest.fixture
def boltz2(monkeypatch: pytest.MonkeyPatch):
    # The script sizes JAX's memory pool at import by probing nvidia-smi and libcudart.
    monkeypatch.setattr("binder_comparison.refolding.memory_policy.apply_jax_memory_policy", lambda *a, **k: "0.5")
    script = _load(monkeypatch, "refold_boltz2")

    def run(sequences, outcome, *, skip_indices=None):
        # Boltz-2 skips a design when building its features raises. TargetChain is a
        # mock here, so keep what the script passed in: chains[0] is the binder.
        folder = mock.MagicMock(name="Boltz2()")
        folder.target_only_features.side_effect = lambda *, chains: outcome(chains[0].sequence)
        monkeypatch.setattr(script, "TargetChain", lambda **kw: SimpleNamespace(**kw))
        monkeypatch.setattr(script, "Boltz2", lambda: folder)
        monkeypatch.setattr(script, "prepare_target_msa", lambda *a, **k: ("", "none"))
        script.refold_batch(sequences, TARGET, "structures", skip_indices=skip_indices, use_msa=False)

    return run


# ---------------------------------------------------------------------------
# What the model call does. Each failure is one of the paths that counts a design as failed.
# ---------------------------------------------------------------------------


def _af3_crashes(binder_seq):
    raise RuntimeError("AF3 exited with code 1")


def _af3_leaves_no_output(binder_seq):
    return None


def _af3_folds(binder_seq):
    n = len(TARGET) + len(binder_seq)
    return {
        "summary": {"iptm": 0.82, "ptm": 0.71, "ranking_score": 0.77},
        "confidences": {"pae": np.full((n, n), 4.0), "atom_plddts": np.full(n, 90.0)},
        "cif": Path("model.cif"),
    }


class _UnreadableResult:
    @property
    def pae(self):
        raise RuntimeError("result tensor was already freed")


def _esmfold2_runs_out_of_memory(binder_seq):
    raise RuntimeError("CUDA out of memory")


def _esmfold2_returns_no_samples(binder_seq):
    return []


def _esmfold2_returns_an_unreadable_result(binder_seq):
    return _UnreadableResult()


def _esmfold2_returns_no_pae(binder_seq):
    return SimpleNamespace(pae=None, plddt=None, iptm=0.5, ptm=0.5, pair_chains_iptm=None, complex=None)


def _esmfold2_folds(binder_seq):
    n = len(TARGET) + len(binder_seq)
    return SimpleNamespace(
        pae=np.full((n, n), 4.0), plddt=np.full(n, 0.9), iptm=0.82, ptm=0.71, pair_chains_iptm=None, complex=None
    )


def _boltz2_cannot_build_features(binder_seq):
    raise IndexError("empty dataloader")


_FAILURES = [
    ("af3", "subprocess-crashes", _af3_crashes, _af3_folds),
    ("af3", "leaves-no-output", _af3_leaves_no_output, _af3_folds),
    ("esmfold2", "fold-raises", _esmfold2_runs_out_of_memory, _esmfold2_folds),
    ("esmfold2", "returns-no-samples", _esmfold2_returns_no_samples, _esmfold2_folds),
    ("esmfold2", "result-unreadable", _esmfold2_returns_an_unreadable_result, _esmfold2_folds),
    ("esmfold2", "returns-no-pae", _esmfold2_returns_no_pae, _esmfold2_folds),
    # No folded counterpart, so Boltz-2 is left out of the one-bad-design test: its
    # success path needs a whole prediction object, and an over-eager guard there fails
    # loudly (exit 1, no CSV copied into place) rather than silently.
    ("boltz2", "feature-build-fails", _boltz2_cannot_build_features, None),
]
ALL_FAIL = [pytest.param(engine, fails, id=f"{engine}-{label}") for engine, label, fails, _ in _FAILURES]
ONE_FAILS = [
    pytest.param(engine, fails, folds, id=f"{engine}-{label}") for engine, label, fails, folds in _FAILURES if folds
]


def _recording(outcome, attempted):
    def wrapper(binder_seq):
        attempted.append(binder_seq)
        return outcome(binder_seq)

    return wrapper


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("engine", "fails"), ALL_FAIL)
def test_a_batch_in_which_every_binder_fails_raises_instead_of_reporting_success(request, engine, fails):
    run = request.getfixturevalue(engine)
    attempted: list[str] = []

    with pytest.raises(RuntimeError, match=rf"All {len(POOL)} binder\(s\) failed"):
        run(POOL, _recording(fails, attempted))

    # Not vacuous: the error came from the guard after every design was tried.
    assert sorted(attempted) == sorted(POOL)


@pytest.mark.parametrize(("engine", "fails"), ALL_FAIL)
def test_a_resumed_batch_whose_remaining_binders_all_fail_still_raises(request, engine, fails):
    """The guard counts against the designs this invocation was asked to fold, not the pool.

    After a crash, `--resume` hands refold_batch only the designs without a result. If
    the engine is what is broken, every one of those fails, and comparing the count with
    the full pool (2 of 4) would call that a partial failure and exit 0.
    """
    run = request.getfixturevalue(engine)
    already_done = {1, 2}
    attempted: list[str] = []

    with pytest.raises(RuntimeError, match=rf"All {len(POOL) - len(already_done)} binder\(s\) failed"):
        run(POOL, _recording(fails, attempted), skip_indices=already_done)

    assert sorted(attempted) == sorted(POOL[2:])


@pytest.mark.parametrize(("engine", "fails", "folds"), ONE_FAILS)
def test_one_failed_binder_among_good_ones_is_tolerated(request, engine, fails, folds):
    """The other half of the guard: a single bad design must not abort the batch.

    Without this a guard that fires on ANY failure (`n_failed > 0`) would pass the tests
    above, and a single malformed binder would fail the whole engine run.
    """
    run = request.getfixturevalue(engine)
    unlucky = POOL[1]

    csv_path = run(POOL, lambda binder_seq: fails(binder_seq) if binder_seq == unlucky else folds(binder_seq))

    with open(csv_path, newline="") as fh:
        scored = {row["sequence"]: row["iptm"] for row in csv.DictReader(fh) if row["iptm"]}
    assert scored == {seq: "0.82" for seq in POOL if seq != unlucky}
