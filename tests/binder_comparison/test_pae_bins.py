"""``--save-pae-bins``: keep the predicted-error DISTRIBUTION, not only its mean.

The refold runners save the expected PAE. The engines compute their own ipTM from the
whole distribution, ``E[1/(1+(e/d0)^2)]``; the kernel is convex, so the kernel of the mean
is lower, and the gap cannot be recovered afterwards. The flag stores the bin probabilities
(default OFF: nothing changes unless asked) and ``compute_iptm_from_pae_bins`` turns them
into the expected-kernel ipTM. It is not used for ranking.

Everything here uses fakes. The engines need a GPU, so the runner scripts are exercised
through the same seams as test_refold_all_failed_guard.py. NO REAL ENGINE OUTPUT HAS BEEN
CHECKED: whether ESMFold2's forward hook and Boltz-2's second ``model_output`` pass behave
as the installed code reads is pending the demo campaign on a GPU.
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
from binder_comparison.cli import refold_af3 as cli_refold_af3
from binder_comparison.cli import refold_boltz2 as cli_refold_boltz2
from binder_comparison.cli import refold_esmfold2 as cli_refold_esmfold2
from binder_comparison.comparison.scoring import compute_iptm_from_pae, compute_iptm_from_pae_bins
from binder_comparison.refolding import pae_bins as pb

_SCRIPTS = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts"
N_BINS = 64
CENTRES = pb.uniform_bin_centres(N_BINS)


def _delta(values: np.ndarray) -> np.ndarray:
    """One-hot bin probabilities for a matrix whose entries are bin centres."""
    idx = np.abs(values[..., None] - CENTRES).argmin(axis=-1)
    return np.eye(N_BINS, dtype=np.float32)[idx]


# ---------------------------------------------------------------------------
# The kernel
# ---------------------------------------------------------------------------


class TestIptmFromBins:
    L_B, L_T = 12, 20

    def _pae_on_centres(self, seed=0):
        rng = np.random.default_rng(seed)
        n = self.L_B + self.L_T
        return CENTRES[rng.integers(0, N_BINS, size=(n, n))].astype(float)

    @pytest.mark.parametrize("ordering", ["binder_target", "target_binder"])
    def test_a_delta_distribution_reproduces_the_point_pae_kernel_exactly(self, ordering):
        pae = self._pae_on_centres()
        point = compute_iptm_from_pae(pae, self.L_B, ordering=ordering)
        binned = compute_iptm_from_pae_bins(_delta(pae), CENTRES, self.L_B, ordering=ordering)
        for key in ("bt_iptm", "tb_iptm", "iptm"):
            assert binned[key] == pytest.approx(point[key], abs=1e-12)

    def test_a_spread_distribution_scores_above_the_kernel_of_its_mean(self):
        """The reason the bins are worth keeping: the kernel is convex in the error."""
        n = self.L_B + self.L_T
        probs = np.zeros((n, n, N_BINS))
        lo, hi = 2, N_BINS - 2  # half the mass at a small error, half at a large one
        probs[..., lo] = 0.5
        probs[..., hi] = 0.5
        mean_pae = np.full((n, n), 0.5 * (CENTRES[lo] + CENTRES[hi]))
        from_mean = compute_iptm_from_pae(mean_pae, self.L_B)["iptm"]
        from_bins = compute_iptm_from_pae_bins(probs, CENTRES, self.L_B)["iptm"]
        assert from_bins > from_mean + 0.05

    def test_float16_storage_does_not_move_the_score(self):
        rng = np.random.default_rng(1)
        n = self.L_B + self.L_T
        probs = pb.softmax(rng.normal(scale=3.0, size=(n, n, N_BINS)))
        exact = compute_iptm_from_pae_bins(probs, CENTRES, self.L_B)["iptm"]
        stored = compute_iptm_from_pae_bins(probs.astype(np.float16), CENTRES, self.L_B)["iptm"]
        assert stored == pytest.approx(exact, abs=2e-3)

    def test_binder_or_target_of_length_zero_is_nan(self):
        probs = _delta(np.full((5, 5), CENTRES[3]))
        assert np.isnan(compute_iptm_from_pae_bins(probs, CENTRES, 0)["iptm"])
        assert np.isnan(compute_iptm_from_pae_bins(probs, CENTRES, 5)["iptm"])

    def test_a_pair_with_no_probability_mass_gives_nan_not_a_silent_zero(self):
        n = self.L_B + self.L_T
        probs = np.zeros((n, n, N_BINS))
        assert np.isnan(compute_iptm_from_pae_bins(probs, CENTRES, self.L_B)["iptm"])

    def test_shape_mismatches_are_refused(self):
        with pytest.raises(ValueError, match="bin_probs"):
            compute_iptm_from_pae_bins(np.zeros((4, 5, N_BINS)), CENTRES, 2)
        with pytest.raises(ValueError, match="bin_centres"):
            compute_iptm_from_pae_bins(np.zeros((4, 4, N_BINS)), CENTRES[:10], 2)


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


class TestPaeBinsFile:
    def test_uniform_centres_are_the_convention_both_engines_use(self):
        assert np.allclose(pb.uniform_bin_centres(64), np.arange(0.25, 32.0, 0.5))

    def test_bins_sit_next_to_the_pae_file(self, tmp_path):
        assert pb.bins_path_for(tmp_path / "d1_pae.npy") == tmp_path / "d1_pae_bins.npz"

    def test_round_trip_is_float16_probs_and_float32_centres(self, tmp_path):
        pae = np.full((6, 6), CENTRES[10])
        path = pb.save_pae_bins(tmp_path / "x_pae_bins.npz", _delta(pae), CENTRES, expected_pae=pae)
        with np.load(path) as z:
            assert z["probs"].dtype == np.float16
            assert z["bin_centres"].dtype == np.float32
        probs, centres = pb.load_pae_bins(path)
        assert probs.shape == (6, 6, N_BINS)
        assert np.allclose(centres, CENTRES)
        assert np.allclose(pb.expected_pae_from_bins(probs, centres), pae)

    def test_a_distribution_that_does_not_reproduce_the_pae_is_refused(self, tmp_path):
        pae = np.full((6, 6), CENTRES[10])
        wrong = np.full((6, 6), CENTRES[40])
        with pytest.raises(pb.PaeBinsMismatch, match="differs from the saved PAE"):
            pb.save_pae_bins(tmp_path / "x.npz", _delta(wrong), CENTRES, expected_pae=pae)
        assert not (tmp_path / "x.npz").exists()

    def test_a_transposed_token_order_is_caught(self, tmp_path):
        rng = np.random.default_rng(2)
        pae = CENTRES[rng.integers(0, N_BINS, size=(8, 8))]
        with pytest.raises(pb.PaeBinsMismatch):
            pb.save_pae_bins(tmp_path / "x.npz", _delta(pae.T), CENTRES, expected_pae=pae)

    def test_bad_shapes_are_refused(self, tmp_path):
        with pytest.raises(ValueError, match="probs must be"):
            pb.save_pae_bins(tmp_path / "x.npz", np.zeros((4, 4)), CENTRES)
        with pytest.raises(ValueError, match="probs must be"):
            pb.save_pae_bins(tmp_path / "x.npz", np.zeros((4, 5, N_BINS)), CENTRES)

    def test_a_csv_without_the_column_cannot_take_bins_rows(self, tmp_path):
        old = tmp_path / "old.csv"
        old.write_text("run_id,pae_file\nr1,a.npy\n")
        with pytest.raises(ValueError, match="pae_bins_file"):
            pb.assert_csv_can_take_pae_bins(old)

    def test_missing_empty_and_matching_csvs_are_fine(self, tmp_path):
        pb.assert_csv_can_take_pae_bins(tmp_path / "absent.csv")
        empty = tmp_path / "empty.csv"
        empty.write_text("")
        pb.assert_csv_can_take_pae_bins(empty)
        ok = tmp_path / "ok.csv"
        ok.write_text("run_id,pae_file,pae_bins_file\n")
        pb.assert_csv_can_take_pae_bins(ok)


# ---------------------------------------------------------------------------
# The runner scripts, with fakes
# ---------------------------------------------------------------------------

TARGET = "MKTAYIAKQRQISFVKSHFSRQ"
POOL = ["ACDEFGHIKL", "MNPQRSTVWY"]


class _Tensor:
    """Just enough torch.Tensor for the ESMFold2 script and its hook."""

    def __init__(self, a):
        self.a = np.asarray(a)

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.a


def _load(monkeypatch, name, stand_ins):
    for dep in stand_ins:
        monkeypatch.setitem(sys.modules, dep, mock.MagicMock(name=dep))
    spec = importlib.util.spec_from_file_location(f"_pae_bins_{name}", _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    with mock.patch.dict(os.environ):
        monkeypatch.chdir(tmp_path)
        yield


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


class _FakeEsmfold2:
    """A model whose forward() output is seen by hooks, and a fold() that triggers it."""

    def __init__(self, *, logits_agree_with_pae=True):
        self.hooks = []
        self.logits_agree_with_pae = logits_agree_with_pae

    def register_forward_hook(self, fn):
        self.hooks.append(fn)

    def fold(self, *, binder_seq, num_diffusion_samples=1, **_):
        n = len(TARGET) + len(binder_seq)
        rng = np.random.default_rng(len(binder_seq))
        results, logit_stack = [], []
        for s in range(num_diffusion_samples):
            bins = rng.integers(0, N_BINS, size=(n, n))
            pae = CENTRES[bins]
            shown = pae if self.logits_agree_with_pae else CENTRES[(bins + 20) % N_BINS]
            logit_stack.append(60.0 * _delta(shown))
            results.append(
                SimpleNamespace(
                    pae=_Tensor(pae),
                    plddt=_Tensor(np.full(n, 0.9)),
                    iptm=0.5 + 0.1 * s,  # the LAST sample is the best one
                    ptm=0.6,
                    pair_chains_iptm=None,
                    complex=SimpleNamespace(to_mmcif=lambda: "data_x\n"),
                )
            )
        out = {"pae_logits": _Tensor(np.stack(logit_stack)), "pae": None}
        for hook in self.hooks:
            hook(self, (), out)
        return results[0] if num_diffusion_samples == 1 else results


@pytest.fixture
def esm(monkeypatch, tmp_path):
    script = _load(monkeypatch, "refold_esmfold2", ["gemmi"])
    monkeypatch.setattr(script, "_free_torch_cache", lambda: None)

    def run(*, save_pae_bins, samples=1, agree=True, csv_path=None, pool=POOL):
        model = _FakeEsmfold2(logits_agree_with_pae=agree)
        monkeypatch.setattr(
            script, "_load_model_and_builder", lambda repo_id, *, target_msa=None: (model, model_fold(model))
        )
        csv_path = csv_path or tmp_path / "esm.csv"
        script.refold_batch(
            pool,
            TARGET,
            tmp_path / "esm_out",
            csv_path,
            use_msa=False,
            num_diffusion_samples=samples,
            save_pae_bins=save_pae_bins,
        )
        return model, csv_path

    def model_fold(model):
        return lambda *, model, target_seq, binder_seq, num_diffusion_samples, **_: model.fold(
            binder_seq=binder_seq, num_diffusion_samples=num_diffusion_samples
        )

    return run


class TestEsmfold2Script:
    def test_off_by_default_nothing_is_hooked_written_or_added(self, esm, tmp_path):
        model, csv_path = esm(save_pae_bins=False)
        assert model.hooks == []
        assert "pae_bins_file" not in _rows(csv_path)[0]
        assert not list((tmp_path / "esm_out").glob("*_bins.npz"))

    def test_on_writes_a_file_per_design_that_reproduces_the_saved_pae(self, esm, tmp_path):
        _, csv_path = esm(save_pae_bins=True)
        rows = _rows(csv_path)
        assert len(rows) == len(POOL)
        for row in rows:
            probs, centres = pb.load_pae_bins(row["pae_bins_file"])
            assert Path(row["pae_bins_file"]).parent == Path(row["pae_file"]).parent
            assert np.allclose(pb.expected_pae_from_bins(probs, centres), np.load(row["pae_file"]), atol=1e-3)

    def test_the_kept_diffusion_sample_is_the_one_whose_bins_are_stored(self, esm):
        _, csv_path = esm(save_pae_bins=True, samples=3)
        for row in _rows(csv_path):
            assert row["pae_bins_file"], "bins for the kept sample were refused as not matching its PAE"

    def test_bins_that_disagree_with_the_pae_are_not_trusted_and_the_run_fails_loudly(self, esm):
        with pytest.raises(RuntimeError, match="no PAE-bin file was written"):
            esm(save_pae_bins=True, agree=False)

    def test_appending_to_a_csv_that_lacks_the_column_is_refused_before_any_work(self, esm, tmp_path):
        old = tmp_path / "old.csv"
        old.write_text("run_id,idx,sequence,pae_file\nr,1,AAA,a.npy\n")
        with pytest.raises(ValueError, match="pae_bins_file"):
            esm(save_pae_bins=True, csv_path=old)


class _FakeBoltz2:
    """Mosaic's Boltz2 as the script uses it, plus the model_output() the flag relies on."""

    def __init__(self, *, logits_agree_with_pae=True):
        self.agree = logits_agree_with_pae
        self.model_output_calls = 0

    def target_only_features(self, *, chains):
        self.binder_len = len(chains[0].sequence)
        return {}, object()

    def build_multisample_loss(self, **_):
        return lambda pssm, key: (0.0, [{"iptm": 0.8}])

    def _pae(self):
        n = self.binder_len + len(TARGET)
        rng = np.random.default_rng(self.binder_len)
        return CENTRES[rng.integers(0, N_BINS, size=(n, n))]

    def predict(self, **_):
        pae = self._pae()
        return SimpleNamespace(
            pae=pae,
            plddt=np.full(pae.shape[0], 0.9),
            iptm=0.8,
            st=SimpleNamespace(make_pdb_string=lambda: "ATOM\n"),
        )

    def model_output(self, **_):
        self.model_output_calls += 1
        shown = self._pae() if self.agree else np.roll(self._pae(), 7, axis=0)
        return SimpleNamespace(pae_logits=60.0 * _delta(shown), pae_bins=CENTRES)


def _boltz_script(monkeypatch):
    """refold_boltz2.py loaded against stand-ins for jax / mosaic / boltz."""
    monkeypatch.setattr("binder_comparison.refolding.memory_policy.apply_jax_memory_policy", lambda *a, **k: "0.5")
    stand_ins = [
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
    ]
    for dep in stand_ins:
        monkeypatch.setitem(sys.modules, dep, mock.MagicMock(name=dep))
    sys.modules["equinox"].filter_jit = lambda f: f
    sys.modules["mosaic.common"].TOKENS = "ACDEFGHIKLMNPQRSTVWY"
    return _load(monkeypatch, "refold_boltz2", [])


@pytest.fixture
def boltz(monkeypatch):
    script = _boltz_script(monkeypatch)

    def run(*, save_pae_bins, agree=True):
        folder = _FakeBoltz2(logits_agree_with_pae=agree)
        monkeypatch.setattr(script, "TargetChain", lambda **kw: SimpleNamespace(**kw))
        monkeypatch.setattr(script, "Boltz2", lambda: folder)
        monkeypatch.setattr(script, "prepare_target_msa", lambda *a, **k: ("", "none"))
        script.refold_batch(POOL, TARGET, "structures", use_msa=False, save_pae_bins=save_pae_bins)
        return folder, _rows(Path("refold_designs.csv"))

    return run


class TestBoltz2Script:
    def test_off_by_default_no_extra_pass_no_file_no_column(self, boltz):
        folder, rows = boltz(save_pae_bins=False)
        assert folder.model_output_calls == 0
        assert "pae_bins_file" not in rows[0]
        assert not list(Path("structures").glob("*_bins.npz"))

    def test_on_writes_a_file_per_design_that_reproduces_the_saved_pae(self, boltz):
        folder, rows = boltz(save_pae_bins=True)
        assert folder.model_output_calls == len(POOL)
        assert len(rows) == len(POOL)
        for row in rows:
            probs, centres = pb.load_pae_bins(row["pae_bins_file"])
            assert np.allclose(pb.expected_pae_from_bins(probs, centres), np.load(row["pae_file"]), atol=1e-3)

    def test_bins_that_disagree_with_the_pae_are_not_trusted_and_the_run_fails_loudly(self, boltz):
        with pytest.raises(RuntimeError, match="no PAE-bin file was written"):
            boltz(save_pae_bins=True, agree=False)

    def test_appending_to_a_csv_that_lacks_the_column_is_refused_before_any_work(self, boltz):
        # The twin of the ESMFold2 test. The guard must be handed the SAME path the rows are
        # appended to: the helper is silent for a path that does not exist, so a drifted
        # copy of the name would pass every other test here.
        Path("refold_designs.csv").write_text("run_id,idx,sequence,pae_file\nr,1,AAA,a.npy\n")
        with pytest.raises(ValueError, match="pae_bins_file"):
            boltz(save_pae_bins=True)
        assert not list(Path("structures").glob("*_bins.npz"))

    def test_the_runner_publishes_the_folded_rows_before_failing_on_zero_bins(self, monkeypatch, tmp_path):
        """The end-of-run zero-bins guard must not strand finished folds in the inner CSV.

        Through ``run_boltz2_refold`` (not ``refold_batch``): the runner copies the inner CSV to
        the caller's path only after the script returns, so a guard exception it does not hold
        and re-raise leaves the caller's CSV missing and ``--resume`` re-folding the whole pool.
        """
        from binder_comparison.refolding.boltz2_runner import run_boltz2_refold

        script = _boltz_script(monkeypatch)
        folder = _FakeBoltz2(logits_agree_with_pae=False)
        monkeypatch.setattr(script, "TargetChain", lambda **kw: SimpleNamespace(**kw))
        monkeypatch.setattr(script, "Boltz2", lambda: folder)
        monkeypatch.setattr(script, "prepare_target_msa", lambda *a, **k: ("", "none"))
        monkeypatch.setitem(sys.modules, "refold_boltz2", script)  # the runner imports it by bare name

        out_csv = tmp_path / "results" / "boltz2.csv"
        with pytest.raises(RuntimeError, match="no PAE-bin file was written"):
            run_boltz2_refold(
                sequences=POOL,
                target_sequence=TARGET,
                output_dir=tmp_path / "work",
                output_csv=out_csv,
                scripts_path=_SCRIPTS,
                save_pae_bins=True,
            )
        assert out_csv.exists(), "the folded designs never reached the caller's CSV"
        assert len(_rows(out_csv)) == len(POOL)

        # ...and --resume therefore keeps them instead of re-folding the pool.
        from binder_comparison.refolding.resume import resume_plan

        skip, _ = resume_plan(tmp_path / "work" / "refold_designs.csv", list(POOL))
        assert len(skip) == len(POOL)


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


def _parse(module, extra):
    import argparse

    parser = argparse.ArgumentParser()
    module.add_parser(parser.add_subparsers())
    return parser.parse_args([module.__name__.rsplit(".", 1)[-1].replace("_", "-"), *extra])


_REQUIRED = ["--sequences", "s.fasta", "--target-seq", "AAAA", "--output", "o.csv"]


@pytest.mark.parametrize("module", [cli_refold_boltz2, cli_refold_esmfold2])
def test_the_flag_exists_and_defaults_off(module):
    assert _parse(module, _REQUIRED).save_pae_bins is False
    assert _parse(module, [*_REQUIRED, "--save-pae-bins"]).save_pae_bins is True


def test_af3_has_no_such_flag_because_it_could_not_honour_it(capsys):
    """AF3 never surfaces its bin probabilities (see the commit message): a flag that quietly
    did nothing would be worse than none."""
    with pytest.raises(SystemExit):
        _parse(cli_refold_af3, [*_REQUIRED, "--save-pae-bins"])
    assert "--save-pae-bins" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("runner", "fn", "script"),
    [
        ("binder_comparison.refolding.esmfold2_runner", "run_esmfold2_refold", "refold_esmfold2"),
        ("binder_comparison.refolding.boltz2_runner", "run_boltz2_refold", "refold_boltz2"),
    ],
)
def test_the_runner_hands_the_flag_to_the_script(tmp_path, monkeypatch, runner, fn, script):
    """Call site, not just the function: a runner that forgot to pass it would write no bins."""
    seen = {}
    monkeypatch.delitem(sys.modules, script, raising=False)  # the runner imports it by bare name
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / f"{script}.py").write_text(
        "def refold_batch(**kw):\n"
        "    import csv, pathlib\n"
        "    SEEN.update(kw)\n"
        "    for name in ('refold_designs.csv', 'out.csv'):\n"
        "        pathlib.Path(name).write_text('run_id,pae_file\\n')\n"
    )
    import builtins

    monkeypatch.setattr(builtins, "SEEN", seen, raising=False)
    module = importlib.import_module(runner)
    out_csv = tmp_path / "out.csv"
    out_csv.write_text("run_id,pae_file\n")
    getattr(module, fn)(
        sequences=["AAAA"],
        target_sequence="CCCC",
        output_dir=tmp_path / "o",
        output_csv=out_csv,
        scripts_path=scripts,
        save_pae_bins=True,
    )
    assert seen["save_pae_bins"] is True
    seen.clear()
    getattr(module, fn)(
        sequences=["AAAA"],
        target_sequence="CCCC",
        output_dir=tmp_path / "o",
        output_csv=out_csv,
        scripts_path=scripts,
    )
    assert seen["save_pae_bins"] is False
