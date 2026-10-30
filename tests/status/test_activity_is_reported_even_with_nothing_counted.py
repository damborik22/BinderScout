"""An arm with 0 counted designs still has to show whether it is making progress.

BoltzGen on BM2 had written 3430 intermediate files and zero counted designs. If
age is read only from the COUNTED artifacts, that arm renders as `0/5000` with no
activity signal whatsoever -- indistinguishable from one that has written nothing
since it started. The intermediates are the evidence it is alive and working.

So the probe reports two timestamps: `mtimes` of the counted artifacts, which is
what cadence and ETA are derived from, and `activity_mtime`, the newest write
anywhere in the arm, which is what "last ..." renders.
"""

import json

from status.probes import probe_tool
from status.render_term import render

CFG = {"name": "camp", "n_designs": 5000}


def test_intermediates_set_the_activity_clock_without_being_counted(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    inter = tmp_path / "boltzgen" / "outputs" / "intermediate_designs"
    inter.mkdir(parents=True)
    (inter / "i0.cif").write_text("data_x\n")

    r = probe_tool("boltzgen", tmp_path, CFG)
    assert r["done"] == 0
    assert r["mtimes"] == [], "cadence must not be derived from intermediates"
    assert r["activity_mtime"] is not None, "but the arm is demonstrably alive"


def test_an_arm_with_no_files_at_all_has_no_activity(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    (tmp_path / "boltzgen").mkdir()
    assert probe_tool("boltzgen", tmp_path, CFG)["activity_mtime"] is None


def test_the_renderer_shows_the_activity_age():
    doc = {
        "generated_at": "now",
        "hosts": {
            "bm2": {
                "reachable": True,
                "runs": {
                    "camp": {
                        "n_designs": 5000,
                        "tools": {
                            "boltzgen": {
                                "state": "running",
                                "done": 0,
                                "total": 5000,
                                "started": True,
                                "output_age_s": 95.0,
                                "warnings": [],
                                "eta_s": None,
                                "proc": {"alive": True},
                            }
                        },
                    }
                },
            }
        },
    }
    line = next(ln for ln in render(doc).splitlines() if "boltzgen" in ln)
    assert "last" in line, line
