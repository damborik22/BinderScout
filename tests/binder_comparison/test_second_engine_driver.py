"""The shared second-engine driver, exercised through a trivial fake adapter.

This pins the generic contract ONCE for every candidate script: a failed design is a blank row and
the designs after it still run, partial failure exits 3 with the count, resume re-runs blank rows,
the PAE is saved binder-first whatever the engine's native order, a wrong-sized or non-finite PAE
(or a non-finite iptm) is refused with nothing saved, and the sidecars are written.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from binder_comparison.refolding.second_engine import REFOLD_CSV_FIELDS, write_refold_row
from binder_comparison.refolding.second_engine_driver import EngineError, run_cli

TARGET = "ACDEFGHIKL"  # 10
B1, B2, B3 = "MKVLAAGW", "GGSSPPTT", "WWYYFFLL"  # 8 each
NT, NB = len(TARGET), len(B1)
TT, TB, BT, BB = 2.0, 25.0, 5.0, 1.0


def block_pae(order: str, nt: int = NT, nb: int = NB) -> np.ndarray:
    """A matrix whose four blocks carry distinct constants, in the given native order."""
    n = nt + nb
    pae = np.empty((n, n), dtype=np.float32)
    if order == "target_binder":
        pae[:nt, :nt], pae[:nt, nt:], pae[nt:, :nt], pae[nt:, nt:] = TT, TB, BT, BB
    else:
        pae[:nb, :nb], pae[:nb, nb:], pae[nb:, :nb], pae[nb:, nb:] = BB, BT, TB, TT
    return pae


class FakeAdapter:
    name = "fakeeng"
    description = "fake"
    target_msa_filename = "target.a3m"

    def __init__(self, tmp_path: Path, order: str = "target_binder", behaviour=None):
        self.native_pae_order = order
        self.tmp_path = tmp_path
        self.behaviour = behaviour or (lambda seq: None)  # return None = fine; raise = fail; dict = override
        self.calls: list[str] = []
        self.configured = False

    def add_args(self, parser):
        parser.add_argument("--fake-flag", default="x")

    def configure(self, args):
        self.configured = args.fake_flag

    def engine_version(self):
        return "9.9"

    def weights_id(self):
        return "fake-weights"

    def predict_one(self, *, query_id, binder_seq, target_seq, target_msa_path, work_dir, num_seeds, num_samples):
        self.calls.append(binder_seq)
        override = self.behaviour(binder_seq) or {}
        cif = self.tmp_path / f"{query_id}.cif"
        cif.write_text("data_x\n")
        pred = {
            "pae": block_pae(self.native_pae_order, len(target_seq), len(binder_seq)),
            "summary": {"iptm": 0.7, "ptm": 0.8, "sample_ranking_score": 0.75},
            "cif": cif,
            "plddt_target": np.full(len(target_seq), 90.0),
            "plddt_binder": np.full(len(binder_seq), 80.0),
            "seed": 7,
        }
        pred.update(override)
        return pred


@pytest.fixture()
def fasta(tmp_path):
    p = tmp_path / "s.fasta"
    p.write_text(f">d1 a\n{B1}\n>d2 b\n{B2}\n>d3 c\n{B3}\n")
    return p


def go(adapter, fasta, tmp_path, *extra):
    out_csv = tmp_path / "o.csv"
    argv = [
        "--sequences",
        str(fasta),
        "--target-seq",
        TARGET,
        "--output",
        str(out_csv),
        "--output-dir",
        str(tmp_path / "out"),
        "--no-msa",
        *extra,
    ]
    return run_cli(adapter, argv), out_csv


def rows(path):
    with Path(path).open() as fh:
        return list(csv.DictReader(fh))


def test_failing_design_is_blank_and_the_next_one_still_scores(fasta, tmp_path, capsys):
    def behaviour(seq):
        if seq == B1:
            raise RuntimeError("boom")

    code, out_csv = go(FakeAdapter(tmp_path, behaviour=behaviour), fasta, tmp_path)
    r = rows(out_csv)
    assert code == 3
    assert [x["sequence"] for x in r] == [B1, B2, B3]
    assert r[0]["iptm"] == "" and r[0]["pae_file"] == "" and r[0]["binder_length"] == str(NB)
    assert r[1]["iptm"] != "" and r[2]["iptm"] != ""  # designs after the failure are scored
    err = capsys.readouterr().err
    assert "boom" in err and "1 of 3" in err
    assert list(r[0]) == list(REFOLD_CSV_FIELDS)


def test_every_design_failing_raises_instead_of_exiting_zero(fasta, tmp_path):
    def behaviour(seq):
        raise RuntimeError("no gpu")

    with pytest.raises(RuntimeError, match="All 3 binder"):
        go(FakeAdapter(tmp_path, behaviour=behaviour), fasta, tmp_path)
    assert all(x["iptm"] == "" for x in rows(tmp_path / "o.csv"))


def test_exit_3_summary_carries_the_tail_of_the_engine_stderr(fasta, tmp_path, capsys):
    noise = "\n".join(f"line {i}" for i in range(40))

    def behaviour(seq):
        if seq == B2:
            raise EngineError("engine exited with code 1", noise + "\nRuntimeError: CUDA out of memory\n")

    code, _ = go(FakeAdapter(tmp_path, behaviour=behaviour), fasta, tmp_path)
    err = capsys.readouterr().err
    assert code == 3
    summary = err.split("1 of 3")[1]  # the exit-3 summary, not only the per-design line
    assert "CUDA out of memory" in summary
    assert "line 39" in summary and "line 31" in summary  # the last ~10 lines
    assert "line 5" not in summary  # and not the whole stream


def test_resume_skips_a_scored_row_and_reruns_a_blank_one(fasta, tmp_path):
    out_csv = tmp_path / "o.csv"
    write_refold_row(out_csv, {"run_id": "fakeeng_0001", "idx": "1", "sequence": B1, "iptm": "0.7"})
    write_refold_row(out_csv, {"run_id": "fakeeng_0002", "idx": "2", "sequence": B2})  # blank: earlier failure
    ad = FakeAdapter(tmp_path)
    code, _ = go(ad, fasta, tmp_path, "--resume")
    assert code == 0
    assert ad.calls == [B2, B3]
    assert {x["sequence"] for x in rows(out_csv) if x["iptm"]} == {B1, B2, B3}


@pytest.mark.parametrize("order", ["target_binder", "binder_target"])
def test_pae_is_saved_binder_first_for_either_native_order(order, fasta, tmp_path):
    code, out_csv = go(FakeAdapter(tmp_path, order=order), fasta, tmp_path)
    assert code == 0
    r = rows(out_csv)[0]
    assert Path(r["pae_file"]).name == "d1_fakeeng_pae.npy"
    pae = np.load(r["pae_file"])
    assert np.all(pae[:NB, :NB] == BB) and np.all(pae[:NB, NB:] == BT)
    assert np.all(pae[NB:, :NB] == TB) and np.all(pae[NB:, NB:] == TT)
    assert (float(r["pae_bt_mean"]), float(r["pae_tb_mean"]), float(r["pae_bb_mean"])) == (BT, TB, BB)


def test_sidecars_and_engine_flags(fasta, tmp_path):
    ad = FakeAdapter(tmp_path)
    code, _ = go(ad, fasta, tmp_path, "--fake-flag", "y", "--num-samples", "4")
    assert code == 0 and ad.configured == "y"
    out = tmp_path / "out"
    assert json.loads((out / "target_msa_mode.json").read_text())["target_msa_mode"] == "single_sequence"
    info = json.loads((out / "refold_run_info.json").read_text())
    assert info == {
        "engine": "fakeeng",
        "engine_version": "9.9",
        "weights_id": "fake-weights",
        "n_samples": 4,
        "n_seeds": 1,
        "seeds": [7],
        "target_msa_mode": "single_sequence",
    }


class SettingsAdapter(FakeAdapter):
    """FakeAdapter plus the optional ``run_info_extra`` hook."""

    def __init__(self, tmp_path, extra):
        super().__init__(tmp_path)
        self._extra = extra

    def run_info_extra(self):
        return self._extra


def test_run_info_extra_hook_is_written_under_a_single_settings_key(fasta, tmp_path):
    extra = {"num_steps": 50, "early_stopping": "off", "engine": "not-a-collision", "nested": {"a": [1, 2]}}
    code, _ = go(SettingsAdapter(tmp_path, extra), fasta, tmp_path)
    assert code == 0
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["settings"] == extra
    # the engine's keys cannot overwrite the driver's own: they live one level down
    assert info["engine"] == "fakeeng" and info["seeds"] == [7] and info["n_samples"] == 5


def test_an_adapter_without_the_hook_gets_no_settings_key(fasta, tmp_path):
    go(FakeAdapter(tmp_path), fasta, tmp_path)
    assert "settings" not in json.loads((tmp_path / "out" / "refold_run_info.json").read_text())


@pytest.mark.parametrize("bad", [{"x": object()}, {"x": {1, 2}}, ["not", "a", "dict"]])
def test_a_settings_hook_that_cannot_be_serialised_fails_loudly_and_writes_no_sidecar(fasta, tmp_path, bad):
    ad = SettingsAdapter(tmp_path, bad)
    with pytest.raises(TypeError):
        go(ad, fasta, tmp_path)
    assert not (tmp_path / "out" / "refold_run_info.json").exists()
    assert ad.calls == []  # no design ran


def test_missing_target_msa_exits_2(fasta, tmp_path, monkeypatch):
    from binder_comparison.refolding import target_msa as tm

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(tm, "_query_colabfold", boom)
    out_csv = tmp_path / "o.csv"
    argv = ["--sequences", str(fasta), "--target-seq", TARGET, "--output", str(out_csv)]
    argv += ["--output-dir", str(tmp_path / "out"), "--msa-cache-dir", str(tmp_path / "cache")]
    ad = FakeAdapter(tmp_path)
    assert run_cli(ad, argv) == 2
    assert ad.calls == []


def test_target_msa_is_written_under_the_adapter_file_name(fasta, tmp_path, monkeypatch):
    from binder_comparison.refolding import target_msa as tm

    a3m = f">q\n{TARGET}\n>h\n{TARGET}\n"
    monkeypatch.setattr(tm, "_query_colabfold", lambda *a, **k: a3m)
    seen = {}
    ad = FakeAdapter(tmp_path)
    original = ad.predict_one

    def spy(**kw):
        seen["path"] = kw["target_msa_path"]
        seen["text"] = Path(kw["target_msa_path"]).read_text()
        return original(**kw)

    ad.predict_one = spy
    argv = ["--sequences", str(fasta), "--target-seq", TARGET, "--output", str(tmp_path / "o.csv")]
    argv += ["--output-dir", str(tmp_path / "out"), "--msa-cache-dir", str(tmp_path / "cache")]
    assert run_cli(ad, argv) == 0
    assert Path(seen["path"]).name == "target.a3m" and seen["text"] == a3m


def test_wrong_sized_pae_is_refused_and_nothing_is_saved(fasta, tmp_path):
    def behaviour(seq):
        if seq == B1:
            return {"pae": np.zeros((NT + NB + 1,) * 2, dtype=np.float32)}

    code, out_csv = go(FakeAdapter(tmp_path, behaviour=behaviour), fasta, tmp_path)
    r = rows(out_csv)
    assert code == 3 and r[0]["iptm"] == "" and r[0]["pae_file"] == ""
    assert not list((tmp_path / "out").glob("d1_*_pae.npy"))


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_pae_is_refused_and_nothing_is_saved(bad, fasta, tmp_path, capsys):
    def behaviour(seq):
        if seq == B1:
            pae = block_pae("target_binder")
            pae[1, 2] = bad
            return {"pae": pae}

    code, out_csv = go(FakeAdapter(tmp_path, behaviour=behaviour), fasta, tmp_path)
    r = rows(out_csv)
    assert code == 3 and r[0]["iptm"] == "" and r[0]["pae_max"] == ""
    assert "non-finite" in capsys.readouterr().err
    assert not list((tmp_path / "out").glob("d1_*_pae.npy"))
    assert r[1]["iptm"] != ""


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None])
def test_non_finite_or_missing_iptm_is_refused_and_nothing_is_saved(bad, fasta, tmp_path, capsys):
    def behaviour(seq):
        if seq == B1:
            return {"summary": {"iptm": bad, "ptm": 0.8, "sample_ranking_score": 0.75}}

    code, out_csv = go(FakeAdapter(tmp_path, behaviour=behaviour), fasta, tmp_path)
    r = rows(out_csv)
    assert code == 3 and r[0]["iptm"] == "" and r[0]["pae_file"] == ""
    assert "iptm" in capsys.readouterr().err
    assert not list((tmp_path / "out").glob("d1_*_pae.npy"))
