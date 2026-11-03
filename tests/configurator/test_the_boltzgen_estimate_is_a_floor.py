"""The BoltzGen pre-run estimate is a floor, built only from step costs measured in this repo.

It priced the diffusion step alone ("~9 min" for the 100-design pool of a 1-design smoke run) and
a live run took about three times that, because inverse folding, Boltz-2 folding and
analysis have no cost in it. The note now says "at least", says what it counts, and adds the
one other measured step (the ~15 s filter) instead of an invented multiplier.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf


def _minutes(note: str) -> int:
    return int(re.search(r"at least ~(\d+) min", note).group(1))


def test_it_is_stated_as_a_floor():
    note = conf.boltzgen_cost_note(50)
    assert "at least" in note
    assert "come on top" in note, "the note must say that other steps are not counted"


def test_the_arithmetic_is_the_measured_step_costs_and_nothing_else():
    n = 50
    expected = n * conf._BOLTZGEN_SECONDS_PER_DESIGN + conf._BOLTZGEN_FILTER_SECONDS
    assert _minutes(conf.boltzgen_cost_note(n)) == round(expected / 60)


def test_the_fixed_filter_cost_is_counted():
    """At 50 designs the diffusion step alone is 267.5 s (4.46 min -> ~4); with the filter it is ~5."""
    assert _minutes(conf.boltzgen_cost_note(50)) == 5


def test_a_production_pool_still_reads_in_hours():
    note = conf.boltzgen_cost_note(10000)
    assert "10,000 intermediate designs" in note
    assert "at least ~15 h" in note, note


def test_the_replay_summary_prints_the_floor_wording(tmp_path, fake_checkout, replay):
    repo = Path(__file__).resolve().parents[2]
    payload = json.loads((repo / "examples" / "CALCA" / "smoke.json").read_text())
    payload["cfg"]["target_pdb_src"] = str(repo / "examples" / "CALCA" / "target.pdb")
    payload["cfg"]["name"] = "floor"
    payload["tools_enabled"] = {"boltzgen": True}
    path = tmp_path / "c.json"
    path.write_text(json.dumps(payload))
    proc = replay(path, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1500:]
    assert "100 intermediate designs (at least ~9 min" in proc.stdout, proc.stdout
