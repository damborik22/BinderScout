"""BoltzGen generates, then analyses, then filters — and only the last step counts rows.

Asked why no BoltzGen count appeared, the answer was my bug, not the tool's.
`--num_designs 5000` is how many raw designs to GENERATE (they land under
`outputs/intermediate_designs/`); `--budget 50` is the size of the final
diversity-optimised set after the filter step; and `aggregate_metrics_*.csv` is
written by the ANALYSE step, which runs only after generation finishes
(`boltzgen/cli/boltzgen.py` writes `aggregate_metrics_analyze.csv`, and
`task/filter/filter.py` requires it).

So mid-generation there is no metrics file and the pool is genuinely 0 banked —
but the arm had written 3461 of its 5000 raw designs, and reporting `0/5000`
hid that completely. Both phases are real progress and each has its own
denominator, so the probe reports whichever phase the arm is actually in.
"""

import json

from status.probes import probe_tool

CFG = {"name": "camp", "n_designs": 5000}


def _run(tmp_path, num_designs=5000, budget=50):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    d = tmp_path / "boltzgen"
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text(json.dumps({"design_params": {"num_designs": num_designs, "budget": budget}}))
    return d


def test_mid_generation_counts_raw_designs_against_num_designs(tmp_path):
    d = _run(tmp_path)
    inter = d / "outputs" / "intermediate_designs"
    inter.mkdir(parents=True)
    for i in range(3461):
        (inter / f"d{i}.cif").write_text("data_x\n")

    r = probe_tool("boltzgen", tmp_path, CFG)
    assert r["phase"] == "generating"
    assert (r["done"], r["total"]) == (3461, 5000)


def test_after_analysis_counts_banked_designs_against_the_budget(tmp_path):
    d = _run(tmp_path)
    out = d / "outputs"
    (out / "intermediate_designs").mkdir(parents=True)
    for i in range(5000):
        (out / "intermediate_designs" / f"d{i}.cif").write_text("x\n")
    (out / "aggregate_metrics_analyze.csv").write_text("id,file_name\n" + "".join(f"{i},f{i}\n" for i in range(37)))

    r = probe_tool("boltzgen", tmp_path, CFG)
    assert r["phase"] == "banked"
    assert (r["done"], r["total"]) == (37, 50)


def test_the_filtered_set_wins_over_the_analysis_table(tmp_path):
    d = _run(tmp_path)
    out = d / "outputs"
    out.mkdir(parents=True)
    (out / "aggregate_metrics_analyze.csv").write_text("id\n" + "".join(f"{i}\n" for i in range(900)))
    (out / "final_designs_metrics_50.csv").write_text("id\n" + "".join(f"{i}\n" for i in range(50)))

    r = probe_tool("boltzgen", tmp_path, CFG)
    assert (r["done"], r["total"]) == (50, 50)
    assert r["phase"] == "banked"


def test_generation_cadence_is_derivable(tmp_path):
    # The generating phase must feed mtimes, or a 5000-design run has no ETA
    # for the 18 hours it spends there.
    d = _run(tmp_path)
    inter = d / "outputs" / "intermediate_designs"
    inter.mkdir(parents=True)
    for i in range(5):
        (inter / f"d{i}.cif").write_text("x\n")
    r = probe_tool("boltzgen", tmp_path, CFG)
    assert len(r["mtimes"]) == 5


def test_an_arm_that_has_written_nothing_is_still_generating_zero(tmp_path):
    _run(tmp_path)
    r = probe_tool("boltzgen", tmp_path, CFG)
    assert (r["done"], r["total"], r["phase"]) == (0, 5000, "generating")


def test_other_tools_report_no_phase(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    (tmp_path / "rfd3").mkdir()
    assert probe_tool("rfd3", tmp_path, CFG)["phase"] is None
