"""An arm with 0 counted designs still has to show whether it is making progress.

An arm writes plenty that its design count never sees -- logs, checkpoints,
caches, work in progress. If age is read only from the COUNTED artifacts, such an
arm renders with no activity signal at all, indistinguishable from one that has
written nothing since it started.

So the probe reports two timestamps: `mtimes` of the counted artifacts, which is
what cadence and ETA are derived from, and `activity_mtime`, the newest write
anywhere in the arm, which is what "last ..." renders.

(This was first written against BoltzGen's intermediates. That was the wrong
example: those intermediates ARE its generation progress and are now counted as
such -- see test_boltzgen_is_a_two_phase_tool.py. The principle stands and is
tested here on an arm whose writes genuinely are not designs.)
"""

import json

from status.probes import probe_tool
from status.render_term import render

CFG = {"name": "camp", "n_designs": 5000}


def test_non_design_writes_set_the_activity_clock_without_being_counted(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    d = tmp_path / "rfd3"
    d.mkdir()
    # Not a design by any reading: rfd3 designs are rfd3/diffusion/*.cif.gz.
    (d / "rfd3.log").write_text("loading weights\n")

    r = probe_tool("rfd3", tmp_path, CFG)
    assert r["done"] == 0
    assert r["mtimes"] == [], "cadence must not be derived from non-designs"
    assert r["activity_mtime"] is not None, "but the arm is demonstrably alive"


def test_an_arm_with_no_files_at_all_has_no_activity(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    (tmp_path / "rfd3").mkdir()
    assert probe_tool("rfd3", tmp_path, CFG)["activity_mtime"] is None


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
