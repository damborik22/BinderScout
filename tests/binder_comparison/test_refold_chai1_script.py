"""refold_chai1.py with the model call stubbed behind ``_predict_one`` / a fake ``chai_lab``.

Chai-1 itself cannot run where these tests do. What they pin is the engine-specific part around the
model call: the version pin (only chai-lab 0.6.1, the release the licence record covers, runs;
anything else is refused before any work starts), which chain comes first in the FASTA (that fixes
the PAE order), how the cached ColabFold a3m becomes the ``<sha256(sequence)>.aligned.pqt`` file
Chai-1 looks up by name, the exact arguments of the ``run_inference`` call (made in a worker
subprocess so a CUDA OOM cannot take the batch with it), how the top sample and its files are
located, and that PAE / pLDDT are read from the right place and refused when they do not line up
with the sequences. The generic driver contract is tested in test_second_engine_driver.py.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from binder_comparison.refolding import target_msa as target_msa_mod

_SCRIPT = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts" / "refold_chai1.py"
# Distinct residues per position so a swapped chain order cannot match the other chain's sequence.
TARGET = "ACDEFGHIKL"  # 10 residues
BINDER_A = "MKVLAAGW"  # 8 residues
BINDER_B = "GGSSPPTT"  # 8 residues
NT, NB = len(TARGET), len(BINDER_A)

# One distinct constant per block of the native, TARGET-FIRST matrix.
TT, TB, BT, BB = 2.0, 25.0, 5.0, 1.0


@pytest.fixture()
def mod(monkeypatch):
    spec = importlib.util.spec_from_file_location("_refold_chai1_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The test env has no chai_lab installed; pretend the cleared release is.
    monkeypatch.setattr(module, "_engine_version", lambda: "0.6.1")
    return module


def native_pae(nt: int = NT, nb: int = NB) -> np.ndarray:
    """Chai-1's native order: chains in FASTA order, target first, binder second."""
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
        "seed": 101,
        "target_msa_depth": 1,  # the --no-msa runs of these tests: the target is its query alone
    }


@pytest.fixture()
def fasta(tmp_path):
    path = tmp_path / "seqs.fasta"
    path.write_text(f">d1 source=x\n{BINDER_A}\n>d2 source=y\n{BINDER_B}\n")
    return path


def run_main(mod, fasta, tmp_path, *extra):
    out_csv = tmp_path / "chai.csv"
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


# --- the version pin ---------------------------------------------------------------------------


def test_the_cleared_version_is_exactly_the_one_in_the_licence_record(mod):
    # Evaluator/docs/second_engine_licences.md: Chai-1, tag v0.6.1.
    assert mod.CLEARED_VERSION == "0.6.1"


@pytest.mark.parametrize("version", ["0.6.0", "0.5.0", "0.7.0", "1.0.0", "0.6.1.dev0", "0.6.10", "0.6", "unknown", ""])
def test_any_other_chai_lab_version_is_refused_before_anything_runs(mod, fasta, tmp_path, monkeypatch, version, capsys):
    monkeypatch.setattr(mod, "_engine_version", lambda: version)
    called = []
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: called.append(kw))
    code, out_csv = run_main(mod, fasta, tmp_path)
    assert code != 0
    assert not called
    assert not out_csv.exists()  # no row, blank or otherwise, was written
    err = capsys.readouterr().err
    assert "0.6.1" in err  # what is allowed is named
    assert "licen" in err.lower()  # and so is why


def test_the_model_seam_refuses_too_so_a_direct_call_cannot_bypass_configure(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_engine_version", lambda: "0.7.0")

    def boom(*a, **k):
        raise AssertionError("no worker may start for an uncleared chai-lab version")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    with pytest.raises(mod.UnclearedVersionError, match=r"0\.7\.0"):
        _call(mod, tmp_path)


def test_run_info_records_the_cleared_version_and_the_weights_identifier(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    code, _ = run_main(mod, fasta, tmp_path)
    assert code == 0
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["engine"] == "chai1"
    assert info["engine_version"] == "0.6.1"
    assert info["weights_id"] == mod.WEIGHTS_ID
    assert "models_v2" in mod.WEIGHTS_ID and "esm2_t36_3B_UR50D" in mod.WEIGHTS_ID
    assert info["seeds"] == [101]


def test_version_is_read_from_the_installed_package_metadata(monkeypatch):
    real = importlib_spec_module()
    seen = []

    def fake_version(name):
        seen.append(name)
        if name == "chai_lab":
            return "0.6.1"
        raise real.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(real.metadata, "version", fake_version)
    assert real._engine_version() == "0.6.1"
    assert seen[0] == "chai_lab"

    def not_installed(name):
        raise real.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(real.metadata, "version", not_installed)
    assert real._engine_version() == "unknown"


def importlib_spec_module():
    spec = importlib.util.spec_from_file_location("_refold_chai1_fresh", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- chain order --------------------------------------------------------------------------------


def test_saved_pae_is_reblocked_from_target_first_to_binder_first(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    code, out_csv = run_main(mod, fasta, tmp_path)
    assert code == 0
    rows = read_rows(out_csv)
    pae = np.load(rows[0]["pae_file"])
    assert Path(rows[0]["pae_file"]).name == "d1_chai1_pae.npy"
    assert pae.shape == (NB + NT, NB + NT)
    # [binder | target]: BB, BT / TB, TT -- blocks moved whole, none transposed.
    assert np.all(pae[:NB, :NB] == BB)
    assert np.all(pae[:NB, NB:] == BT)
    assert np.all(pae[NB:, :NB] == TB)
    assert np.all(pae[NB:, NB:] == TT)
    assert mod.NATIVE_PAE_ORDER == "target_binder"
    assert mod.Chai1Adapter.native_pae_order == "target_binder"


def test_fasta_lists_the_target_chain_first_then_the_binder_with_distinct_names(mod):
    text = mod.build_fasta(BINDER_A, TARGET)
    assert text == f">protein|name=target\n{TARGET}\n>protein|name=binder\n{BINDER_A}\n"


# --- MSA: a3m text -> <sha256>.aligned.pqt -------------------------------------------------------

A3M = (
    ">101\n"
    f"{TARGET}\n"
    ">UniRef100_AAA some protein\n"
    "ACDEFGHIKM\n"
    ">UniRef100_BBB other\n"
    "ACdDEFG-IKL\n"  # a lowercase insertion and a gap, as in a real a3m
    ">tr|CCC|env sample\n"
    "A-DEFGHIKL\n"
    ">padding\n"
    "----------\n"
)


def test_aligned_pqt_name_is_the_sha256_of_the_uppercased_sequence(mod):
    want = hashlib.sha256(TARGET.upper().encode()).hexdigest() + ".aligned.pqt"
    assert mod.aligned_pqt_name(TARGET) == want
    assert mod.aligned_pqt_name(TARGET.lower()) == want  # chai_lab uppercases before hashing


def test_a3m_becomes_the_four_column_table_chai_lab_validates(mod):
    df = mod.a3m_to_aligned_df(A3M, TARGET)
    assert list(df.columns) == ["sequence", "source_database", "pairing_key", "comment"]
    # Query first and alone; padding row dropped; the lowercase insertion is kept (a3m sequence format).
    assert list(df["sequence"]) == [TARGET, "ACDEFGHIKM", "ACdDEFG-IKL", "A-DEFGHIKL"]
    assert list(df["source_database"]) == ["query", "uniref90", "uniref90", "bfd_uniclust"]
    assert list(df["pairing_key"]) == ["", "", "", ""]  # unpaired: the binder has no MSA to pair with
    assert df["comment"].iloc[1] == "UniRef100_AAA some protein"
    assert (df["source_database"] == "query").sum() == 1 and df["source_database"].iloc[0] == "query"
    # Every value is a str, as chai_lab's pandera model coerces nothing else.
    assert all(isinstance(v, str) for col in df.columns for v in df[col])


def test_the_source_labels_are_ones_chai_lab_recognises(mod):
    # chai_lab.data.parsing.msas.aligned_pqt.RECOGNIZED_SOURCES: default sources + query.
    recognised = {"bfd_uniclust", "mgnify", "uniref90", "uniprot", "query"}
    df = mod.a3m_to_aligned_df(A3M, TARGET)
    assert set(df["source_database"]) <= recognised


def test_an_a3m_whose_query_row_is_not_the_target_is_refused(mod):
    with pytest.raises(ValueError, match="query"):
        mod.a3m_to_aligned_df(A3M.replace(f"101\n{TARGET}", "101\nMMMMMMMMMM"), TARGET)


def test_an_a3m_row_with_the_wrong_number_of_columns_is_refused(mod):
    # Chai-1 would hit a token-count mismatch inside the model; fail here instead, naming the row.
    short = A3M.replace("ACDEFGHIKM", "ACDEFGHIK")
    with pytest.raises(ValueError, match="aligned columns"):
        mod.a3m_to_aligned_df(short, TARGET)
    # A lowercase insertion does not count as a column.
    assert len(mod.a3m_to_aligned_df(A3M, TARGET)) == 4


def test_multiline_a3m_records_are_joined(mod):
    df = mod.a3m_to_aligned_df(f">101\n{TARGET[:4]}\n{TARGET[4:]}\n>hit\nACDEF\nGHIKL\n", TARGET)
    assert list(df["sequence"]) == [TARGET, "ACDEFGHIKL"]


def test_with_a_target_msa_only_the_target_gets_a_parquet_and_the_binder_none(mod, tmp_path, monkeypatch):
    written = []
    monkeypatch.setattr(mod, "_write_parquet", lambda df, path: written.append((df, Path(path))))
    a3m = tmp_path / "shared" / "target.a3m"
    a3m.parent.mkdir()
    a3m.write_text(A3M)
    paths = mod.prepare_inputs(tmp_path / "w", BINDER_A, TARGET, target_msa_path=a3m)
    assert [p.name for _, p in written] == [mod.aligned_pqt_name(TARGET)]
    assert written[0][1].parent == paths["msa_dir"]
    assert not (paths["msa_dir"] / mod.aligned_pqt_name(BINDER_A)).exists()  # binder: no MSA
    assert Path(paths["fasta"]).read_text() == mod.build_fasta(BINDER_A, TARGET)
    assert written[0][0]["source_database"].iloc[0] == "query"


def test_without_a_target_msa_the_msa_directory_exists_but_is_empty(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_write_parquet", lambda *a, **k: pytest.fail("no MSA must be written"))
    paths = mod.prepare_inputs(tmp_path / "w", BINDER_A, TARGET, target_msa_path=None)
    # An existing, empty directory (not None): both chains are then single-sequence in the same way,
    # which keeps the binder's input identical to the with-MSA run.
    assert paths["msa_dir"].is_dir() and list(paths["msa_dir"].iterdir()) == []


def test_a_parquet_round_trips_through_pandas(mod, tmp_path):
    pytest.importorskip("pyarrow")
    path = tmp_path / mod.aligned_pqt_name(TARGET)
    mod._write_parquet(mod.a3m_to_aligned_df(A3M, TARGET), path)
    back = pd.read_parquet(path)
    assert back["source_database"].iloc[0] == "query" and len(back) == 4


def test_target_msa_a3m_text_reaches_the_model_call_as_a_file(mod, fasta, tmp_path, monkeypatch):
    a3m = f">101\n{TARGET}\n>hit\n{TARGET}\n"
    monkeypatch.setattr(target_msa_mod, "_query_colabfold", lambda seq, *a, **k: a3m)
    seen = {}

    def predict(**kw):
        seen["text"] = Path(kw["target_msa_path"]).read_text()
        return {**fake_prediction(tmp_path, kw["query_id"]), "target_msa_depth": 4045}

    monkeypatch.setattr(mod, "_predict_one", predict)
    code = mod.main(
        [
            "--sequences",
            str(fasta),
            "--target-seq",
            TARGET,
            "--output",
            str(tmp_path / "chai.csv"),
            "--output-dir",
            str(tmp_path / "out"),
            "--msa-cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    assert code == 0
    assert seen["text"] == a3m
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["target_msa_mode"] == "fetched"


# --- the worker subprocess command ----------------------------------------------------------------


def _capture_run(mod, monkeypatch, *, returncode=0, stderr="", write_result=None):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"], captured["kw"] = cmd, kw
        captured["spec"] = json.loads(Path(cmd[-1]).read_text())
        if write_result is not None:
            write_result(captured["spec"])
        return subprocess.CompletedProcess(cmd, returncode, "", stderr)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return captured


def _touch_result(spec):
    Path(spec["result"]).write_bytes(b"stub")  # the (stubbed) loader never reads it


def _call(mod, tmp_path, **over):
    kw = dict(
        query_id="q1",
        binder_seq=BINDER_A,
        target_seq=TARGET,
        target_msa_path=None,
        work_dir=tmp_path / "w",
        model_dir=None,
        num_seeds=1,
        num_samples=5,
    )
    kw.update(over)
    return mod._predict_one(**kw)


def test_worker_command_runs_this_script_in_worker_mode_with_a_spec_file(mod, tmp_path, monkeypatch):
    captured = _capture_run(mod, monkeypatch, write_result=_touch_result)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {"loaded": True})
    assert _call(mod, tmp_path) == {"loaded": True}
    cmd = captured["cmd"]
    assert cmd[0] == sys.executable
    assert Path(cmd[1]) == _SCRIPT or Path(cmd[1]).name == "refold_chai1.py"
    assert cmd[2] == "--chai-worker"
    assert len(cmd) == 4
    # Captured as text, so a failure's stderr is a str the driver can tail.
    assert captured["kw"]["capture_output"] is True and captured["kw"]["text"] is True


def test_spec_carries_the_inputs_and_the_documented_default_settings(mod, tmp_path, monkeypatch):
    captured = _capture_run(mod, monkeypatch, write_result=_touch_result)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    a3m = tmp_path / "t" / "target.a3m"
    a3m.parent.mkdir()
    a3m.write_text(A3M)
    monkeypatch.setattr(mod, "_write_parquet", lambda df, path: Path(path).write_bytes(b"x"))
    _call(mod, tmp_path, target_msa_path=a3m, num_seeds=3, num_samples=2)
    spec = captured["spec"]
    assert Path(spec["fasta"]).read_text() == mod.build_fasta(BINDER_A, TARGET)
    assert (Path(spec["msa_dir"]) / mod.aligned_pqt_name(TARGET)).is_file()
    assert spec["num_samples"] == 2
    assert spec["num_seeds"] == 3
    assert spec["seed"] == 101
    # The output directory must not exist yet: run_inference asserts a missing-or-empty directory.
    assert not Path(spec["output_dir"]).exists()
    assert Path(spec["output_dir"]).parent == tmp_path / "w"


def test_model_dir_becomes_chai_downloads_dir_for_the_worker_only(mod, tmp_path, monkeypatch):
    monkeypatch.delenv("CHAI_DOWNLOADS_DIR", raising=False)
    captured = _capture_run(mod, monkeypatch, write_result=_touch_result)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    _call(mod, tmp_path)
    assert "CHAI_DOWNLOADS_DIR" not in captured["kw"]["env"]
    root = tmp_path / "chai_dl"
    _call(mod, tmp_path, model_dir=root)
    assert captured["kw"]["env"]["CHAI_DOWNLOADS_DIR"] == str(root)


def test_nonzero_exit_is_a_failure_and_its_stderr_is_text(mod, tmp_path, monkeypatch):
    _capture_run(mod, monkeypatch, returncode=1, stderr="torch.OutOfMemoryError: CUDA out of memory")
    with pytest.raises(mod.EngineError, match="exited with code 1") as exc:
        _call(mod, tmp_path)
    assert isinstance(exc.value.stderr, str) and "CUDA out of memory" in exc.value.stderr


def test_exit_zero_with_no_result_file_is_a_failed_design(mod, tmp_path, monkeypatch):
    _capture_run(mod, monkeypatch, returncode=0, stderr="INFO fine")
    with pytest.raises(mod.EngineError, match="no result") as exc:
        _call(mod, tmp_path)
    assert isinstance(exc.value.stderr, str)


def test_a_stale_work_dir_is_cleared_before_the_run(mod, tmp_path, monkeypatch):
    stale = tmp_path / "w" / "chai_out"
    stale.mkdir(parents=True)
    (stale / "pred.model_idx_0.cif").write_text("old")
    (tmp_path / "w" / mod.RESULT_NAME).write_bytes(b"old")
    _capture_run(mod, monkeypatch)
    with pytest.raises(mod.EngineError, match="no result"):
        _call(mod, tmp_path)  # the leftovers of an earlier attempt must not be picked up
    assert not stale.exists()


# --- the worker: the actual chai_lab call ---------------------------------------------------------


class _T:
    """A stand-in for a torch tensor: just the methods the worker may call."""

    def __init__(self, arr):
        self._a = np.asarray(arr)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._a

    def float(self):
        return self


def _fake_chai_lab(monkeypatch, tmp_path, *, version="0.6.1", n_cand=3, nt=NT, nb=NB, agg=None, target_depth=4045):
    """A fake ``chai_lab`` with the three names the worker's MSA probe wraps.

    ``run_inference`` calls ``chai1.get_msa_contexts`` (looked up at call time, as in chai-lab); that calls
    ``load.parse_aligned_pqt_to_msa_context`` for the target's ``.aligned.pqt`` if the file exists in the MSA
    directory, and reports ``target_depth`` as its depth.
    """
    import hashlib

    calls = []
    n = nt + nb
    chai1 = types.ModuleType("chai_lab.chai1")
    load = types.ModuleType("chai_lab.data.dataset.msas.load")
    aligned = types.ModuleType("chai_lab.data.parsing.msas.aligned_pqt")

    aligned.expected_basename = lambda seq: hashlib.sha256(seq.upper().encode()).hexdigest() + ".aligned.pqt"
    load.parse_aligned_pqt_to_msa_context = lambda path, *a, **k: types.SimpleNamespace(depth=target_depth)

    def get_msa_contexts(chains, msa_directory):
        path = Path(msa_directory) / aligned.expected_basename(TARGET)
        if path.is_file():
            load.parse_aligned_pqt_to_msa_context(path)  # looked up at call time, like load.py's own global
        return "joined", "profile"

    chai1.get_msa_contexts = get_msa_contexts

    def run_inference(**kw):
        calls.append(kw)
        chai1.get_msa_contexts(["chains"], msa_directory=kw["msa_directory"])
        out = Path(kw["output_dir"])
        out.mkdir(parents=True)
        cifs = []
        for i in range(n_cand):
            cif = out / f"pred.model_idx_{i}.cif"
            cif.write_text("data_x\n")
            cifs.append(cif)
        scores = agg if agg is not None else [0.1 * (i + 1) for i in range(n_cand)]
        rds = [
            types.SimpleNamespace(
                aggregate_score=_T([scores[i]]),
                ptm_scores=types.SimpleNamespace(complex_ptm=_T([0.5 + i / 10]), interface_ptm=_T([0.4 + i / 10])),
            )
            for i in range(n_cand)
        ]
        pae = np.stack([np.full((n, n), float(i), dtype=np.float32) for i in range(n_cand)])
        return types.SimpleNamespace(cif_paths=cifs, ranking_data=rds, pae=_T(pae))

    chai1.run_inference = run_inference
    pkg = types.ModuleType("chai_lab")
    pkg.__version__ = version
    pkg.chai1 = chai1
    for name, module in {
        "chai_lab": pkg,
        "chai_lab.chai1": chai1,
        "chai_lab.data": types.ModuleType("chai_lab.data"),
        "chai_lab.data.dataset": types.ModuleType("chai_lab.data.dataset"),
        "chai_lab.data.dataset.msas": types.ModuleType("chai_lab.data.dataset.msas"),
        "chai_lab.data.dataset.msas.load": load,
        "chai_lab.data.parsing": types.ModuleType("chai_lab.data.parsing"),
        "chai_lab.data.parsing.msas": types.ModuleType("chai_lab.data.parsing.msas"),
        "chai_lab.data.parsing.msas.aligned_pqt": aligned,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    # attribute links so `from chai_lab.data.dataset.msas import load` resolves
    sys.modules["chai_lab.data.dataset.msas"].load = load
    sys.modules["chai_lab.data.dataset"].msas = sys.modules["chai_lab.data.dataset.msas"]
    return calls


def _write_spec(mod, tmp_path, **over):
    paths = mod.prepare_inputs(tmp_path / "w", BINDER_A, TARGET, target_msa_path=None)
    spec = {
        "fasta": str(paths["fasta"]),
        "msa_dir": str(paths["msa_dir"]),
        "output_dir": str(tmp_path / "w" / "chai_out"),
        "result": str(tmp_path / "w" / mod.RESULT_NAME),
        "num_samples": 3,
        "num_seeds": 1,
        "seed": 101,
        "target_seq": TARGET,
        "expect_target_msa": False,
    }
    spec.update(over)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    return path, spec


def test_worker_calls_run_inference_with_the_recorded_settings(mod, tmp_path, monkeypatch):
    calls = _fake_chai_lab(monkeypatch, tmp_path)
    spec_path, spec = _write_spec(mod, tmp_path, num_samples=3, num_seeds=1)
    assert mod.main(["--chai-worker", str(spec_path)]) == 0
    [kw] = calls
    assert kw == {
        "fasta_file": Path(spec["fasta"]),
        "output_dir": Path(spec["output_dir"]),
        "use_esm_embeddings": True,  # Chai-1's default; the binder's only evolutionary signal
        "use_msa_server": False,  # nothing is queried online
        "msa_directory": Path(spec["msa_dir"]),
        "num_trunk_recycles": 3,
        "num_diffn_timesteps": 200,
        "num_diffn_samples": 3,
        "num_trunk_samples": 1,
        "seed": 101,
        "low_memory": True,
    }
    assert "constraint_path" not in kw and "use_templates_server" not in kw and "template_hits_path" not in kw


def test_worker_maps_num_seeds_to_trunk_samples(mod, tmp_path, monkeypatch):
    calls = _fake_chai_lab(monkeypatch, tmp_path, n_cand=6)
    spec_path, _ = _write_spec(mod, tmp_path, num_samples=2, num_seeds=3)
    assert mod.main(["--chai-worker", str(spec_path)]) == 0
    assert calls[0]["num_trunk_samples"] == 3 and calls[0]["num_diffn_samples"] == 2


def test_worker_dumps_every_candidate_with_its_pae_and_scores(mod, tmp_path, monkeypatch):
    _fake_chai_lab(monkeypatch, tmp_path, n_cand=3, agg=[0.30, 0.10, 0.20])
    spec_path, spec = _write_spec(mod, tmp_path, num_samples=3)
    assert mod.main(["--chai-worker", str(spec_path)]) == 0
    with np.load(spec["result"], allow_pickle=False) as res:
        assert res["pae"].shape == (3, NT + NB, NT + NB)
        np.testing.assert_allclose(res["aggregate_score"], [0.30, 0.10, 0.20])
        np.testing.assert_allclose(res["ptm"], [0.5, 0.6, 0.7])
        np.testing.assert_allclose(res["iptm"], [0.4, 0.5, 0.6])
        assert [Path(p).name for p in res["cif_paths"]] == [f"pred.model_idx_{i}.cif" for i in range(3)]
        assert float(res["pae"][2][0, 0]) == 2.0  # candidate i's PAE is stored at index i


def test_worker_refuses_a_chai_lab_that_is_not_the_cleared_version(mod, tmp_path, monkeypatch):
    calls = _fake_chai_lab(monkeypatch, tmp_path, version="0.7.0")
    spec_path, _ = _write_spec(mod, tmp_path)
    with pytest.raises(mod.UnclearedVersionError, match=r"0\.7\.0"):
        mod.main(["--chai-worker", str(spec_path)])
    assert calls == []  # the model was never called


def test_worker_refuses_when_pae_and_structures_do_not_line_up(mod, tmp_path, monkeypatch):
    calls = _fake_chai_lab(monkeypatch, tmp_path, n_cand=2)
    spec_path, _ = _write_spec(mod, tmp_path, num_samples=3, num_seeds=1)  # asked for 3, fake gives 2
    with pytest.raises(RuntimeError, match="candidate"):
        mod.main(["--chai-worker", str(spec_path)])
    assert calls  # the call was made; the result was then judged short


# --- the result file: top sample -------------------------------------------------------------------

_COLUMNS = [
    "group_PDB",
    "id",
    "type_symbol",
    "label_atom_id",
    "label_alt_id",
    "label_comp_id",
    "label_seq_id",
    "auth_seq_id",
    "pdbx_PDB_ins_code",
    "label_asym_id",
    "Cartn_x",
    "Cartn_y",
    "Cartn_z",
    "occupancy",
    "label_entity_id",
    "auth_asym_id",
    "auth_comp_id",
    "B_iso_or_equiv",
    "pdbx_PDB_model_num",
]
_THREE = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "K": "LYS",
    "L": "LEU",
    "M": "MET",
    "N": "ASN",
    "P": "PRO",
    "Q": "GLN",
    "R": "ARG",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
    "Y": "TYR",
}


def mini_cif(
    *,
    target: str = TARGET,
    binder: str = BINDER_A,
    target_b=90.0,
    binder_b=80.0,
    drop_ca: tuple[str, int] | None = None,
    extra_chain: bool = False,
    chains: tuple[str, str] = ("A", "B"),
):
    """A ModelCIF-shaped file as chai_lab writes it (modelcif/ihm dumper): the same _atom_site columns and
    value layout (``?`` for the insertion code, ``.`` for the alt id), a loop before and after it."""
    lines = [
        "data_pred",
        "#",
        "loop_",
        "_ma_qa_metric_local.ordinal_id",
        "_ma_qa_metric_local.label_asym_id",
        "1 A",
        "#",
        "loop_",
        *(f"_atom_site.{c}" for c in _COLUMNS),
    ]
    serial = 0
    groups = [(chains[0], target, target_b), (chains[1], binder, binder_b)]
    if extra_chain:
        groups.append(("C", "AA", 50.0))
    for ent, (chain, seq, b) in enumerate(groups, start=1):
        for res, aa in enumerate(seq, start=1):
            for atom in ("N", "CA", "C", "O"):
                if drop_ca == (chain, res) and atom == "CA":
                    continue
                serial += 1
                lines.append(
                    f"ATOM {serial} {atom[0]} {atom} . {_THREE.get(aa, 'UNK')} {res} {res} ? {chain} 1.000 2.000 3.000 1.000 "
                    f"{ent} {chain} {_THREE.get(aa, 'UNK')} {b:.3f} 1"
                )
    lines += ["#", "#", "loop_", "_atom_type.symbol", "C", "N", "O", "#"]
    return "\n".join(lines) + "\n"


def write_result(
    root: Path, name: str, scores, *, cifs=None, nt=NT, nb=NB, paes=None, ptm=None, result_path=None, depth=1
):
    """Write what the worker writes: result npz + one CIF per candidate. Returns (result_path, cif_paths)."""
    n = len(scores)
    root.mkdir(parents=True, exist_ok=True)
    cif_paths = []
    for i in range(n):
        p = root / f"{name}_pred.model_idx_{i}.cif"
        p.write_text(mini_cif() if cifs is None else cifs[i])
        cif_paths.append(str(p))
    pae = np.stack([np.full((nt + nb,) * 2, float(i)) for i in range(n)]) if paes is None else np.stack(paes)
    result = Path(result_path) if result_path else root / mod_result_name()
    np.savez(
        result,
        pae=pae.astype(np.float32),
        aggregate_score=np.asarray(scores, dtype=np.float32),
        iptm=np.asarray([0.40 + i / 100 for i in range(n)], dtype=np.float32),
        ptm=np.asarray([0.60 + i / 100 for i in range(n)] if ptm is None else ptm, dtype=np.float32),
        cif_paths=np.asarray(cif_paths),
        **({} if depth is None else {"target_msa_depth": np.int64(depth)}),
    )
    return result, cif_paths


def mod_result_name():
    return importlib_spec_module().RESULT_NAME


def test_top_sample_is_the_highest_aggregate_score_and_its_own_pae(mod, tmp_path):
    result, cifs = write_result(tmp_path, "q1", [0.20, 0.90, 0.40])
    top = mod._load_top_sample(result, num_samples=3, seed=101, binder_seq=BINDER_A, target_seq=TARGET)
    assert top["cif"] == Path(cifs[1])
    assert top["summary"]["sample_ranking_score"] == pytest.approx(0.90)
    assert top["summary"]["iptm"] == pytest.approx(0.41) and top["summary"]["ptm"] == pytest.approx(0.61)
    assert float(top["pae"][0, 0]) == 1.0  # candidate 1's PAE, not another's
    assert top["pae"].shape == (NT + NB, NT + NB)
    assert len(top["plddt_target"]) == NT and len(top["plddt_binder"]) == NB


def test_non_finite_scores_are_skipped_and_all_non_finite_is_an_error(mod, tmp_path):
    result, cifs = write_result(tmp_path, "q1", [float("nan"), 0.30, float("inf")])
    kw = dict(num_samples=3, seed=101, binder_seq=BINDER_A, target_seq=TARGET)
    assert mod._load_top_sample(result, **kw)["cif"] == Path(cifs[1])
    result2, _ = write_result(tmp_path / "b", "q2", [float("nan"), float("nan")])
    with pytest.raises(mod.EngineError, match="finite"):
        mod._load_top_sample(result2, **{**kw, "num_samples": 2})


def test_a_missing_cif_makes_a_candidate_ineligible(mod, tmp_path):
    result, cifs = write_result(tmp_path, "q1", [0.99, 0.20])
    Path(cifs[0]).unlink()
    kw = dict(num_samples=2, seed=101, binder_seq=BINDER_A, target_seq=TARGET)
    assert mod._load_top_sample(result, **kw)["cif"] == Path(cifs[1])


def test_seed_of_the_top_sample_is_base_plus_its_trunk_index(mod, tmp_path):
    # 2 samples per trunk, 3 trunks (num_seeds=3): candidate 4 is trunk 2 -> seed 103.
    result, _ = write_result(tmp_path, "q1", [0.1, 0.1, 0.1, 0.1, 0.9, 0.1])
    kw = dict(num_samples=2, seed=101, binder_seq=BINDER_A, target_seq=TARGET)
    assert mod._load_top_sample(result, **kw)["seed"] == 103
    result2, _ = write_result(tmp_path / "b", "q2", [0.9, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert mod._load_top_sample(result2, **kw)["seed"] == 101


def test_pae_is_passed_through_in_native_target_first_order(mod, tmp_path):
    result, _ = write_result(tmp_path, "q1", [0.5], paes=[native_pae()])
    top = mod._load_top_sample(result, num_samples=1, seed=101, binder_seq=BINDER_A, target_seq=TARGET)
    np.testing.assert_array_equal(top["pae"], native_pae())  # untouched here; the driver re-blocks it


def test_a_result_whose_candidate_count_disagrees_with_the_request_is_an_error(mod, tmp_path):
    result, _ = write_result(tmp_path, "q1", [0.5, 0.4])
    with pytest.raises(mod.EngineError, match="candidate"):
        mod._load_top_sample(result, num_samples=5, seed=101, binder_seq=BINDER_A, target_seq=TARGET)


# --- pLDDT and the structure check -----------------------------------------------------------------


def test_per_residue_plddt_is_the_ca_b_factor_per_chain_on_a_0_100_scale(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(target_b=91.5, binder_b=64.25))
    out = mod._ca_plddt_by_chain(cif, TARGET, BINDER_A)
    np.testing.assert_allclose(out["A"], np.full(NT, 91.5))
    np.testing.assert_allclose(out["B"], np.full(NB, 64.25))


def test_a_residue_without_a_ca_atom_fails_loudly(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(drop_ca=("B", 3)))
    with pytest.raises(ValueError, match="CA"):
        mod._ca_plddt_by_chain(cif, TARGET, BINDER_A)
    cif.write_text(mini_cif(drop_ca=("A", 1)))
    with pytest.raises(ValueError, match="CA"):
        mod._ca_plddt_by_chain(cif, TARGET, BINDER_A)


def test_a_chain_with_the_wrong_residue_count_fails_loudly(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(binder=BINDER_A + "GG"))
    with pytest.raises(ValueError, match="binder"):
        mod._ca_plddt_by_chain(cif, TARGET, BINDER_A)


def test_chains_written_in_the_wrong_order_are_refused_even_at_equal_length(mod, tmp_path):
    # Same lengths on purpose: counts alone cannot see that chain A holds the binder's residues.
    t, b = "ACDEFGHIKL", "MKVLAAGWPQ"
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(target=b, binder=t))
    with pytest.raises(ValueError, match="sequence"):
        mod._ca_plddt_by_chain(cif, t, b)
    cif.write_text(mini_cif(target=t, binder=b))
    assert set(mod._ca_plddt_by_chain(cif, t, b)) == {"A", "B"}


def test_an_unexpected_extra_chain_is_refused(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(extra_chain=True))
    with pytest.raises(ValueError, match="chain"):
        mod._ca_plddt_by_chain(cif, TARGET, BINDER_A)


def test_b_factors_that_are_all_zero_mean_no_plddt_was_written(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(target_b=0.0, binder_b=0.0))
    with pytest.raises(ValueError, match="pLDDT"):
        mod._ca_plddt_by_chain(cif, TARGET, BINDER_A)


def test_a_cif_without_an_atom_site_loop_or_chain_is_refused(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text("data_stub\n")
    with pytest.raises(ValueError, match="atom_site"):
        mod._ca_plddt_by_chain(cif, TARGET, BINDER_A)


def test_non_standard_letters_are_unk_x_on_both_sides(mod, tmp_path):
    # chai_lab turns a letter outside the 20 into UNK; the expected sequence must do the same.
    assert mod._expected_residues("AXBZ") == ["A", "X", "X", "X"]
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(target="AXC", binder="MKV"))  # X is written as UNK
    assert set(mod._ca_plddt_by_chain(cif, "AXC", "MKV")) == {"A", "B"}
    with pytest.raises(ValueError, match="sequence"):
        mod._ca_plddt_by_chain(cif, "AGC", "MKV")


def test_the_whole_top_sample_path_validates_the_structure_of_the_chosen_candidate(mod, tmp_path):
    # Candidate 1 wins on score but its CIF has a missing CA: the design must fail, not fall back silently.
    bad = mini_cif(drop_ca=("B", 2))
    result, _ = write_result(tmp_path, "q1", [0.2, 0.9], cifs=[mini_cif(), bad])
    with pytest.raises(ValueError, match="CA"):
        mod._load_top_sample(result, num_samples=2, seed=101, binder_seq=BINDER_A, target_seq=TARGET)


def test_end_to_end_through_the_driver_with_the_worker_stubbed(mod, fasta, tmp_path, monkeypatch):
    # _predict_one -> (stubbed subprocess writing a result) -> _load_top_sample -> driver -> CSV row.
    def write(spec):
        root = Path(spec["result"]).parent / "cifs"
        write_result(root, "x", [0.2, 0.8], paes=[np.zeros((NT + NB,) * 2), native_pae()], result_path=spec["result"])

    _capture_run(mod, monkeypatch, write_result=write)
    out_csv = tmp_path / "chai.csv"
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
            "--no-msa",
            "--num-samples",
            "2",
        ]
    )
    rows = read_rows(out_csv)
    # The stub's structure holds BINDER_A, so d2 (BINDER_B) fails the residue check: blank row, exit 3.
    assert code == 3
    assert rows[0]["iptm"] != "" and rows[0]["pae_file"] != ""
    assert float(rows[0]["pae_bt_mean"]) == pytest.approx(BT)  # rows binder, cols target of the native matrix
    assert float(rows[0]["pae_tb_mean"]) == pytest.approx(TB)
    assert rows[1]["iptm"] == "" and rows[1]["pae_file"] == ""


# --- a target MSA that fails to load cannot be hidden ----------------------------------------------


def _msa_file(mod, spec):
    """Drop a stand-in for the target's .aligned.pqt where chai-lab looks for it."""
    path = Path(spec["msa_dir"]) / mod.aligned_pqt_name(TARGET)
    path.write_bytes(b"pqt")
    return path


def test_check_target_msa_depth_fails_only_a_query_only_target_when_an_msa_was_expected(mod):
    mod.check_target_msa_depth(4045, expect_msa=True)
    mod.check_target_msa_depth(1, expect_msa=False)  # --no-msa: depth 1 is the intended state
    with pytest.raises(mod.EngineError, match="depth 1"):
        mod.check_target_msa_depth(1, expect_msa=True)
    with pytest.raises(mod.EngineError, match="no target_msa_depth"):
        mod.check_target_msa_depth(None, expect_msa=False)  # a missing measurement is never silently fine


def test_worker_records_the_depth_chai_lab_actually_loaded_for_the_target(mod, tmp_path, monkeypatch):
    _fake_chai_lab(monkeypatch, tmp_path, target_depth=4045)
    spec_path, spec = _write_spec(mod, tmp_path, expect_target_msa=True)
    _msa_file(mod, spec)
    assert mod.main(["--chai-worker", str(spec_path)]) == 0
    with np.load(spec["result"], allow_pickle=False) as res:
        assert int(res["target_msa_depth"]) == 4045


def test_worker_fails_the_design_before_any_model_work_when_the_target_msa_did_not_load(mod, tmp_path, monkeypatch):
    _fake_chai_lab(monkeypatch, tmp_path)
    spec_path, spec = _write_spec(mod, tmp_path, expect_target_msa=True)  # but no file for the target
    with pytest.raises(mod.EngineError, match="depth 1"):
        mod.main(["--chai-worker", str(spec_path)])
    assert not Path(spec["result"]).exists()
    assert not Path(spec["output_dir"]).exists()  # run_inference never got as far as writing structures


def test_worker_without_an_expected_msa_records_depth_1(mod, tmp_path, monkeypatch):
    _fake_chai_lab(monkeypatch, tmp_path)
    spec_path, spec = _write_spec(mod, tmp_path, expect_target_msa=False)
    assert mod.main(["--chai-worker", str(spec_path)]) == 0
    with np.load(spec["result"], allow_pickle=False) as res:
        assert int(res["target_msa_depth"]) == 1


def test_worker_refuses_a_chai_lab_whose_loader_it_cannot_wrap(mod, tmp_path, monkeypatch):
    _fake_chai_lab(monkeypatch, tmp_path)
    monkeypatch.delattr(sys.modules["chai_lab.data.dataset.msas.load"], "parse_aligned_pqt_to_msa_context")
    spec_path, spec = _write_spec(mod, tmp_path, expect_target_msa=True)
    with pytest.raises(AttributeError):
        mod.main(["--chai-worker", str(spec_path)])
    assert not Path(spec["result"]).exists()


def test_spec_tells_the_worker_the_target_and_whether_an_msa_is_expected(mod, tmp_path, monkeypatch):
    captured = _capture_run(mod, monkeypatch, write_result=_touch_result)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    monkeypatch.setattr(mod, "_write_parquet", lambda df, path: Path(path).write_bytes(b"x"))
    _call(mod, tmp_path)
    assert captured["spec"]["target_seq"] == TARGET and captured["spec"]["expect_target_msa"] is False
    a3m = tmp_path / "t" / "target.a3m"
    a3m.parent.mkdir()
    a3m.write_text(A3M)
    _call(mod, tmp_path, target_msa_path=a3m)
    assert captured["spec"]["expect_target_msa"] is True


def test_load_top_sample_returns_the_depth_the_worker_measured(mod, tmp_path):
    kw = dict(num_samples=2, seed=101, binder_seq=BINDER_A, target_seq=TARGET)
    result, _ = write_result(tmp_path, "q1", [0.2, 0.9], depth=4045)
    assert mod._load_top_sample(result, **kw)["target_msa_depth"] == 4045
    result2, _ = write_result(tmp_path / "b", "q2", [0.2, 0.9], depth=None)  # an older / foreign result file
    assert mod._load_top_sample(result2, **kw)["target_msa_depth"] is None


def _fetched_run(mod, fasta, tmp_path, monkeypatch, depths):
    """Run main in fetched-MSA mode with a stubbed model call returning the given depth per design."""
    a3m = f">101\n{TARGET}\n>hit\n{TARGET}\n"
    monkeypatch.setattr(target_msa_mod, "_query_colabfold", lambda seq, *a, **k: a3m)
    queue = list(depths)

    def predict(**kw):
        pred = fake_prediction(tmp_path, kw["query_id"])
        depth = queue.pop(0)
        if depth == "absent":
            del pred["target_msa_depth"]
        else:
            pred["target_msa_depth"] = depth
        return pred

    monkeypatch.setattr(mod, "_predict_one", predict)
    out_csv = tmp_path / "chai.csv"
    argv = ["--sequences", str(fasta), "--target-seq", TARGET, "--output", str(out_csv)]
    argv += ["--output-dir", str(tmp_path / "out"), "--msa-cache-dir", str(tmp_path / "cache")]
    return mod.main(argv), out_csv


def test_fetched_mode_records_the_pool_constant_depth_in_run_info(mod, fasta, tmp_path, monkeypatch):
    code, _ = _fetched_run(mod, fasta, tmp_path, monkeypatch, [4045, 4045])
    assert code == 0
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["settings"] == {"target_msa_depth": 4045}


def test_no_msa_mode_records_depth_1_without_failing(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    code, _ = run_main(mod, fasta, tmp_path)
    assert code == 0
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["settings"] == {"target_msa_depth": 1}


def test_a_query_only_target_in_fetched_mode_is_a_blank_row(mod, fasta, tmp_path, monkeypatch, capsys):
    code, out_csv = _fetched_run(mod, fasta, tmp_path, monkeypatch, [4045, 1])
    rows = read_rows(out_csv)
    assert code == 3 and rows[0]["iptm"] != "" and rows[1]["iptm"] == "" and rows[1]["pae_file"] == ""
    assert "depth 1" in capsys.readouterr().err


def test_a_depth_that_differs_between_designs_fails_the_odd_one(mod, fasta, tmp_path, monkeypatch, capsys):
    code, out_csv = _fetched_run(mod, fasta, tmp_path, monkeypatch, [4045, 3000])
    rows = read_rows(out_csv)
    assert code == 3 and rows[0]["iptm"] != "" and rows[1]["iptm"] == ""
    assert "differs" in capsys.readouterr().err
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["settings"] == {"target_msa_depth": 4045}  # the pool constant is the one that scored


def test_a_result_with_no_depth_measurement_fails_the_design(mod, fasta, tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="no target_msa_depth"):  # every design lacked it: the all-failed error
        _fetched_run(mod, fasta, tmp_path, monkeypatch, ["absent", "absent"])
    assert all(r["iptm"] == "" for r in read_rows(tmp_path / "chai.csv"))


def test_a_4045_row_a3m_converts_without_losing_a_row(mod, tmp_path):
    # PD-L1 smoke: depth 4045. The conversion must hand chai-lab every distinct non-gap row of the a3m.
    hits = ["".join("ACDEFGHIKLMNPQRSTVWY"[(i // 20**k) % 20] for k in range(len(TARGET))) for i in range(1, 4045)]
    a3m = f">101\n{TARGET}\n" + "".join(f">hit{i}\n{h}\n" for i, h in enumerate(hits))
    df = mod.a3m_to_aligned_df(a3m, TARGET)
    assert len(df) == 4045 and df["source_database"].iloc[0] == "query"
    pytest.importorskip("pyarrow")
    path = tmp_path / mod.aligned_pqt_name(TARGET)
    mod._write_parquet(df, path)
    assert len(pd.read_parquet(path)) == 4045
