"""The duplication guard the design doc promises.

The probe knows each tool's layout a second time, because the Evaluator's
extractors parse and live in a conda env while the probe must count and run on a
bare python3. The price of that duplication is this test: if the two ever
disagree about WHICH file holds a tool's designs, the monitor reports a number
nobody will be able to reproduce downstream.

Found by running against the live fleet: the BoltzGen probe globbed
`boltzgen/outputs/*.pdb`, and BoltzGen writes `.cif`. On BM2 it had produced 3430
files, all of them under `intermediate_designs/`, and zero counted designs. The
glob was wrong AND an intermediate is not a design -- so a naive fix would have
reported 3430/5000 for a run that has finished nothing.
"""

import json

from status.probes import boltzgen_count_sources, probe_tool

CFG = {"name": "camp", "n_designs": 5000}


def test_the_boltzgen_probe_reads_the_same_files_as_the_extractor():
    from binder_comparison.extractors.boltzgen import _CSV_CANDIDATES

    assert list(boltzgen_count_sources()) == list(_CSV_CANDIDATES), (
        "probe and extractor must agree on which file holds BoltzGen's designs"
    )


def test_intermediate_designs_are_not_counted_as_designs(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    inter = tmp_path / "boltzgen" / "outputs" / "intermediate_designs"
    inter.mkdir(parents=True)
    for i in range(3430):
        (inter / f"i{i}.cif").write_text("data_x\n")

    r = probe_tool("boltzgen", tmp_path, CFG)
    assert r["done"] == 0, "an intermediate is not a finished design"


def test_the_metrics_csv_is_what_counts(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    out = tmp_path / "boltzgen" / "outputs"
    out.mkdir(parents=True)
    (out / "aggregate_metrics_step1.csv").write_text("design_id,designed_chain_sequence\n0,AAA\n1,BBB\n2,CCC\n")
    assert probe_tool("boltzgen", tmp_path, CFG)["done"] == 3


def test_final_designs_metrics_wins_over_aggregate(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    out = tmp_path / "boltzgen" / "outputs"
    out.mkdir(parents=True)
    (out / "aggregate_metrics_step1.csv").write_text("a\n1\n2\n3\n4\n5\n")
    (out / "final_designs_metrics_100.csv").write_text("a\n1\n2\n")
    assert probe_tool("boltzgen", tmp_path, CFG)["done"] == 2
