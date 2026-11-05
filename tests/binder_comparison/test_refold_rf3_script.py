"""refold_rf3.py with the model call stubbed behind ``_predict_one`` / ``subprocess.run``.

RF3 (RoseTTAFold3, RosettaCommons Foundry) cannot run where these tests do. What they pin is the
engine-specific part around the model call: the weights licence pin (only the allow-listed checkpoint
file runs; anything else, including a symlink that resolves to another file, is refused before any
work starts), that the installed Foundry version and the checkpoint actually used are recorded and that
the version is read from the executable's OWN environment, which entity comes first in the input JSON
(that fixes the PAE order), that the target MSA is attached to the target chain and verified through
RF3's own parser (a chain left without an MSA is silent in RF3), that the binder never gets one, the
exact ``rf3 fold`` command line (early stopping off, otherwise a low-confidence design writes no
structure), how the top sample and its files are located, and that PAE / pLDDT are read from the right
files and refused when they do not line up with the sequences. The generic driver contract is tested in
test_second_engine_driver.py.
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

_SCRIPT = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts" / "refold_rf3.py"
TARGET = "ACDEFGHIKL"  # 10 residues
BINDER_A = "MKVLAAGW"  # 8 residues
BINDER_B = "GGSSPPTT"  # 8 residues
NT, NB = len(TARGET), len(BINDER_A)
CKPT = "rf3_foundry_01_24_latest_remapped.ckpt"
EXE = "/opt/rf3env/bin/rf3"
ENV_PYTHON = "/opt/rf3env/bin/python"

# One distinct constant per block of the native, TARGET-FIRST matrix.
TT, TB, BT, BB = 2.0, 25.0, 5.0, 1.0


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("_refold_rf3_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def ckpt_dir(tmp_path):
    d = tmp_path / "ckpts"
    d.mkdir()
    (d / CKPT).write_bytes(b"weights")
    return d


@pytest.fixture(autouse=True)
def _isolated_foundry_env(monkeypatch, tmp_path):
    """No ambient checkpoint dirs / home: the tests decide where checkpoints may be found."""
    monkeypatch.delenv("FOUNDRY_CHECKPOINT_DIRS", raising=False)
    monkeypatch.delenv("FOUNDRY_CHECKPOINTS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def native_pae(nt: int = NT, nb: int = NB) -> np.ndarray:
    """RF3's native order: components in input order, target (A) first, binder (B) second."""
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
    }


@pytest.fixture()
def fasta(tmp_path):
    path = tmp_path / "seqs.fasta"
    path.write_text(f">d1 source=x\n{BINDER_A}\n>d2 source=y\n{BINDER_B}\n")
    return path


@pytest.fixture()
def stub_env(mod, monkeypatch):
    """The executable lookup and the version probe stubbed, as they are when nothing is installed."""
    monkeypatch.setattr(mod, "_rf3_executable", lambda: EXE)
    monkeypatch.setattr(mod, "_foundry_version", lambda exe: "rc-foundry 0.2.0")


def run_main(mod, fasta, tmp_path, *extra, model_dir=None):
    out_csv = tmp_path / "rf3.csv"
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
        *(["--model-dir", str(model_dir)] if model_dir else []),
        *extra,
    ]
    return mod.main(argv), out_csv


def read_rows(path: Path) -> list[dict]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


# --- the licence pin ----------------------------------------------------------------------


def test_the_allow_list_is_exactly_the_one_recorded_checkpoint(mod):
    assert mod.DEFAULT_CHECKPOINT == CKPT
    # Evaluator/docs/second_engine_licences.md (RF3): the sentence covers "model weights referenced for
    # download in the README"; the only file both the README and the registry's default name is this one.
    assert tuple(mod.LICENSED_CHECKPOINTS) == (CKPT,)


@pytest.mark.parametrize(
    "name",
    [
        "rf3_foundry_01_24_preprint_remapped.ckpt",  # registry's other names: not the model under test
        "rf3_foundry_09_21_preprint_remapped.ckpt",
        "rf3_foundry_01_24_latest.ckpt",  # the pre-remap name v0.1.9's README/config still carry
        "rf3_foundry_01_24_preprint.ckpt",
        "rf3_foundry_09_21_preprint.ckpt",
        "rf3_latest.ckpt",
        "rf3",  # a registry name: the registry would pick the file, we will not
        "RF3_FOUNDRY_01_24_LATEST_REMAPPED.CKPT",  # exact match only
        "rf3_foundry_01_24_latest_remapped.ckpt.bak",
        "rfd3_latest.ckpt",
        "",
    ],
)
def test_any_checkpoint_not_on_the_allow_list_is_refused_before_anything_runs(
    mod, fasta, tmp_path, monkeypatch, capsys, ckpt_dir, name
):
    (ckpt_dir / name if name else ckpt_dir / "x").write_bytes(b"w")  # present on disk: still refused
    called = []
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: called.append(kw))
    code, out_csv = run_main(mod, fasta, tmp_path, "--checkpoint", name, model_dir=ckpt_dir)
    assert code != 0
    assert not called
    assert not out_csv.exists()  # no row, blank or otherwise, was written
    err = capsys.readouterr().err
    assert CKPT in err  # what is allowed is named
    assert "licence" in err.lower()


def test_a_path_whose_file_name_is_not_licensed_is_refused_even_if_the_directory_looks_right(mod, tmp_path):
    other = tmp_path / "rf3_foundry_01_24_latest_remapped" / "model.ckpt"
    other.parent.mkdir()
    other.write_bytes(b"w")
    with pytest.raises(mod.UnlicensedCheckpointError):
        mod.resolve_checkpoint(str(other), None)


def test_a_symlink_with_the_licensed_name_that_points_at_another_file_is_refused(mod, tmp_path):
    real = tmp_path / "rf3_foundry_09_21_preprint_remapped.ckpt"
    real.write_bytes(b"w")
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    (link_dir / CKPT).symlink_to(real)
    with pytest.raises(mod.UnlicensedCheckpointError):
        mod.resolve_checkpoint(CKPT, link_dir)


def test_the_model_seam_refuses_too_so_a_direct_call_cannot_bypass_configure(mod, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess must not start for an unlicensed checkpoint")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    monkeypatch.setattr(mod, "_rf3_executable", lambda: EXE)
    with pytest.raises(mod.UnlicensedCheckpointError):
        mod._predict_one(
            query_id="q1",
            binder_seq=BINDER_A,
            target_seq=TARGET,
            target_msa_path=None,
            work_dir=tmp_path / "w",
            checkpoint=tmp_path / "rf3_latest.ckpt",
            num_steps=200,
            num_seeds=1,
            num_samples=1,
        )


def test_default_run_resolves_the_default_checkpoint_and_records_it_and_the_version(
    mod, fasta, tmp_path, monkeypatch, stub_env, ckpt_dir
):
    seen = []

    def predict(**kw):
        seen.append(kw["checkpoint"])
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    code, _ = run_main(mod, fasta, tmp_path, model_dir=ckpt_dir)
    assert code == 0
    assert set(seen) == {(ckpt_dir / CKPT).resolve()}  # the file actually on disk, absolute
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["engine"] == "rf3"
    assert info["weights_id"] == CKPT
    assert info["engine_version"] == "rc-foundry 0.2.0"
    assert info["seeds"] == [101]


def test_run_info_settings_follow_the_values_that_reach_the_command_line(
    mod, fasta, tmp_path, monkeypatch, stub_env, ckpt_dir
):
    """The non-default settings are tied to the result: change them and the sidecar changes with the command."""
    captured = _capture_run(mod, monkeypatch)

    def settings_for(sub: str, *extra: str) -> tuple[dict, dict]:
        out = tmp_path / sub
        out.mkdir()
        argv = ["--sequences", str(fasta), "--target-seq", TARGET, "--output", str(out / "o.csv")]
        argv += ["--output-dir", str(out / "out"), "--no-msa", "--model-dir", str(ckpt_dir), *extra]
        assert mod.main(argv) == 0
        info = json.loads((out / "out" / "refold_run_info.json").read_text())
        return info["settings"], _overrides(captured["folds"][-1][0])

    settings, cmd = settings_for("default")
    assert settings == {
        "num_steps": 200,
        "n_recycles": 10,
        "early_stopping": "off",
        "diffusion_batch_size": 5,
        "shipped_default_num_steps": 50,
    }
    assert str(settings["num_steps"]) == cmd["num_steps"] == "200"
    assert str(settings["n_recycles"]) == cmd["n_recycles"]
    assert str(settings["diffusion_batch_size"]) == cmd["diffusion_batch_size"]
    assert float(cmd["early_stopping_plddt_threshold"]) == 0.0

    settings, cmd = settings_for("shipped", "--num-steps", "50", "--num-samples", "3")
    assert settings["num_steps"] == 50 and cmd["num_steps"] == "50"  # --num-steps 50 is RF3's shipped default
    assert settings["diffusion_batch_size"] == 3 and cmd["diffusion_batch_size"] == "3"


def test_the_checkpoint_is_searched_where_foundry_itself_looks(mod, tmp_path, monkeypatch, ckpt_dir):
    other = tmp_path / "empty"
    other.mkdir()
    monkeypatch.setenv("FOUNDRY_CHECKPOINT_DIRS", f"{other}:{ckpt_dir}")  # colon separated, in order
    assert mod.resolve_checkpoint(CKPT, None) == (ckpt_dir / CKPT).resolve()
    monkeypatch.delenv("FOUNDRY_CHECKPOINT_DIRS")
    home_dir = tmp_path / "home" / ".foundry" / "checkpoints"
    home_dir.mkdir(parents=True)
    (home_dir / CKPT).write_bytes(b"w")
    assert mod.resolve_checkpoint(CKPT, None) == (home_dir / CKPT).resolve()


def test_a_missing_checkpoint_is_an_error_that_says_where_it_looked_and_does_not_download(mod, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(mod.CheckpointNotFoundError) as exc:
        mod.resolve_checkpoint(CKPT, empty)
    assert str(empty) in str(exc.value) and CKPT in str(exc.value)


def test_a_missing_checkpoint_stops_the_cli_before_any_work(mod, fasta, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: pytest.fail("must not run"))
    code, out_csv = run_main(mod, fasta, tmp_path, model_dir=tmp_path)
    assert code != 0 and not out_csv.exists()
    assert CKPT in capsys.readouterr().err


# --- the version is read from the executable's own environment -----------------------------


def test_env_python_is_the_interpreter_beside_the_executable_not_the_scripts_own(mod):
    import sys

    assert mod._env_python(EXE) == ENV_PYTHON
    assert mod._env_python(EXE) != sys.executable


def _version_run(out: str, rc: int = 0, err: str = ""):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, rc, out, err)

    return seen, fake_run


def test_foundry_version_is_asked_of_the_executables_python(mod, monkeypatch):
    payload = {"version": "0.2.0", "direct_url": None}
    seen, fake_run = _version_run(f"noise from atomworks\nRF3_FOUNDRY_DIST={json.dumps(payload)}\n")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._foundry_version(EXE) == "rc-foundry 0.2.0"
    assert seen["cmd"][0] == ENV_PYTHON
    assert "-I" in seen["cmd"]
    assert "rc-foundry" in " ".join(seen["cmd"])
    assert seen["kw"]["text"] is True


def test_foundry_version_names_the_git_commit_of_a_vcs_install(mod, monkeypatch):
    direct = json.dumps(
        {"url": "https://github.com/RosettaCommons/foundry", "vcs_info": {"vcs": "git", "commit_id": "69d5f73"}}
    )
    payload = {"version": "0.2.1.dev23", "direct_url": direct}
    _, fake_run = _version_run(f"RF3_FOUNDRY_DIST={json.dumps(payload)}\n")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._foundry_version(EXE) == "rc-foundry 0.2.1.dev23 (git 69d5f73)"


@pytest.mark.parametrize("out,rc", [("", 0), ("no marker here\n", 0), ("RF3_FOUNDRY_DIST=\n", 0), ("", 1)])
def test_an_unreadable_version_is_an_error_not_unknown(mod, monkeypatch, out, rc):
    _, fake_run = _version_run(out, rc, "ModuleNotFoundError")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(mod.EngineError):
        mod._foundry_version(EXE)


# --- chain order --------------------------------------------------------------------------


def test_saved_pae_is_reblocked_from_target_first_to_binder_first(
    mod, fasta, tmp_path, monkeypatch, stub_env, ckpt_dir
):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    code, out_csv = run_main(mod, fasta, tmp_path, model_dir=ckpt_dir)
    assert code == 0
    rows = read_rows(out_csv)
    pae = np.load(rows[0]["pae_file"])
    assert Path(rows[0]["pae_file"]).name == "d1_rf3_pae.npy"
    assert pae.shape == (NB + NT, NB + NT)
    # [binder | target]: BB, BT / TB, TT -- blocks moved whole, none transposed.
    assert np.all(pae[:NB, :NB] == BB)
    assert np.all(pae[:NB, NB:] == BT)
    assert np.all(pae[NB:, :NB] == TB)
    assert np.all(pae[NB:, NB:] == TT)
    assert mod.NATIVE_PAE_ORDER == "target_binder"
    assert mod.RF3Adapter.native_pae_order == "target_binder"


def test_input_lists_the_target_first_with_chain_ids_a_and_b_as_explicit_proteins(mod, tmp_path):
    doc = mod.build_input("q1", BINDER_A, TARGET, target_msa_path=None)
    assert isinstance(doc, list) and len(doc) == 1  # the multi-example JSON form
    assert doc[0]["name"] == "q1"
    comps = doc[0]["components"]
    assert [(c["chain_id"], c["seq"]) for c in comps] == [("A", TARGET), ("B", BINDER_A)]
    # chain type is explicit: RF3 otherwise infers it from the letters, and an A/C/G/T-only
    # binder would be read as DNA.
    assert all(c["chain_type"] == "polypeptide(L)" for c in comps)


# --- MSA wiring ---------------------------------------------------------------------------


def test_without_a_target_msa_no_component_has_an_msa_path(mod):
    doc = mod.build_input("q1", BINDER_A, TARGET, target_msa_path=None)
    assert all("msa_path" not in c for c in doc[0]["components"])


def test_with_a_target_msa_only_the_target_carries_the_absolute_a3m_path_and_the_binder_has_none(mod, tmp_path):
    a3m = tmp_path / "shared" / "target.a3m"
    a3m.parent.mkdir()
    a3m.write_text(f">query\n{TARGET}\n>hit\n{TARGET}\n")
    doc = mod.build_input("q1", BINDER_A, TARGET, target_msa_path=a3m)
    target, binder = doc[0]["components"]
    assert target["msa_path"] == str(a3m.absolute()) and Path(target["msa_path"]).is_absolute()
    # No MSA for the binder means no msa_path at all (RF3's convention), not a one-row file.
    assert "msa_path" not in binder


def test_target_msa_a3m_text_reaches_the_model_call_as_a_file(mod, fasta, tmp_path, monkeypatch, stub_env, ckpt_dir):
    a3m = f">query\n{TARGET}\n>hit\n{TARGET}\n"
    monkeypatch.setattr(target_msa_mod, "_query_colabfold", lambda seq, *a, **k: a3m)
    seen = {}

    def predict(**kw):
        seen["text"] = Path(kw["target_msa_path"]).read_text()
        seen["name"] = Path(kw["target_msa_path"]).name
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    code = mod.main(
        [
            "--sequences",
            str(fasta),
            "--target-seq",
            TARGET,
            "--output",
            str(tmp_path / "rf3.csv"),
            "--output-dir",
            str(tmp_path / "out"),
            "--msa-cache-dir",
            str(tmp_path / "cache"),
            "--model-dir",
            str(ckpt_dir),
        ]
    )
    assert code == 0
    assert seen["text"] == a3m
    assert seen["name"] == "target.a3m"  # RF3 picks the parser from the extension
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["target_msa_mode"] == "fetched"


def _wiring_run(mapping: dict, rc: int = 0, err: str = ""):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, rc, f"warn\nRF3_MSA_WIRING={json.dumps(mapping)}\n", err)

    return seen, fake_run


def test_the_wiring_check_runs_rf3s_own_input_parser_in_the_executables_env(mod, tmp_path, monkeypatch):
    a3m = tmp_path / "target.a3m"
    a3m.write_text(">q\nA\n")
    input_json = tmp_path / "input.json"
    input_json.write_text("[]")
    seen, fake_run = _wiring_run({"A": str(a3m), "B": None})
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    mod._check_msa_wiring(EXE, input_json, a3m)  # no exception: A carries the file, B nothing
    assert seen["cmd"][0] == ENV_PYTHON and "-I" in seen["cmd"]
    assert seen["cmd"][-1] == str(input_json)
    assert "from_json_dict" in " ".join(seen["cmd"])


@pytest.mark.parametrize(
    "mapping",
    [
        {"A": None, "B": None},  # target MSA silently not attached: RF3 would fold it single-sequence
        {"A": "/elsewhere/other.a3m", "B": None},  # some other file
        {"A": "TARGET", "B": "TARGET"},  # binder got an MSA
        {"B": None},  # chain A missing from chain_info
    ],
)
def test_a_wiring_that_is_not_target_msa_plus_binder_without_one_fails_the_design(mod, tmp_path, monkeypatch, mapping):
    a3m = tmp_path / "target.a3m"
    a3m.write_text(">q\nA\n")
    mapping = {k: (str(a3m) if v == "TARGET" else v) for k, v in mapping.items()}
    _, fake_run = _wiring_run(mapping)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(mod.EngineError, match="MSA"):
        mod._check_msa_wiring(EXE, tmp_path / "input.json", a3m)


def test_a_wiring_check_that_cannot_run_fails_the_design_with_its_stderr_as_text(mod, tmp_path, monkeypatch):
    _, fake_run = _wiring_run({}, rc=1, err="ImportError: rf3")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(mod.EngineError) as exc:
        mod._check_msa_wiring(EXE, tmp_path / "input.json", tmp_path / "target.a3m")
    assert isinstance(exc.value.stderr, str) and "ImportError: rf3" in exc.value.stderr


def test_a_wiring_check_with_no_marker_line_is_a_failure(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "nothing\n", ""))
    with pytest.raises(mod.EngineError, match="MSA"):
        mod._check_msa_wiring(EXE, tmp_path / "input.json", tmp_path / "target.a3m")


# --- the command line ---------------------------------------------------------------------


def _capture_run(mod, monkeypatch, *, returncode=0, stdout="", stderr="", wiring_ok=True, write_samples=True):
    """Record every ``rf3 fold`` invocation; the wiring probe (the env's python) answers correctly."""
    captured = {"folds": [], "probes": []}

    def fake_run(cmd, **kw):
        if cmd[0] == ENV_PYTHON:
            captured["probes"].append((cmd, kw))
            a3m = captured.get("a3m")
            ok = {"A": a3m, "B": None} if wiring_ok else {"A": None, "B": None}
            return subprocess.CompletedProcess(cmd, 0, f"RF3_MSA_WIRING={json.dumps(ok)}\n", "")
        captured["folds"].append((cmd, kw))
        if write_samples and returncode == 0:
            o = _overrides(cmd)
            name = json.loads(Path(o["inputs"]).read_text())[0]["name"]
            write_sample(Path(o["out_dir"]), name, int(o["seed"]), 0, 0.8)
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_rf3_executable", lambda: EXE)
    return captured


def _call(mod, tmp_path, **over):
    kw = dict(
        query_id="q1",
        binder_seq=BINDER_A,
        target_seq=TARGET,
        target_msa_path=None,
        work_dir=tmp_path / "w",
        checkpoint=tmp_path / "ck" / CKPT,
        num_steps=200,
        num_seeds=1,
        num_samples=5,
    )
    kw.update(over)
    return mod._predict_one(**kw)


def _overrides(cmd) -> dict[str, str]:
    assert cmd[1] == "fold"
    out = {}
    for tok in cmd[2:]:
        key, _, val = tok.partition("=")
        out[key] = val.strip("'") if val.startswith("'") else val
    return out


def test_command_pins_checkpoint_steps_samples_seed_and_turns_early_stopping_off(mod, tmp_path, monkeypatch):
    captured = _capture_run(mod, monkeypatch)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {"loaded": True})
    assert _call(mod, tmp_path) == {"loaded": True}
    assert len(captured["folds"]) == 1 and captured["probes"] == []  # no target MSA: nothing to verify
    cmd, kw = captured["folds"][0]
    assert cmd[0] == EXE
    o = _overrides(cmd)
    assert o["ckpt_path"] == str(tmp_path / "ck" / CKPT)  # an absolute path, never a registry name
    assert o["seed"] == "101"
    assert o["diffusion_batch_size"] == "5"
    assert o["num_steps"] == "200"
    assert o["n_recycles"] == "10"
    # Without this a design whose first-recycle pLDDT is under 0.5 is skipped: exit 0, no structure.
    assert float(o["early_stopping_plddt_threshold"]) == 0.0
    assert o["compress_outputs"] == "false"  # plain .cif, read by a stdlib parser
    assert o["dump_predictions"] == "true"  # per-sample files are the only place every sample's PAE is
    assert o["annotate_b_factor_with_plddt"] == "true"  # per-residue pLDDT is read from the CIF B-factors
    # Nothing is passed that one of the three Foundry versions does not know (Hydra rejects unknown keys).
    assert set(o) == {
        "inputs",
        "out_dir",
        "ckpt_path",
        "seed",
        "diffusion_batch_size",
        "num_steps",
        "n_recycles",
        "early_stopping_plddt_threshold",
        "compress_outputs",
        "dump_predictions",
        "annotate_b_factor_with_plddt",
    }
    # The input it was pointed at is the one build_input wrote.
    doc = json.loads(Path(o["inputs"]).read_text())
    assert doc[0]["name"] == "q1"
    assert Path(o["out_dir"]).parent == tmp_path / "w"
    # Text capture of both streams, so a failure's stderr is a str the driver can tail.
    assert kw["capture_output"] is True and kw["text"] is True
    assert kw["cwd"] == str(tmp_path / "w")  # stray files stay inside the design's work dir


def test_command_with_a_target_msa_verifies_the_wiring_first_and_one_subprocess_per_seed(mod, tmp_path, monkeypatch):
    a3m = tmp_path / "t" / "target.a3m"
    a3m.parent.mkdir()
    a3m.write_text(f">q\n{TARGET}\n")
    captured = _capture_run(mod, monkeypatch)
    captured["a3m"] = str(a3m.absolute())
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    _call(mod, tmp_path, target_msa_path=a3m, num_seeds=3, num_samples=2, num_steps=50)
    assert len(captured["probes"]) == 1
    seeds = [_overrides(cmd)["seed"] for cmd, _ in captured["folds"]]
    assert seeds == ["101", "102", "103"]
    outs = [_overrides(cmd)["out_dir"] for cmd, _ in captured["folds"]]
    assert len(set(outs)) == 3  # a seed never overwrites another seed's files
    assert all(_overrides(cmd)["diffusion_batch_size"] == "2" for cmd, _ in captured["folds"])
    assert all(_overrides(cmd)["num_steps"] == "50" for cmd, _ in captured["folds"])
    doc = json.loads(Path(_overrides(captured["folds"][0][0])["inputs"]).read_text())
    assert doc[0]["components"][0]["msa_path"] == str(a3m.absolute())


def test_a_target_msa_that_rf3_did_not_attach_stops_the_design_before_any_fold(mod, tmp_path, monkeypatch):
    a3m = tmp_path / "target.a3m"
    a3m.write_text(f">q\n{TARGET}\n")
    captured = _capture_run(mod, monkeypatch, wiring_ok=False)
    with pytest.raises(mod.EngineError, match="MSA"):
        _call(mod, tmp_path, target_msa_path=a3m)
    assert captured["folds"] == []


def test_the_subprocess_env_cannot_hand_the_binder_an_msa_and_keeps_the_allocator_friendly(mod, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_MSA_DIRS", "/some/msa/library")  # RF3 would look the binder up there by hash
    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF", raising=False)
    captured = _capture_run(mod, monkeypatch)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    _call(mod, tmp_path)
    env = captured["folds"][0][1]["env"]
    assert "LOCAL_MSA_DIRS" not in env
    assert env["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True"


def test_an_operator_set_allocator_config_is_left_alone(mod, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:128")
    captured = _capture_run(mod, monkeypatch)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    _call(mod, tmp_path)
    assert captured["folds"][0][1]["env"]["PYTORCH_CUDA_ALLOC_CONF"] == "max_split_size_mb:128"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("/tmp/work/q1/input.json", "/tmp/work/q1/input.json"),
        ("/tmp/my work/input.json", "'/tmp/my work/input.json'"),
        ("/tmp/a=b,c/[x].json", "'/tmp/a=b,c/[x].json'"),
        ("/tmp/it's/x", "'/tmp/it\\'s/x'"),
    ],
)
def test_hydra_values_with_special_characters_are_quoted(mod, value, expected):
    assert mod._hydra_value(value) == expected


def test_a_work_dir_with_a_space_still_yields_a_quoted_override(mod, tmp_path, monkeypatch):
    captured = _capture_run(mod, monkeypatch)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    _call(mod, tmp_path, work_dir=tmp_path / "my work")
    assert "my work" in _overrides(captured["folds"][0][0])["inputs"]
    assert captured["folds"][0][0][2].startswith("inputs='")


def test_nonzero_exit_is_a_failure_and_its_stderr_is_text(mod, tmp_path, monkeypatch):
    _capture_run(mod, monkeypatch, returncode=1, stderr="boom: cuda")
    with pytest.raises(mod.EngineError, match="exited with code 1") as exc:
        _call(mod, tmp_path)
    assert isinstance(exc.value.stderr, str) and "boom: cuda" in exc.value.stderr


def test_the_project_root_crash_of_rc_foundry_0_1_9_is_named_not_left_as_a_bare_traceback(mod, tmp_path, monkeypatch):
    _capture_run(
        mod,
        monkeypatch,
        returncode=1,
        stderr="FileNotFoundError: Project root directory not found. Indicators: ['.project-root']",
    )
    with pytest.raises(mod.EngineError) as exc:
        _call(mod, tmp_path)
    assert "0.2.0" in str(exc.value)  # the first release that no longer needs a .project-root marker


def test_exit_zero_with_no_output_is_a_failed_design_and_carries_both_streams_and_the_early_stop_note(
    mod, tmp_path, monkeypatch
):
    def fake_run(cmd, **kw):
        out = Path(_overrides(cmd)["out_dir"]) / "q1"
        out.mkdir(parents=True)
        # What RF3 writes when it skips a prediction: no structure, a one-row ranking file.
        (out / "q1_ranking_scores.csv").write_text("early_stopped,mean_plddt\nTrue,0.31\n")
        return subprocess.CompletedProcess(cmd, 0, "stdout line", "WARNING Early stopping triggered for q1")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_rf3_executable", lambda: EXE)
    with pytest.raises(mod.EngineError, match="no prediction") as exc:
        _call(mod, tmp_path)
    assert isinstance(exc.value.stderr, str)
    assert "Early stopping triggered" in exc.value.stderr and "stdout line" in exc.value.stderr
    assert "early_stopped" in exc.value.stderr  # the ranking file's content is attached


def test_a_seed_that_wrote_nothing_fails_the_design_even_if_another_seed_wrote_samples(mod, tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if _overrides(cmd)["seed"] == "101":
            write_sample(Path(_overrides(cmd)["out_dir"]), "q1", 101, 0, 0.9)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_rf3_executable", lambda: EXE)
    with pytest.raises(mod.EngineError, match="seed 102"):
        _call(mod, tmp_path, num_seeds=2)


def test_a_stale_work_dir_is_cleared_before_the_run(mod, tmp_path, monkeypatch):
    write_sample(tmp_path / "w" / "seed_101", "q1", 101, 0, 0.99)  # an earlier, partly failed attempt
    _capture_run(mod, monkeypatch, write_samples=False)
    with pytest.raises(mod.EngineError, match="no prediction"):
        _call(mod, tmp_path)  # the leftover sample must not be picked up


def test_the_whole_path_runs_through_the_cli_with_a_stubbed_subprocess(
    mod, fasta, tmp_path, monkeypatch, stub_env, ckpt_dir
):
    """No seam stubbed: command, files on disk, parsing, driver. Only the subprocess answers."""

    def fake_run(cmd, **kw):
        o = _overrides(cmd)
        name = json.loads(Path(o["inputs"]).read_text())[0]["name"]
        write_sample(Path(o["out_dir"]), name, int(o["seed"]), 0, 0.8, pae=native_pae().tolist())
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    code, out_csv = run_main(mod, fasta, tmp_path, model_dir=ckpt_dir)
    assert code == 0
    rows = read_rows(out_csv)
    assert [r["iptm"] for r in rows] == ["0.5", "0.5"]
    assert rows[0]["plddt_binder_mean"] == "0.8" and rows[0]["plddt_target_mean"] == "0.9"
    pae = np.load(rows[0]["pae_file"])
    assert np.all(pae[:NB, NB:] == BT)  # binder rows, target columns


# --- output files: layout, top sample, PAE, pLDDT ------------------------------------------

_COLUMNS = [
    "group_PDB",
    "type_symbol",
    "label_atom_id",
    "label_alt_id",
    "label_comp_id",
    "label_asym_id",
    "label_entity_id",
    "label_seq_id",
    "pdbx_PDB_ins_code",
    "auth_seq_id",
    "auth_comp_id",
    "auth_asym_id",
    "auth_atom_id",
    "id",
    "B_iso_or_equiv",
    "occupancy",
    "pdbx_formal_charge",
    "Cartn_x",
    "Cartn_y",
    "Cartn_z",
    "pdbx_PDB_model_num",
]


def mini_cif(*, target_b=0.9, binder_b=0.8, nt: int = NT, nb: int = NB, drop_ca: tuple[str, int] | None = None):
    """An atomworks-shaped mmCIF: a ``_chem_comp_bond`` loop first, then ``_atom_site``; B-factor = pLDDT (0-1)."""
    lines = [
        "data_stub",
        "#",
        "loop_",
        "_chem_comp_bond.comp_id ",
        "_chem_comp_bond.atom_id_1 ",
        "_chem_comp_bond.atom_id_2 ",
        "ALA N CA",
        "#",
        "loop_",
        *(f"_atom_site.{c} " for c in _COLUMNS),
    ]
    serial = 0
    for chain, n, b in (("A", nt, target_b), ("B", nb, binder_b)):
        for res in range(1, n + 1):
            for atom in ("N", "CA", "C"):
                if drop_ca == (chain, res) and atom == "CA":
                    continue
                serial += 1
                lines.append(
                    f"ATOM {atom[0]} {atom} . ALA {chain} 0 {res} . {res} ALA {chain} {atom} {serial} {b!r} 1.0 ? "
                    f"1.0 2.0 3.0 1"
                )
    lines.append("#")
    return "\n".join(lines) + "\n"


def write_sample(
    out_dir: Path,
    name: str,
    seed: int,
    sample: int,
    score: float,
    pae_value: float = 1.0,
    *,
    nt: int = NT,
    nb: int = NB,
    cif: str | None = None,
    token_chains=None,
    pae=None,
    summary_extra: dict | None = None,
):
    """One sample the way RF3's ``RF3Output.dump`` lays it out under ``<out_dir>/<name>/``."""
    d = out_dir / name / f"seed-{seed}_sample-{sample}"
    d.mkdir(parents=True, exist_ok=True)
    stem = f"{name}_seed-{seed}_sample-{sample}"
    (d / f"{stem}_model.cif").write_text(mini_cif(nt=nt, nb=nb) if cif is None else cif)
    summary = {
        "chain_pair_pae": [[None, 3.1], [2.9, None]],
        "overall_plddt": 0.85,
        "ptm": 0.6,
        "iptm": 0.5,
        "has_clash": False,
        "ranking_score": score,
    }
    summary.update(summary_extra or {})
    (d / f"{stem}_summary_confidences.json").write_text(json.dumps(summary))
    n = nt + nb
    confidences = {
        "atom_chain_ids": ["A"] * 3 + ["B"] * 3,
        "atom_plddts": [0.9] * 6,
        "pae": ([[pae_value] * n] * n) if pae is None else pae,
        "token_chain_ids": (["A_1"] * nt + ["B_1"] * nb) if token_chains is None else token_chains,
        "token_res_ids": list(range(n)),
    }
    (d / f"{stem}_confidences.json").write_text(json.dumps(confidences))
    return d


def test_top_sample_is_the_highest_ranking_score_across_seeds_and_samples(mod, tmp_path):
    write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.60, 3.0)
    write_sample(tmp_path / "seed_101", "q1", 101, 1, 0.40, 1.0)
    write_sample(tmp_path / "seed_102", "q1", 102, 3, 0.90, 2.0)  # the winner: another seed's sample 3
    write_sample(tmp_path / "seed_102", "q1", 102, 4, 0.30, 4.0)
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    assert top["seed"] == 102
    assert top["cif"].name == "q1_seed-102_sample-3_model.cif"
    assert top["summary"]["sample_ranking_score"] == pytest.approx(0.90)
    assert top["summary"]["iptm"] == pytest.approx(0.5) and top["summary"]["ptm"] == pytest.approx(0.6)
    assert float(top["pae"][0, 0]) == 2.0  # the PAE of THAT sample, not another's
    assert top["pae"].shape == (NT + NB, NT + NB)
    assert len(top["plddt_target"]) == NT and len(top["plddt_binder"]) == NB


def test_the_top_level_copies_rf3_also_writes_are_not_candidates(mod, tmp_path):
    # RF3 copies the best sample's files up to <name>/<name>_*.{json,cif}; reading those as well would
    # double count, and with several seeds the top-level copy belongs to one seed only.
    d = write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.30, 5.0)
    top_level = d.parent
    (top_level / "q1_summary_confidences.json").write_text(
        json.dumps({"ranking_score": 99.0, "iptm": 0.99, "ptm": 0.9})
    )
    (top_level / "q1_confidences.json").write_text("{}")
    (top_level / "q1_model.cif").write_text("data_decoy\n")
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    assert top["summary"]["sample_ranking_score"] == pytest.approx(0.30) and float(top["pae"][0, 0]) == 5.0


def test_top_sample_is_none_when_nothing_was_written(mod, tmp_path):
    assert mod._load_top_sample(tmp_path, "q1", NT, NB) is None


def test_non_finite_ranking_scores_are_skipped_when_picking_the_top_sample(mod, tmp_path):
    write_sample(tmp_path / "seed_101", "q1", 101, 0, float("nan"), 1.0)
    write_sample(tmp_path / "seed_101", "q1", 101, 1, 0.30, 2.0)
    write_sample(tmp_path / "seed_102", "q1", 102, 0, float("inf"), 3.0)
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    assert top["cif"].name == "q1_seed-101_sample-1_model.cif"
    write_sample(tmp_path / "seed_101", "q2", 101, 0, float("nan"), 1.0)
    assert mod._load_top_sample(tmp_path, "q2", NT, NB) is None


def test_a_sample_without_iptm_or_ptm_is_not_a_candidate(mod, tmp_path):
    # RF3 writes ptm / iptm / ranking_score only when its metrics ran; a summary without them is no score.
    d = write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.99)
    summary = json.loads((d / "q1_seed-101_sample-0_summary_confidences.json").read_text())
    del summary["iptm"]
    (d / "q1_seed-101_sample-0_summary_confidences.json").write_text(json.dumps(summary))
    write_sample(tmp_path / "seed_101", "q1", 101, 1, 0.20, 7.0)
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    assert top["cif"].name == "q1_seed-101_sample-1_model.cif" and float(top["pae"][0, 0]) == 7.0


def test_a_sample_without_its_cif_or_confidences_file_is_not_a_candidate(mod, tmp_path):
    d = write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.99)
    (d / "q1_seed-101_sample-0_confidences.json").unlink()  # no PAE for the best-scoring sample
    d2 = write_sample(tmp_path / "seed_101", "q1", 101, 1, 0.80)
    (d2 / "q1_seed-101_sample-1_model.cif").unlink()
    write_sample(tmp_path / "seed_101", "q1", 101, 2, 0.20, 7.0)
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    assert top["cif"].name == "q1_seed-101_sample-2_model.cif" and float(top["pae"][0, 0]) == 7.0


def test_pae_is_the_full_token_matrix_of_the_confidences_file_in_target_first_order(mod, tmp_path):
    write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.5, pae=native_pae().tolist())
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    np.testing.assert_array_equal(top["pae"], native_pae())  # untouched here; the driver re-blocks it


def test_a_binder_first_token_order_is_refused_not_silently_mis_blocked(mod, tmp_path):
    # Same sizes, so the driver's size check could not see this: the tokens say the binder is first.
    write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.5, token_chains=["B_1"] * NB + ["A_1"] * NT)
    with pytest.raises(ValueError, match="target"):
        mod._load_top_sample(tmp_path, "q1", NT, NB)


def test_chain_labels_that_are_not_a_then_b_are_refused(mod, tmp_path):
    write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.5, token_chains=["A_1"] * NT + ["C_1"] * NB)
    with pytest.raises(ValueError, match="target"):
        mod._load_top_sample(tmp_path, "q1", NT, NB)
    # a block that is not one chain
    write_sample(tmp_path / "seed_102", "q2", 102, 0, 0.5, token_chains=["A_1"] * (NT - 1) + ["B_1"] * (NB + 1))
    with pytest.raises(ValueError, match="target"):
        mod._load_top_sample(tmp_path, "q2", NT, NB)


def test_token_count_that_differs_from_the_residue_count_is_refused(mod, tmp_path):
    # e.g. a non-standard residue or a ligand token: residue-indexed blocks would be wrong.
    write_sample(
        tmp_path / "seed_101",
        "q1",
        101,
        0,
        0.5,
        token_chains=["A_1"] * NT + ["B_1"] * (NB + 1),
        pae=np.zeros((NT + NB + 1,) * 2).tolist(),
    )
    with pytest.raises(ValueError, match="token"):
        mod._load_top_sample(tmp_path, "q1", NT, NB)


def test_a_non_square_pae_is_refused(mod, tmp_path):
    write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.5, pae=np.zeros((NT + NB, NT + NB - 1)).tolist())
    with pytest.raises(ValueError, match="token"):
        mod._load_top_sample(tmp_path, "q1", NT, NB)


def test_a_missing_token_chain_ids_is_refused(mod, tmp_path):
    d = write_sample(tmp_path / "seed_101", "q1", 101, 0, 0.5)
    fp = d / "q1_seed-101_sample-0_confidences.json"
    conf = json.loads(fp.read_text())
    del conf["token_chain_ids"]
    fp.write_text(json.dumps(conf))
    with pytest.raises(ValueError, match="token_chain_ids"):
        mod._load_top_sample(tmp_path, "q1", NT, NB)


def test_per_residue_plddt_is_the_ca_b_factor_per_chain_rescaled_from_0_1_to_0_100(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(target_b=0.915, binder_b=0.6425))
    out = mod._ca_plddt_by_chain(cif, NT, NB)
    assert set(out) == {"A", "B"}
    np.testing.assert_allclose(out["A"], np.full(NT, 91.5))
    np.testing.assert_allclose(out["B"], np.full(NB, 64.25))


def test_a_plddt_on_the_0_100_scale_is_refused_not_divided_twice(mod, tmp_path):
    # If a Foundry version ever wrote 0-100, the driver's /100 would silently give 0.9 -> 0.009.
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(target_b=91.5, binder_b=64.25))
    with pytest.raises(ValueError, match="scale"):
        mod._ca_plddt_by_chain(cif, NT, NB)


def test_a_residue_without_a_ca_atom_fails_loudly(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(drop_ca=("B", 3)))
    with pytest.raises(ValueError, match="CA"):
        mod._ca_plddt_by_chain(cif, NT, NB)
    cif.write_text(mini_cif(drop_ca=("A", 1)))
    with pytest.raises(ValueError, match="CA"):
        mod._ca_plddt_by_chain(cif, NT, NB)


def test_a_chain_with_the_wrong_residue_count_fails_loudly(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(nb=NB + 2))
    with pytest.raises(ValueError, match="binder"):
        mod._ca_plddt_by_chain(cif, NT, NB)


def test_b_factors_that_are_all_zero_mean_no_plddt_was_written(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(target_b=0.0, binder_b=0.0))
    with pytest.raises(ValueError, match="pLDDT"):
        mod._ca_plddt_by_chain(cif, NT, NB)
    cif.write_text(mini_cif(target_b=float("nan"), binder_b=0.5))
    with pytest.raises(ValueError, match="pLDDT"):
        mod._ca_plddt_by_chain(cif, NT, NB)


def test_a_cif_without_an_atom_site_loop_or_chain_is_refused(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text("data_stub\n")
    with pytest.raises(ValueError, match="atom_site"):
        mod._ca_plddt_by_chain(cif, NT, NB)
    cif.write_text(mini_cif(nb=0))
    with pytest.raises(ValueError, match="binder"):
        mod._ca_plddt_by_chain(cif, NT, NB)
