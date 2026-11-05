"""refold_protenix_v1.py with the model call stubbed behind ``_predict_one``.

Protenix itself cannot run where these tests do. What they pin is the engine-specific part around
the model call: the licence pin (only the v1.x checkpoints on the allow-list run, ``protenix-v2``
and anything else is refused), which entity comes first in the input JSON (that fixes the PAE
order), that every protein chain carries an explicit MSA path (otherwise Protenix silently searches
an MSA server for ALL chains), the exact ``protenix pred`` command line, how the top sample and its
files are located, and that PAE / pLDDT are read from the right files and refused when they do not
line up with the sequences. The generic driver contract is tested in test_second_engine_driver.py.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
from binder_comparison.refolding import target_msa as target_msa_mod

_SCRIPT = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts" / "refold_protenix_v1.py"
TARGET = "ACDEFGHIKL"  # 10 residues
BINDER_A = "MKVLAAGW"  # 8 residues
BINDER_B = "GGSSPPTT"  # 8 residues
NT, NB = len(TARGET), len(BINDER_A)
MODEL = "protenix_base_default_v1.0.0"

# One distinct constant per block of the native, TARGET-FIRST matrix.
TT, TB, BT, BB = 2.0, 25.0, 5.0, 1.0


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("_refold_protenix_v1_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native_pae(nt: int = NT, nb: int = NB) -> np.ndarray:
    """Protenix's native order: entities in input order, target (A) first, binder (B) second."""
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


def run_main(mod, fasta, tmp_path, *extra):
    out_csv = tmp_path / "px.csv"
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


# --- the licence pin ----------------------------------------------------------------------


def test_default_model_is_the_v1_default_and_the_allow_list_is_exactly_the_recorded_names(mod):
    assert mod.DEFAULT_MODEL == MODEL
    # Names taken from Evaluator/docs/second_engine_licences.md (Protenix caveats); nothing else.
    assert tuple(mod.LICENSED_MODELS) == ("protenix_base_default_v1.0.0", "protenix_base_20250630_v1.0.0")
    assert mod.DEFAULT_MODEL in mod.LICENSED_MODELS


@pytest.mark.parametrize(
    "name",
    [
        "protenix-v2",
        "Protenix-v2",
        "protenix_v2",
        "protenix_base_default_v2.0.0",
        "protenix_base_default_v0.5.0",  # v0.x is not covered by the licence record either
        "protenix_mini_default_v0.5.0",
        "PROTENIX_BASE_DEFAULT_V1.0.0",  # exact match only
        " protenix_base_default_v1.0.0",
        "protenix_base_default_v1.0.0.pt",
        "/some/dir/protenix_base_default_v1.0.0",
        "",
    ],
)
def test_any_model_not_on_the_allow_list_is_refused_before_anything_runs(
    mod, fasta, tmp_path, monkeypatch, name, capsys
):
    called = []
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: called.append(kw))
    code, out_csv = run_main(mod, fasta, tmp_path, "--model-name", name)
    assert code != 0
    assert not called
    assert not out_csv.exists()  # no row, blank or otherwise, was written
    err = capsys.readouterr().err
    assert "proprietary" in err  # the reason is named, not just "unknown model"
    assert "protenix_base_default_v1.0.0" in err  # and so is what is allowed


def test_the_model_seam_refuses_too_so_a_direct_call_cannot_bypass_configure(mod, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess must not start for an unlicensed model")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    with pytest.raises(mod.UnlicensedModelError, match="protenix-v2"):
        mod._predict_one(
            query_id="q1",
            binder_seq=BINDER_A,
            target_seq=TARGET,
            target_msa_path=None,
            work_dir=tmp_path / "w",
            model_name="protenix-v2",
            model_dir=None,
            num_seeds=1,
            num_samples=1,
        )


def test_the_second_licensed_name_is_accepted_and_recorded_as_weights_id(mod, fasta, tmp_path, monkeypatch):
    seen = []

    def predict(**kw):
        seen.append(kw["model_name"])
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    code, _ = run_main(mod, fasta, tmp_path, "--model-name", "protenix_base_20250630_v1.0.0")
    assert code == 0
    assert set(seen) == {"protenix_base_20250630_v1.0.0"}
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["engine"] == "protenix"
    assert info["weights_id"] == "protenix_base_20250630_v1.0.0"
    assert "engine_version" in info


def test_default_run_uses_the_default_model_and_records_it(mod, fasta, tmp_path, monkeypatch):
    seen = []

    def predict(**kw):
        seen.append(kw["model_name"])
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    run_main(mod, fasta, tmp_path)
    assert set(seen) == {MODEL}
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["weights_id"] == MODEL
    assert info["seeds"] == [101]


# --- chain order --------------------------------------------------------------------------


def test_saved_pae_is_reblocked_from_target_first_to_binder_first(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    code, out_csv = run_main(mod, fasta, tmp_path)
    assert code == 0
    rows = read_rows(out_csv)
    pae = np.load(rows[0]["pae_file"])
    assert Path(rows[0]["pae_file"]).name == "d1_protenix_pae.npy"
    assert pae.shape == (NB + NT, NB + NT)
    # [binder | target]: BB, BT / TB, TT -- blocks moved whole, none transposed.
    assert np.all(pae[:NB, :NB] == BB)
    assert np.all(pae[:NB, NB:] == BT)
    assert np.all(pae[NB:, :NB] == TB)
    assert np.all(pae[NB:, NB:] == TT)
    assert mod.NATIVE_PAE_ORDER == "target_binder"
    assert mod.ProtenixAdapter.native_pae_order == "target_binder"


def test_input_lists_the_target_entity_first_with_chain_ids_a_and_b(mod, tmp_path):
    doc = mod.build_input("q1", BINDER_A, TARGET, msa_dir=tmp_path / "msa", target_msa_path=None)
    assert isinstance(doc, list) and len(doc) == 1  # Protenix wants a top-level list of jobs
    assert doc[0]["name"] == "q1"
    chains = [s["proteinChain"] for s in doc[0]["sequences"]]
    assert [(c["id"], c["sequence"], c["count"]) for c in chains] == [
        (["A"], TARGET, 1),
        (["B"], BINDER_A, 1),
    ]


# --- MSA wiring ---------------------------------------------------------------------------


def test_without_a_target_msa_no_chain_has_an_msa_path(mod, tmp_path):
    doc = mod.build_input("q1", BINDER_A, TARGET, msa_dir=tmp_path / "msa", target_msa_path=None)
    for seq in doc[0]["sequences"]:
        assert "unpairedMsaPath" not in seq["proteinChain"]
        assert "pairedMsaPath" not in seq["proteinChain"]


def test_with_a_target_msa_both_chains_carry_an_existing_unpaired_a3m(mod, tmp_path):
    target_a3m = tmp_path / "shared" / "non_pairing.a3m"
    target_a3m.parent.mkdir()
    target_a3m.write_text(f">query\n{TARGET}\n>hit\n{TARGET}\n")
    doc = mod.build_input("q1", BINDER_A, TARGET, msa_dir=tmp_path / "msa", target_msa_path=target_a3m)
    target_chain, binder_chain = (s["proteinChain"] for s in doc[0]["sequences"])
    assert target_chain["unpairedMsaPath"] == str(target_a3m)
    # The binder must ALSO have a path: with one chain lacking both paths Protenix searches an MSA server
    # for every chain and overwrites the paths. The binder's file holds only its own sequence (no MSA).
    binder_file = Path(binder_chain["unpairedMsaPath"])
    assert binder_file.is_file()
    assert binder_file.read_text() == f">query\n{BINDER_A}\n"
    assert binder_file != target_a3m
    # Nothing was given for pairing: the target MSA is an unpaired ColabFold a3m.
    assert "pairedMsaPath" not in target_chain and "pairedMsaPath" not in binder_chain


def test_target_msa_a3m_text_reaches_the_model_call_as_a_file(mod, fasta, tmp_path, monkeypatch):
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
            str(tmp_path / "px.csv"),
            "--output-dir",
            str(tmp_path / "out"),
            "--msa-cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    assert code == 0
    assert seen["text"] == a3m
    assert seen["name"] == "non_pairing.a3m"
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["target_msa_mode"] == "fetched"


# --- the command line ---------------------------------------------------------------------


def _capture_run(mod, monkeypatch, *, returncode=0, stderr=""):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"], captured["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, returncode, "", stderr)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return captured


def _call(mod, tmp_path, **over):
    kw = dict(
        query_id="q1",
        binder_seq=BINDER_A,
        target_seq=TARGET,
        target_msa_path=None,
        work_dir=tmp_path / "w",
        model_name=MODEL,
        model_dir=None,
        num_seeds=1,
        num_samples=5,
    )
    kw.update(over)
    return mod._predict_one(**kw)


def test_command_pins_the_model_and_the_sample_and_seed_counts(mod, tmp_path, monkeypatch):
    captured = _capture_run(mod, monkeypatch)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {"loaded": True})
    assert _call(mod, tmp_path) == {"loaded": True}
    cmd = captured["cmd"]
    assert Path(cmd[0]).name == "protenix"
    assert cmd[1] == "pred"

    def flag(name):
        return cmd[cmd.index(name) + 1]

    assert flag("-n") == MODEL
    assert flag("-s") == "101"  # Protenix's own default seed
    assert flag("-e") == "5"
    assert flag("--use_msa") == "false"  # no target MSA given -> single-sequence mode
    assert flag("--use_default_params") == "true"  # model-specific cycles/steps (10 / 200 for the v1 base models)
    assert flag("--need_atom_confidence") == "true"  # without it no full_data (PAE) file is written
    assert "--use_template" not in cmd and "--use_rna_msa" not in cmd  # both default to false
    assert "--msa_server_mode" not in cmd  # nothing is ever searched online
    # The input JSON it was pointed at is the one build_input wrote, and -o is a fresh dir under work_dir.
    doc = json.loads(Path(flag("-i")).read_text())
    assert doc[0]["name"] == "q1"
    assert Path(flag("-o")).parent == tmp_path / "w"
    # Kernel flags are only passed when asked for.
    assert "--trimul_kernel" not in cmd and "--triatt_kernel" not in cmd
    # Captured as text, so a failure's stderr is a str the driver can tail.
    assert captured["kw"]["capture_output"] is True and captured["kw"]["text"] is True


def test_command_with_msa_seeds_kernels_and_a_model_dir(mod, tmp_path, monkeypatch):
    captured = _capture_run(mod, monkeypatch)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    a3m = tmp_path / "t" / "non_pairing.a3m"
    a3m.parent.mkdir()
    a3m.write_text(f">q\n{TARGET}\n")
    root = tmp_path / "px_root"
    _call(
        mod,
        tmp_path,
        target_msa_path=a3m,
        num_seeds=3,
        num_samples=2,
        model_dir=root,
        model_name="protenix_base_20250630_v1.0.0",
        trimul_kernel="torch",
        triatt_kernel="torch",
    )
    cmd = captured["cmd"]

    def flag(name):
        return cmd[cmd.index(name) + 1]

    assert flag("--use_msa") == "true"
    assert flag("-s") == "101,102,103"
    assert flag("-e") == "2"
    assert flag("-n") == "protenix_base_20250630_v1.0.0"
    assert flag("--trimul_kernel") == "torch" and flag("--triatt_kernel") == "torch"
    assert captured["kw"]["env"]["PROTENIX_ROOT_DIR"] == str(root)
    doc = json.loads(Path(flag("-i")).read_text())
    assert doc[0]["sequences"][0]["proteinChain"]["unpairedMsaPath"] == str(a3m)


def test_nonzero_exit_is_a_failure_and_its_stderr_is_text(mod, tmp_path, monkeypatch):
    _capture_run(mod, monkeypatch, returncode=1, stderr="boom: cuda")
    with pytest.raises(mod.EngineError, match="exited with code 1") as exc:
        _call(mod, tmp_path)
    assert isinstance(exc.value.stderr, str) and "boom: cuda" in exc.value.stderr


def test_exit_zero_with_no_output_is_a_failed_design_and_carries_protenix_own_error_file(mod, tmp_path, monkeypatch):
    # inference.py catches a failed sample, writes <dump_dir>/ERR/<name>.txt and the CLI still exits 0.
    def fake_run(cmd, **kw):
        err = Path(cmd[cmd.index("-o") + 1]) / "ERR"
        err.mkdir(parents=True)
        (err / "q1.txt").write_text("q1 failed: CUDA out of memory\n")
        return subprocess.CompletedProcess(cmd, 0, "", "INFO fine")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(mod.EngineError, match="no prediction") as exc:
        _call(mod, tmp_path)
    assert "CUDA out of memory" in exc.value.stderr


def test_a_stale_work_dir_is_cleared_before_the_run(mod, tmp_path, monkeypatch):
    stale = tmp_path / "w" / "output" / "q1" / "seed_101" / "predictions"
    stale.mkdir(parents=True)
    (stale / "q1_summary_confidence_sample_0.json").write_text("{}")
    _capture_run(mod, monkeypatch)
    with pytest.raises(mod.EngineError, match="no prediction"):
        _call(mod, tmp_path)  # the leftover sample of an earlier attempt must not be picked up


# --- output files: layout, top sample, PAE, pLDDT ------------------------------------------

_COLUMNS = [
    "group_PDB",
    "id",
    "type_symbol",
    "label_atom_id",
    "label_comp_id",
    "label_asym_id",
    "label_seq_id",
    "Cartn_x",
    "Cartn_y",
    "Cartn_z",
    "B_iso_or_equiv",
    "auth_asym_id",
    "pdbx_PDB_model_num",
]


def mini_cif(*, target_b=90.0, binder_b=80.0, nt: int = NT, nb: int = NB, drop_ca: tuple[str, int] | None = None):
    """A biotite-shaped mmCIF: one N/CA/C triple per residue, B-factor = pLDDT (0-100)."""
    lines = ["data_stub", "#", "loop_", *(f"_atom_site.{c}" for c in _COLUMNS)]
    serial = 0
    for chain, n, b in (("A", nt, target_b), ("B", nb, binder_b)):
        for res in range(1, n + 1):
            for atom in ("N", "CA", "C"):
                if drop_ca == (chain, res) and atom == "CA":
                    continue
                serial += 1
                lines.append(f"ATOM {serial} {atom[0]} {atom} ALA {chain} {res} 1.000 2.000 3.000 {b:.2f} {chain} 1")
    lines.append("#")
    return "\n".join(lines) + "\n"


def write_sample(
    root: Path,
    name: str,
    seed: int,
    rank: int,
    score: float,
    pae_value: float = 1.0,
    *,
    nt: int = NT,
    nb: int = NB,
    cif: str | None = None,
    asym=None,
    pae=None,
):
    d = root / name / f"seed_{seed}" / "predictions"
    d.mkdir(parents=True, exist_ok=True)
    stem = f"{name}_sample_{rank}"
    (d / f"{stem}.cif").write_text(mini_cif(nt=nt, nb=nb) if cif is None else cif)
    (d / f"{stem}_wounresol.cif").write_text("data_decoy\n")  # Protenix writes a second, shorter copy
    (d / f"{name}_summary_confidence_sample_{rank}.json").write_text(
        json.dumps({"plddt": 85.0, "ptm": 0.6, "iptm": 0.5, "ranking_score": score, "has_clash": 0.0})
    )
    n = nt + nb
    full = {
        "atom_plddt": [0.9] * 5,
        "token_pair_pae": ([[pae_value] * n] * n) if pae is None else pae,
        "token_asym_id": ([0] * nt + [1] * nb) if asym is None else asym,
    }
    (d / f"{name}_full_data_sample_{rank}.json").write_text(json.dumps(full))
    return d


def test_top_sample_is_the_highest_ranking_score_across_seeds_and_ranks(mod, tmp_path):
    write_sample(tmp_path, "q1", 101, 0, 0.60, 3.0)
    write_sample(tmp_path, "q1", 101, 1, 0.40, 1.0)
    write_sample(tmp_path, "q1", 102, 0, 0.90, 2.0)  # the winner: another seed's rank 0
    write_sample(tmp_path, "q1", 102, 1, 0.30, 4.0)
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    assert top["seed"] == 102
    assert top["cif"].name == "q1_sample_0.cif"  # never the _wounresol decoy
    assert top["cif"].parent.parent.name == "seed_102"
    assert top["summary"]["sample_ranking_score"] == pytest.approx(0.90)
    assert top["summary"]["iptm"] == pytest.approx(0.5) and top["summary"]["ptm"] == pytest.approx(0.6)
    assert float(top["pae"][0, 0]) == 2.0  # the PAE of THAT sample, not another's
    assert top["pae"].shape == (NT + NB, NT + NB)
    assert len(top["plddt_target"]) == NT and len(top["plddt_binder"]) == NB


def test_top_sample_is_none_when_nothing_was_written(mod, tmp_path):
    assert mod._load_top_sample(tmp_path, "q1", NT, NB) is None


def test_non_finite_ranking_scores_are_skipped_when_picking_the_top_sample(mod, tmp_path):
    write_sample(tmp_path, "q1", 101, 0, float("nan"), 1.0)
    write_sample(tmp_path, "q1", 101, 1, 0.30, 2.0)
    write_sample(tmp_path, "q1", 102, 0, float("inf"), 3.0)
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    assert top["cif"].name == "q1_sample_1.cif"
    write_sample(tmp_path, "q2", 101, 0, float("nan"), 1.0)
    assert mod._load_top_sample(tmp_path, "q2", NT, NB) is None


def test_a_sample_without_its_cif_or_full_data_file_is_not_a_candidate(mod, tmp_path):
    d = write_sample(tmp_path, "q1", 101, 0, 0.99)
    (d / "q1_full_data_sample_0.json").unlink()  # no PAE for the best-scoring sample
    write_sample(tmp_path, "q1", 101, 1, 0.20, 7.0)
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    assert top["cif"].name == "q1_sample_1.cif" and float(top["pae"][0, 0]) == 7.0


def test_pae_is_the_token_pair_pae_in_target_first_order(mod, tmp_path):
    write_sample(tmp_path, "q1", 101, 0, 0.5, pae=native_pae().tolist())
    top = mod._load_top_sample(tmp_path, "q1", NT, NB)
    np.testing.assert_array_equal(top["pae"], native_pae())  # untouched here; the driver re-blocks it


def test_a_binder_first_token_order_is_refused_not_silently_mis_blocked(mod, tmp_path):
    # Same sizes, so the driver's size check could not see this: the tokens say binder (asym 1) is first.
    write_sample(tmp_path, "q1", 101, 0, 0.5, asym=[1] * NT + [0] * NB)
    with pytest.raises(ValueError, match="target"):
        mod._load_top_sample(tmp_path, "q1", NT, NB)


def test_token_count_that_differs_from_the_residue_count_is_refused(mod, tmp_path):
    # e.g. a non-standard residue or a ligand token: residue-indexed blocks would be wrong.
    write_sample(
        tmp_path,
        "q1",
        101,
        0,
        0.5,
        nt=NT,
        nb=NB,
        asym=[0] * NT + [1] * (NB + 1),
        pae=np.zeros((NT + NB + 1,) * 2).tolist(),
    )
    with pytest.raises(ValueError, match="token"):
        mod._load_top_sample(tmp_path, "q1", NT, NB)


def test_a_missing_token_asym_id_is_refused(mod, tmp_path):
    d = write_sample(tmp_path, "q1", 101, 0, 0.5)
    fp = d / "q1_full_data_sample_0.json"
    full = json.loads(fp.read_text())
    del full["token_asym_id"]
    fp.write_text(json.dumps(full))
    with pytest.raises(ValueError, match="token_asym_id"):
        mod._load_top_sample(tmp_path, "q1", NT, NB)


def test_per_residue_plddt_is_the_ca_b_factor_per_chain_on_a_0_100_scale(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text(mini_cif(target_b=91.5, binder_b=64.25))
    out = mod._ca_plddt_by_chain(cif, NT, NB)
    assert list(out) == ["A", "B"] or set(out) == {"A", "B"}
    np.testing.assert_allclose(out["A"], np.full(NT, 91.5))
    np.testing.assert_allclose(out["B"], np.full(NB, 64.25))


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


def test_a_cif_without_an_atom_site_loop_or_chain_is_refused(mod, tmp_path):
    cif = tmp_path / "m.cif"
    cif.write_text("data_stub\n")
    with pytest.raises(ValueError, match="atom_site"):
        mod._ca_plddt_by_chain(cif, NT, NB)
    cif.write_text(mini_cif(nb=0))
    with pytest.raises(ValueError, match="binder"):
        mod._ca_plddt_by_chain(cif, NT, NB)


# --- kernel and layernorm switches (needed on aarch64 / hosts without nvcc) -----------------------


def test_layernorm_type_is_exported_to_the_subprocess_only_when_asked(mod, tmp_path, monkeypatch):
    monkeypatch.delenv("LAYERNORM_TYPE", raising=False)
    captured = _capture_run(mod, monkeypatch)
    monkeypatch.setattr(mod, "_load_top_sample", lambda *a, **k: {})
    _call(mod, tmp_path)
    assert "LAYERNORM_TYPE" not in captured["kw"]["env"]  # unset = pass nothing
    _call(mod, tmp_path, layernorm_type="torch")
    assert captured["kw"]["env"]["LAYERNORM_TYPE"] == "torch"
    # an inherited value is overridden by the explicit option, never the other way round
    monkeypatch.setenv("LAYERNORM_TYPE", "fast_layernorm")
    _call(mod, tmp_path, layernorm_type="torch")
    assert captured["kw"]["env"]["LAYERNORM_TYPE"] == "torch"
    # and the process's own environment is not modified
    assert os.environ["LAYERNORM_TYPE"] == "fast_layernorm"


@pytest.mark.parametrize(
    "flags",
    [
        ["--trimul-kernel", "triattention"],  # valid for triatt, not for trimul
        ["--trimul-kernel", "deepspeed"],
        ["--trimul-kernel", "cuda"],
        ["--triatt-kernel", "fast"],
        ["--triatt-kernel", ""],
        ["--layernorm-type", "cuda"],
    ],
)
def test_unknown_kernel_or_layernorm_values_are_refused_before_any_work(mod, fasta, tmp_path, monkeypatch, flags):
    called = []
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: called.append(kw))
    with pytest.raises(SystemExit) as exc:
        run_main(mod, fasta, tmp_path, *flags)
    assert exc.value.code == 2 and not called
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("trimul", ["cuequivariance", "torch"])
@pytest.mark.parametrize("triatt", ["triattention", "cuequivariance", "deepspeed", "torch"])
def test_every_documented_kernel_value_is_accepted(mod, fasta, tmp_path, monkeypatch, trimul, triatt):
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    code, _ = run_main(mod, fasta, tmp_path, "--trimul-kernel", trimul, "--triatt-kernel", triatt)
    assert code == 0


def test_run_info_settings_record_the_kernels_and_layernorm_actually_used(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.delenv("LAYERNORM_TYPE", raising=False)
    seen = {}

    def predict(**kw):
        seen.update(kw)
        return fake_prediction(tmp_path, kw["query_id"])

    monkeypatch.setattr(mod, "_predict_one", predict)
    code, _ = run_main(
        mod, fasta, tmp_path, "--trimul-kernel", "torch", "--triatt-kernel", "deepspeed", "--layernorm-type", "torch"
    )
    assert code == 0
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["settings"] == {"trimul_kernel": "torch", "triatt_kernel": "deepspeed", "layernorm_type": "torch"}
    # the sidecar follows what reaches the model call
    assert (seen["trimul_kernel"], seen["triatt_kernel"], seen["layernorm_type"]) == ("torch", "deepspeed", "torch")


def test_run_info_settings_say_default_when_nothing_was_passed(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.delenv("LAYERNORM_TYPE", raising=False)
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    run_main(mod, fasta, tmp_path)
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["settings"] == {"trimul_kernel": "default", "triatt_kernel": "default", "layernorm_type": "default"}


def test_an_inherited_layernorm_env_is_recorded_not_hidden(mod, fasta, tmp_path, monkeypatch):
    monkeypatch.setenv("LAYERNORM_TYPE", "torch")
    monkeypatch.setattr(mod, "_predict_one", lambda **kw: fake_prediction(tmp_path, kw["query_id"]))
    run_main(mod, fasta, tmp_path)
    info = json.loads((tmp_path / "out" / "refold_run_info.json").read_text())
    assert info["settings"]["layernorm_type"] == "torch"
