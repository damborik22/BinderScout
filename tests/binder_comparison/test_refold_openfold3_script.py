"""refold_openfold3.py with the model call stubbed behind ``_predict_one``.

OpenFold3 itself cannot run where these tests do. What they pin is everything around the model
call that can silently corrupt a score: which chain comes first in the query (that fixes the
PAE order), that the saved PAE is re-blocked to ``[binder|target]``, that a wrong-sized PAE is
refused rather than scored, that a failed design is a blank row plus a non-zero exit, and that
``--resume`` re-runs blank rows.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from binder_comparison.refolding import target_msa as target_msa_mod
from binder_comparison.refolding.second_engine import REFOLD_CSV_FIELDS, write_refold_row

_SCRIPT = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts" / "refold_openfold3.py"
TARGET = "ACDEFGHIKL"  # 10 residues
BINDER_A = "MKVLAAGW"  # 8 residues
BINDER_B = "GGSSPPTT"  # 8 residues
NT, NB = len(TARGET), len(BINDER_A)

# One distinct constant per block of the native, TARGET-FIRST matrix.
TT, TB, BT, BB = 2.0, 25.0, 5.0, 1.0


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("_refold_openfold3_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native_pae(nt: int = NT, nb: int = NB) -> np.ndarray:
    """OpenFold3's native order: chains in query order, target (A) first, binder (B) second."""
    pae = np.empty((nt + nb, nt + nb), dtype=np.float32)
    pae[:nt, :nt] = TT
    pae[:nt, nt:] = TB  # rows target, cols binder
    pae[nt:, :nt] = BT  # rows binder, cols target
    pae[nt:, nt:] = BB
    return pae


def fake_prediction(tmp_path: Path, query_id: str, *, pae=None, nt: int = NT, nb: int = NB) -> dict:
    cif = tmp_path / f"{query_id}_model.cif"
    cif.write_text("data_stub\n")
    return {
        "pae": native_pae(nt, nb) if pae is None else pae,
        "summary": {"iptm": 0.71, "ptm": 0.8, "sample_ranking_score": 0.75},
        "cif": cif,
        "plddt_target": np.full(nt, 90.0),
        "plddt_binder": np.full(nb, 80.0),
        "seed": 42,
    }


@pytest.fixture()
def fasta(tmp_path):
    path = tmp_path / "seqs.fasta"
    path.write_text(f">d1 source=x\n{BINDER_A}\n>d2 source=y\n{BINDER_B}\n")
    return path


def run_main(mod, fasta, tmp_path, *extra):
    out_csv = tmp_path / "of3.csv"
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
    return mod.main(argv), out_csv


def read_rows(path: Path) -> list[dict]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


def test_saved_pae_is_reblocked_to_binder_first(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    code, out_csv = run_main(mod, fasta, tmp_path)
    assert code == 0
    rows = read_rows(out_csv)
    assert [r["sequence"] for r in rows] == [BINDER_A, BINDER_B]

    pae = np.load(rows[0]["pae_file"])
    assert Path(rows[0]["pae_file"]).name == "d1_openfold3_pae.npy"
    assert pae.shape == (NB + NT, NB + NT)
    # [binder | target]: BB, BT / TB, TT -- blocks moved whole, none transposed.
    assert np.all(pae[:NB, :NB] == BB)
    assert np.all(pae[:NB, NB:] == BT)
    assert np.all(pae[NB:, :NB] == TB)
    assert np.all(pae[NB:, NB:] == TT)
    # The CSV summaries are computed from that same re-blocked matrix.
    assert float(rows[0]["pae_bt_mean"]) == BT
    assert float(rows[0]["pae_tb_mean"]) == TB
    assert float(rows[0]["pae_bb_mean"]) == BB
    assert float(rows[0]["iptm"]) == pytest.approx(0.71)
    assert float(rows[0]["ranking_score"]) == pytest.approx(0.75)
    assert float(rows[0]["plddt_binder_mean"]) == pytest.approx(0.8)  # 0-100 rescaled to 0-1
    assert float(rows[0]["plddt_target_mean"]) == pytest.approx(0.9)


def test_csv_header_is_the_af3_header(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    _, out_csv = run_main(mod, fasta, tmp_path)
    assert next(csv.reader(out_csv.open())) == list(REFOLD_CSV_FIELDS)


def test_query_lists_target_first_so_the_pae_order_is_target_binder(mod, tmp_path):
    msa_dir = tmp_path / "msa"
    query = mod.build_query(BINDER_A, TARGET, msa_dir=msa_dir, target_msa_path=None)
    chains = query["chains"]
    assert [(c["chain_ids"], c["sequence"]) for c in chains] == [("A", TARGET), ("B", BINDER_A)]
    assert mod.NATIVE_PAE_ORDER == "target_binder"
    assert query["use_msas"] is False  # no target MSA given: single-sequence mode
    assert all("main_msa_file_paths" not in c for c in chains)


def test_query_with_msa_points_each_chain_at_a_colabfold_main_file(mod, tmp_path):
    target_a3m = tmp_path / "shared" / "colabfold_main.a3m"
    target_a3m.parent.mkdir()
    target_a3m.write_text(f">query\n{TARGET}\n>hit\n{TARGET}\n")
    query = mod.build_query(BINDER_A, TARGET, msa_dir=tmp_path / "msa", target_msa_path=target_a3m)
    assert query["use_msas"] is True
    target_chain, binder_chain = query["chains"]
    # OpenFold3 picks alignments by file name; colabfold_main is in its default aln_order.
    assert target_chain["main_msa_file_paths"] == str(target_a3m)
    with pytest.raises(ValueError, match="colabfold_main"):
        mod.build_query(BINDER_A, TARGET, msa_dir=tmp_path / "m2", target_msa_path=tmp_path / "other.a3m")
    binder_file = Path(binder_chain["main_msa_file_paths"])
    assert binder_file.name == "colabfold_main.a3m"
    assert binder_file.read_text() == f">query\n{BINDER_A}\n"  # one sequence: no MSA for a de novo binder


def test_wrong_sized_pae_is_refused_blank_row_and_counted(mod, fasta, tmp_path, monkeypatch, capsys):
    def predict(**kw):
        if kw["binder_seq"] == BINDER_B:
            return fake_prediction(tmp_path, kw["query_id"], pae=np.zeros((NT + NB + 1,) * 2))
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    code, out_csv = run_main(mod, fasta, tmp_path)
    rows = read_rows(out_csv)
    assert code == 3
    assert "1 of 2" in capsys.readouterr().err
    assert rows[0]["iptm"] != ""
    bad = rows[1]
    assert bad["sequence"] == BINDER_B
    assert all(bad[c] == "" for c in ("iptm", "ptm", "ranking_score", "pae_bt_mean", "pae_max", "pae_file", "cif"))
    assert not list((tmp_path / "out").glob("d2_*_pae.npy"))  # nothing saved for the refused design


def test_failing_design_is_a_blank_row_and_exit_3(mod, fasta, tmp_path, monkeypatch, capsys):
    def predict(**kw):
        if kw["binder_seq"] == BINDER_A:
            raise RuntimeError("CUDA out of memory")
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    code, out_csv = run_main(mod, fasta, tmp_path)
    err = capsys.readouterr().err
    rows = read_rows(out_csv)
    assert code == 3
    assert "1 of 2" in err
    assert "CUDA out of memory" in err
    assert rows[0]["sequence"] == BINDER_A and rows[0]["iptm"] == ""
    assert rows[0]["binder_length"] == str(NB)
    assert rows[1]["iptm"] != ""  # the design that folded is kept


def test_every_design_failing_is_an_error_not_a_quiet_zero(mod, fasta, tmp_path, monkeypatch):
    def predict(**kw):
        raise RuntimeError("no GPU")

    monkeypatch.setattr(mod, "_predict_one", predict)
    with pytest.raises(RuntimeError, match="All 2 binder"):
        run_main(mod, fasta, tmp_path)
    rows = read_rows(tmp_path / "of3.csv")
    assert len(rows) == 2 and all(r["iptm"] == "" for r in rows)


def test_resume_skips_a_scored_row_and_reruns_a_blank_one(mod, fasta, tmp_path, monkeypatch):
    out_csv = tmp_path / "of3.csv"
    write_refold_row(out_csv, {"run_id": "openfold3_0001", "idx": "1", "sequence": BINDER_A, "iptm": "0.7"})
    write_refold_row(out_csv, {"run_id": "openfold3_0002", "idx": "2", "sequence": BINDER_B})  # blank: a failure
    seen = []

    def predict(**kw):
        seen.append(kw["binder_seq"])
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    code, _ = run_main(mod, fasta, tmp_path, "--resume")
    assert code == 0
    assert seen == [BINDER_B]
    scored = {r["sequence"] for r in read_rows(out_csv) if r["iptm"]}
    assert scored == {BINDER_A, BINDER_B}


def test_run_info_and_msa_mode_sidecars_are_written(mod, fasta, tmp_path, monkeypatch):
    a3m = f">query\n{TARGET}\n>hit\n{TARGET}\n"
    monkeypatch.setattr(target_msa_mod, "_query_colabfold", lambda seq, *a, **k: a3m)
    seen = {}

    def predict(**kw):
        seen["target_msa_path"] = kw["target_msa_path"]
        seen["text"] = Path(kw["target_msa_path"]).read_text()
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    out_csv = tmp_path / "of3.csv"
    code = mod.main(
        [
            "--sequences",
            str(fasta),
            "--target-seq",
            TARGET,
            "--output",
            str(out_csv),
            "--output-dir",
            str(tmp_path / "out"),
            "--msa-cache-dir",
            str(tmp_path / "cache"),
            "--num-samples",
            "3",
        ]
    )
    assert code == 0
    assert seen["text"] == a3m  # the shared target MSA reached the model call as a file
    mode = json.loads((tmp_path / "out" / "target_msa_mode.json").read_text())
    assert mode["target_msa_mode"] == "fetched"
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["engine"] == "openfold3"
    assert info["weights_id"] == "openbind-2025-06-30-174k"
    assert info["n_samples"] == 3
    assert info["target_msa_mode"] == "fetched"
    assert info["seeds"] == [42]
    assert "engine_version" in info


def test_no_msa_run_records_single_sequence(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    run_main(mod, fasta, tmp_path)
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["target_msa_mode"] == "single_sequence"
    mode = json.loads((tmp_path / "out" / "target_msa_mode.json").read_text())
    assert mode["target_msa_mode"] == "single_sequence"


# --- the real invocation and output parsing (no model, no GPU) ----------------------------


def test_command_pins_the_checkpoint_and_turns_every_online_service_off(mod, tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {"loaded": True})
    mod._predict_one(
        query_id="q1",
        binder_seq=BINDER_A,
        target_seq=TARGET,
        target_msa_path=None,
        work_dir=tmp_path / "w",
        ckpt_path=None,
        ckpt_name="openbind-2025-06-30-174k",
        num_seeds=1,
        num_samples=5,
    )
    cmd = captured["cmd"]
    assert cmd[1:4] == ["-m", "openfold3.run_openfold", "predict"]

    def flag(name):
        return cmd[cmd.index(name) + 1]

    assert flag("--inference-ckpt-name") == "openbind-2025-06-30-174k"
    assert "--inference-ckpt-path" not in cmd
    assert flag("--use-msa-server") == "false"
    assert flag("--use-templates") == "false"
    assert flag("--num-diffusion-samples") == "5"
    # One seed means "do not pass --num-model-seeds": the flag would swap seed 42 for a derived one.
    assert "--num-model-seeds" not in cmd
    assert json.loads(Path(flag("--query-json")).read_text())["queries"]["q1"]["chains"][0]["chain_ids"] == "A"


def test_command_with_several_seeds_and_an_explicit_checkpoint(mod, tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    ckpt = tmp_path / "w.pt"
    mod._predict_one(
        query_id="q1",
        binder_seq=BINDER_A,
        target_seq=TARGET,
        target_msa_path=None,
        work_dir=tmp_path / "w",
        ckpt_path=ckpt,
        ckpt_name="ignored",
        num_seeds=3,
        num_samples=2,
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--num-model-seeds") + 1] == "3"
    assert cmd[cmd.index("--inference-ckpt-path") + 1] == str(ckpt)
    assert "--inference-ckpt-name" not in cmd


def test_nonzero_exit_or_missing_output_is_a_failure_not_a_blank_success(mod, tmp_path, monkeypatch):
    # run_openfold's writer logs a failed query and carries on, so rc==0 with no files happens.
    monkeypatch.setattr(
        mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "Failed to write predictions")
    )
    with pytest.raises(RuntimeError, match="no prediction"):
        mod._predict_one(
            query_id="q1",
            binder_seq=BINDER_A,
            target_seq=TARGET,
            target_msa_path=None,
            work_dir=tmp_path / "w",
            ckpt_path=None,
            ckpt_name="openbind-2025-06-30-174k",
            num_seeds=1,
            num_samples=1,
        )
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    with pytest.raises(RuntimeError, match="exited with code 1"):
        mod._predict_one(
            query_id="q2",
            binder_seq=BINDER_A,
            target_seq=TARGET,
            target_msa_path=None,
            work_dir=tmp_path / "w",
            ckpt_path=None,
            ckpt_name="openbind-2025-06-30-174k",
            num_seeds=1,
            num_samples=1,
        )


def _write_sample(root: Path, query_id: str, seed: int, sample: int, score: float, pae_value: float):
    d = root / query_id / f"seed_{seed}"
    d.mkdir(parents=True, exist_ok=True)
    prefix = d / f"{query_id}_seed_{seed}_sample_{sample}"
    Path(f"{prefix}_model.cif").write_text("data_stub\n")
    Path(f"{prefix}_confidences_aggregated.json").write_text(
        json.dumps({"iptm": 0.5, "ptm": 0.6, "sample_ranking_score": score, "avg_plddt": 80.0})
    )
    Path(f"{prefix}_confidences.json").write_text(
        json.dumps({"plddt": [90.0] * 4, "pde": [[0.0]], "pae": [[pae_value] * 3] * 3})
    )


def test_top_sample_is_the_highest_sample_ranking_score_across_seeds(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_ca_plddt_by_chain", lambda cif: {"A": np.full(NT, 90.0), "B": np.full(NB, 80.0)})
    _write_sample(tmp_path, "q1", 42, 1, 0.40, 1.0)
    _write_sample(tmp_path, "q1", 42, 2, 0.90, 2.0)  # the winner
    _write_sample(tmp_path, "q1", 43, 1, 0.60, 3.0)
    top = mod._load_top_sample(tmp_path, "q1")
    assert top["seed"] == 42
    assert top["cif"].name == "q1_seed_42_sample_2_model.cif"
    assert top["summary"]["sample_ranking_score"] == 0.9
    assert float(top["pae"][0, 0]) == 2.0
    assert top["pae"].shape == (3, 3)
    assert len(top["plddt_target"]) == NT and len(top["plddt_binder"]) == NB


def test_top_sample_is_none_when_nothing_was_written(mod, tmp_path):
    assert mod._load_top_sample(tmp_path, "q1") is None
