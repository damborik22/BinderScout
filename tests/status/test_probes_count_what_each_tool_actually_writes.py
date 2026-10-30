"""One probe per tool, against the layout that tool really produces.

Layouts here were read off disk on 2026-10-30, not taken from documentation:
  rfd3  -> rfd3/diffusion/*.cif.gz                        (50 on the pMHC arm, BM4)
  rfd4  -> rfd4/generate/inference_samples/<n>_<i>/<n>_<i>_generated.cif  (50, BM1)

Probes COUNT, they never parse. A monitor that parses a half-written CSV crashes
exactly when you most want to look at it.
"""

import gzip
import json

import pytest

from status.probes import probe_tool

CFG = {"name": "camp", "n_designs": 50, "chains": "A"}


def _run(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    return tmp_path


def test_rfd3_counts_compressed_mmcifs(tmp_path):
    d = _run(tmp_path) / "rfd3" / "diffusion"
    d.mkdir(parents=True)
    for i in range(12):
        with gzip.open(d / f"camp_{i}.cif.gz", "wt") as fh:
            fh.write("data_x\n")
    r = probe_tool("rfd3", tmp_path, CFG)
    assert (r["done"], r["total"]) == (12, 50)


def test_rfd4_counts_generated_cifs_not_the_sample_directories(tmp_path):
    base = _run(tmp_path) / "rfd4" / "generate" / "inference_samples"
    for i in range(8):
        s = base / f"camp_{i}"
        s.mkdir(parents=True)
        (s / f"camp_{i}_generated.cif").write_text("data_x\n")
    # A sample dir that exists but holds no structure yet must not be counted.
    (base / "camp_8").mkdir()
    r = probe_tool("rfd4", tmp_path, CFG)
    assert (r["done"], r["total"]) == (8, 50)


def test_bindcraft2_counts_accepted_rows_not_files_on_disk(tmp_path):
    # Its budget is a quota of ACCEPTED designs and it writes structures for
    # rejected candidates too, so a file count overstates it.
    d = _run(tmp_path) / "bindcraft2" / "3_Ranked"
    d.mkdir(parents=True)
    (d / "!_Ranked.csv").write_text("rank,design,Binder_Sequence\n1,a,AAA\n2,b,BBB\n3,c,CCC\n")
    r = probe_tool("bindcraft2", tmp_path, CFG)
    assert (r["done"], r["total"]) == (3, 50)


def test_boltzgen_is_not_counted_from_structures_on_disk(tmp_path):
    # Measured on BM2 2026-10-30: 3430 .cif files, all intermediates, zero
    # finished designs. Counting structures would have reported 3430/5000 for a
    # run that has produced nothing. The count comes from the metrics CSV --
    # see test_the_probe_counts_what_the_extractor_would_extract.py.
    d = _run(tmp_path) / "boltzgen" / "outputs" / "intermediate_designs"
    d.mkdir(parents=True)
    for i in range(5):
        (d / f"d{i}.cif").write_text("data_x\n")
    assert probe_tool("boltzgen", tmp_path, CFG)["done"] == 0


def test_an_empty_tool_dir_counts_zero_and_does_not_raise(tmp_path):
    (_run(tmp_path) / "rfd3").mkdir()
    r = probe_tool("rfd3", tmp_path, CFG)
    assert r["done"] == 0
    assert r["started"] is False


def test_a_truncated_csv_does_not_crash_the_probe(tmp_path):
    d = _run(tmp_path) / "bindcraft2" / "3_Ranked"
    d.mkdir(parents=True)
    (d / "!_Ranked.csv").write_text("rank,design,Binder_Seq")  # header only, no newline
    r = probe_tool("bindcraft2", tmp_path, CFG)
    assert r["done"] == 0


def test_an_unknown_tool_reports_no_denominator_rather_than_inventing_one(tmp_path):
    d = _run(tmp_path) / "some_future_tool"
    d.mkdir()
    (d / "out.pdb").write_text("ATOM\n")
    r = probe_tool("some_future_tool", tmp_path, CFG)
    assert r["total"] is None, "a guessed denominator is a lie; None renders as 'total unknown'"
    assert r["done"] >= 0


def test_mtimes_are_returned_so_cadence_can_be_derived(tmp_path):
    d = _run(tmp_path) / "rfd3" / "diffusion"
    d.mkdir(parents=True)
    for i in range(3):
        with gzip.open(d / f"c_{i}.cif.gz", "wt") as fh:
            fh.write("data_x\n")
    r = probe_tool("rfd3", tmp_path, CFG)
    assert len(r["mtimes"]) == 3
    assert all(isinstance(m, float) for m in r["mtimes"])


@pytest.mark.parametrize("mag,expect_warning", [(0.008, True), (23.05, False)])
def test_rfd3_flags_a_near_zero_fixed_com(tmp_path, mag, expect_warning):
    # |fixed_com| near zero means infer_ori_strategy: hotspots is missing and
    # every design in the arm is void. 304 backbones were lost to this once.
    d = _run(tmp_path) / "rfd3" / "diffusion"
    d.mkdir(parents=True)
    with gzip.open(d / "c_0.cif.gz", "wt") as fh:
        fh.write("data_x\n")
    (d / "c_0.json").write_text(json.dumps({"metrics": {"fixed_com": [mag, 0.0, 0.0]}}))
    warnings = probe_tool("rfd3", tmp_path, CFG)["warnings"]
    hit = any("fixed_com" in w for w in warnings)
    assert hit is expect_warning, f"|fixed_com|={mag} -> warnings={warnings}"


def test_a_failed_marker_in_the_log_is_surfaced(tmp_path):
    # run_arm.sh writes this when a tool exits non-zero; the old dispatch
    # reported rc=0 after a pipe and an OOM read as a zero-yield run.
    run = _run(tmp_path)
    (run / "rfd3").mkdir()
    (run / "rfd3" / "settings.json").write_text("{}")
    logs = run / "logs"
    logs.mkdir()
    (logs / "rfd3.log").write_text(
        "...\n"
        "######## END rfd3 rc=137 2026-10-30T11:23:34+01:00 ########\n"
        "######## rfd3 FAILED -- do not read this arm as a zero-yield run ########\n"
    )
    r = probe_tool("rfd3", run, CFG)
    assert any("137" in w for w in r["warnings"]), r["warnings"]
