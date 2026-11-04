"""A fully resumed Boltz-2 refold must say so and leave without touching the model.

`evaluate.sh` always passes `--resume`. On a finished run every design is already scored, and
the run still imported jax/equinox/mosaic, built `Boltz2()` and reserved its XLA pool (~19 GB on
a 24 GB card, for ~9 s) before finding an empty loop. That is not free on a shared card: it can
starve, or be starved by, a neighbouring engine.

The early exit uses the same key as the rest of resume (binder sequence + a non-empty `iptm`,
`binder_comparison.refolding.resume`) and is TARGET-AWARE the way `evaluate.sh`'s `pool_coverage`
is, because `--resume` keys on the sequence alone: a CSV left over from another target would
otherwise be "complete" and its scores reported for this one.

Three things are pinned, each with a control that proves the path under test was reached:

* the runner returns before it imports the script (so before jax is imported at all),
* the script's own `refold_batch` returns before the target MSA, the weights and `Boltz2()`,
* a design with no score, a different target, or no `--resume` is NOT treated as complete.

Heavy modules are made to RAISE rather than merely be absent, so a regression fails loudly
instead of quietly paying for a model load.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from binder_comparison.refolding import boltz2_runner
from binder_comparison.refolding.resume import ResumeTargetMismatch, pool_resume_state

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "Evaluator" / "scripts"
EVALUATE_SH = REPO / "Evaluator" / "evaluate.sh"

TARGET = "MKTAYIAKQRQISFVKSHFSRQ"
OTHER_TARGET = "GSHMLEDPVDAFKQRYTW"
POOL = ["AAAAKKKKLLLL", "CCCCDDDDEEEE", "GGGGHHHHIIII"]
HEAVY = ("jax", "jaxlib", "equinox", "mosaic", "boltz", "gemmi", "torch")


def _write_results(path: Path, rows: list[dict], *, with_target_col: bool = True) -> Path:
    cols = ["run_id", "idx", "sequence", *(["target_sequence"] if with_target_col else []), "iptm", "pdb"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i, r in enumerate(rows, 1):
            w.writerow({"run_id": "r1", "idx": i, "pdb": f"structures/{i}.pdb", **{k: r.get(k, "") for k in cols}})
    return path


def _scored(seqs, target=TARGET, iptm="0.81"):
    return [{"sequence": s, "target_sequence": target, "iptm": iptm} for s in seqs]


@pytest.fixture
def heavy_imports_raise(monkeypatch):
    """Importing any heavy module raises ImportError; the script module is not cached."""
    for name in HEAVY:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.delitem(sys.modules, "refold_boltz2", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))  # the runner prepends the scripts dir
    monkeypatch.setattr(os, "environ", os.environ.copy())  # the script's memory policy writes XLA_* variables


def _run(tmp_path: Path, seqs=POOL, *, target=TARGET, resume=True):
    out_dir = tmp_path / "refold"
    out_csv = tmp_path / "published" / "boltz2.csv"
    boltz2_runner.run_boltz2_refold(
        sequences=list(seqs),
        target_sequence=target,
        output_dir=out_dir,
        output_csv=out_csv,
        scripts_path=SCRIPTS,
        resume=resume,
    )
    return out_dir, out_csv


# ---------------------------------------------------------------------------------------------
# The runner: returns before the script (and therefore jax) is imported
# ---------------------------------------------------------------------------------------------


class TestRunnerEarlyExit:
    def test_a_fully_scored_pool_returns_without_importing_anything_heavy(self, tmp_path, heavy_imports_raise, capsys):
        _write_results(tmp_path / "refold" / "refold_designs.csv", _scored(POOL))
        _, out_csv = _run(tmp_path)  # would raise ImportError if it reached the script
        out = capsys.readouterr().out
        assert "already complete" in out
        assert "model not loaded" in out
        assert "refold_boltz2" not in sys.modules, "the script (and so jax) was imported"
        assert len(list(csv.DictReader(out_csv.open()))) == len(POOL), "the existing rows were not published"

    def test_control_the_heavy_import_really_is_poisoned_and_really_is_reached(self, tmp_path, heavy_imports_raise):
        """One design lacks a score, so the runner must go on to import the script: if the
        poison were not effective, or the runner never got that far, this would not raise."""
        rows = _scored(POOL[:2]) + [{"sequence": POOL[2], "target_sequence": TARGET, "iptm": ""}]
        _write_results(tmp_path / "refold" / "refold_designs.csv", rows)
        with pytest.raises(ImportError):
            _run(tmp_path)

    def test_a_design_with_a_blank_score_is_not_skipped_and_not_called_complete(self, tmp_path, heavy_imports_raise):
        rows = _scored(POOL[:2]) + [{"sequence": POOL[2], "target_sequence": TARGET, "iptm": "  "}]
        _write_results(tmp_path / "refold" / "refold_designs.csv", rows)
        assert pool_resume_state(tmp_path / "refold" / "refold_designs.csv", POOL, TARGET) == (False, 0)
        with pytest.raises(ImportError):
            _run(tmp_path)

    def test_a_design_with_no_row_at_all_goes_on_to_fold(self, tmp_path, heavy_imports_raise):
        _write_results(tmp_path / "refold" / "refold_designs.csv", _scored(POOL[:2]))
        with pytest.raises(ImportError):
            _run(tmp_path)

    def test_without_resume_a_complete_csv_is_not_a_reason_to_stop(self, tmp_path, heavy_imports_raise):
        _write_results(tmp_path / "refold" / "refold_designs.csv", _scored(POOL))
        with pytest.raises(ImportError):
            _run(tmp_path, resume=False)

    def test_a_csv_scored_against_another_target_is_refused_and_not_published(self, tmp_path, heavy_imports_raise):
        _write_results(tmp_path / "refold" / "refold_designs.csv", _scored(POOL, target=OTHER_TARGET))
        with pytest.raises(ResumeTargetMismatch, match="DIFFERENT target"):
            _run(tmp_path)
        assert not (tmp_path / "published" / "boltz2.csv").exists(), "the other target's scores were published"

    def test_one_foreign_design_among_matching_ones_still_refuses(self, tmp_path, heavy_imports_raise):
        rows = _scored(POOL[:2]) + _scored(POOL[2:], target=OTHER_TARGET)
        _write_results(tmp_path / "refold" / "refold_designs.csv", rows)
        with pytest.raises(ResumeTargetMismatch):
            _run(tmp_path)

    def test_a_design_scored_against_both_targets_counts_for_this_one(self, tmp_path, heavy_imports_raise):
        rows = _scored(POOL, target=OTHER_TARGET) + _scored(POOL)
        _write_results(tmp_path / "refold" / "refold_designs.csv", rows)
        _run(tmp_path)  # complete, not refused

    def test_a_csv_without_a_target_column_cannot_be_checked_and_counts(self, tmp_path, heavy_imports_raise):
        _write_results(tmp_path / "refold" / "refold_designs.csv", _scored(POOL), with_target_col=False)
        _run(tmp_path)

    def test_the_cli_turns_the_refusal_into_a_nonzero_exit(self, tmp_path, heavy_imports_raise, capsys):
        from binder_comparison.cli import refold_boltz2 as cli

        _write_results(tmp_path / "refold" / "refold_designs.csv", _scored(POOL, target=OTHER_TARGET))
        fasta = tmp_path / "pool.fasta"
        fasta.write_text("".join(f">d{i}\n{s}\n" for i, s in enumerate(POOL, 1)))
        args = argparse.Namespace(
            sequences=str(fasta),
            target_seq=TARGET,
            target_pdb=None,
            output=str(tmp_path / "published" / "boltz2.csv"),
            output_dir=str(tmp_path / "refold"),
            num_samples=6,
            recycling_steps=3,
            scripts_path=str(SCRIPTS),
            resume=True,
            save_pae_bins=False,
        )
        with pytest.raises(SystemExit) as exc:
            cli.run(args)
        assert exc.value.code == 1
        assert "DIFFERENT target" in capsys.readouterr().err

    def test_the_cli_exits_zero_and_says_complete_for_a_finished_pool(self, tmp_path, heavy_imports_raise, capsys):
        from binder_comparison.cli import refold_boltz2 as cli

        _write_results(tmp_path / "refold" / "refold_designs.csv", _scored(POOL))
        fasta = tmp_path / "pool.fasta"
        fasta.write_text("".join(f">d{i}\n{s}\n" for i, s in enumerate(POOL, 1)))
        args = argparse.Namespace(
            sequences=str(fasta),
            target_seq=TARGET,
            target_pdb=None,
            output=str(tmp_path / "published" / "boltz2.csv"),
            output_dir=str(tmp_path / "refold"),
            num_samples=6,
            recycling_steps=3,
            scripts_path=str(SCRIPTS),
            resume=True,
            save_pae_bins=False,
        )
        cli.run(args)  # returns normally: exit 0
        assert "already complete" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------
# The script: refold_batch returns before the MSA, the weights and Boltz2()
# ---------------------------------------------------------------------------------------------


class _Loaded(AssertionError):
    """Raised by every stand-in for a step that must not run on the early-exit path."""


@pytest.fixture
def script(monkeypatch):
    """The real refold_boltz2.py, imported against stand-ins that raise if the model is touched."""
    monkeypatch.setattr(os, "environ", os.environ.copy())

    def _mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m)
        return m

    def _forbidden(*_a, **_k):
        raise _Loaded("the model / GPU was touched")

    class Boltz2:
        def __init__(self, *a, **k):
            raise _Loaded("Boltz2() constructed")

    _mod("equinox", filter_jit=lambda f: f)
    _mod("gemmi")
    _mod("jax", devices=_forbidden)
    _mod("jax.numpy")
    _mod("mosaic")
    _mod("mosaic.losses")
    _mod("mosaic.losses.structure_prediction")
    _mod("mosaic.common", TOKENS="ACDEFGHIKLMNPQRSTVWY")
    _mod("mosaic.models")
    _mod("mosaic.models.boltz2", Boltz2=Boltz2)
    _mod("mosaic.structure_prediction", TargetChain=object)

    spec = importlib.util.spec_from_file_location("refold_boltz2_under_test", SCRIPTS / "refold_boltz2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Every step between the top of refold_batch and the first fold. Reaching one is the failure.
    monkeypatch.setattr(module, "prepare_target_msa", _forbidden)
    monkeypatch.setattr(module, "_check_boltz_cache", _forbidden)
    return module


class TestScriptEarlyExit:
    def test_everything_skipped_returns_before_the_msa_and_the_model(self, script, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        script.refold_batch(POOL, TARGET, output_dir=str(tmp_path / "s"), skip_indices={1, 2, 3})
        assert "already complete" in capsys.readouterr().out
        assert not (tmp_path / "s").exists(), "work directories were created for a pool with nothing to do"

    def test_control_one_design_left_reaches_the_first_forbidden_step(self, script, tmp_path, monkeypatch):
        """Proves the stand-ins are wired in and that the guard, not luck, is what stopped the run above."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(_Loaded):
            script.refold_batch(POOL, TARGET, output_dir=str(tmp_path / "s"), skip_indices={1, 2})

    def test_no_skip_set_means_everything_is_still_to_do(self, script, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(_Loaded):
            script.refold_batch(POOL, TARGET, output_dir=str(tmp_path / "s"))


# ---------------------------------------------------------------------------------------------
# One definition of "complete": python and evaluate.sh's pool_coverage must agree
# ---------------------------------------------------------------------------------------------


def _bash_fn(name: str) -> str:
    lines = EVALUATE_SH.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"^{re.escape(name)} \(\) \{{", line))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _awk_covered(tmp_path: Path, csv_path: Path, pool: list[str], target: str) -> int:
    fa = tmp_path / "pool.fasta"
    fa.write_text("".join(f">b{i}\n{s}\n" for i, s in enumerate(pool, 1)))
    program = f'{_bash_fn("pool_coverage")}\npool_coverage "{csv_path}" "{fa}" "{target}"'
    done = subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return int(done.stdout.strip())


@pytest.mark.parametrize(
    "rows, with_target_col",
    [
        (_scored(POOL), True),
        (_scored(POOL[:2]), True),
        (_scored(POOL, iptm=""), True),
        (_scored(POOL[:1]) + _scored(POOL[1:], iptm=""), True),
        (_scored(POOL, target=OTHER_TARGET), True),
        (_scored(POOL[:2]) + _scored(POOL[2:], target=OTHER_TARGET), True),
        (_scored(POOL, target=OTHER_TARGET) + _scored(POOL), True),
        (_scored(POOL, target=" " + TARGET.lower() + " "), True),
        (_scored(POOL), False),
    ],
    ids=[
        "complete",
        "design-missing",
        "all-blank",
        "one-blank",
        "other-target",
        "one-other-target",
        "both-targets",
        "case-and-space",
        "no-target-column",
    ],
)
def test_python_and_pool_coverage_agree_on_what_complete_means(tmp_path, rows, with_target_col):
    results = _write_results(tmp_path / "e.csv", rows, with_target_col=with_target_col)
    complete, _ = pool_resume_state(results, POOL, TARGET)
    assert complete == (_awk_covered(tmp_path, results, POOL, TARGET) == len(POOL))
