"""The shipped example must keep working, or it is worse than no example.

`examples/CALCA/smoke.json` is the one thing a new user is told to run after an
~85 GB install. A config that no longer replays would send them straight into a
traceback with nothing to compare against.

It is also the only in-repo exercise of the `--config` replay path that README
calls "the seam any front-end should use", so it doubles as that path's
regression test.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "configurator"))
import configurator as conf  # noqa: E402

SMOKE = REPO / "examples" / "CALCA" / "smoke.json"
TARGET = REPO / "examples" / "CALCA" / "target.pdb"


def test_the_example_target_exists_and_parses():
    assert TARGET.exists(), "examples/CALCA/target.pdb is missing"
    assert conf.available_chains(TARGET) == ["A"]
    seq = conf.extract_sequence_from_structure(str(TARGET), "A")
    assert seq and len(seq) == 32, f"expected the 32 aa CALCA target, got {len(seq or '')}"


def test_the_declared_sequence_matches_the_structure():
    """A mismatch here is the RFD3 mislabelling trap, pre-loaded into the one
    config we hand people."""
    cfg = json.loads(SMOKE.read_text())["cfg"]
    assert cfg["target_sequence"] == conf.extract_sequence_from_structure(str(TARGET), cfg["chains"])


def test_the_example_replays(tmp_path, monkeypatch):
    monkeypatch.chdir(REPO)
    cfg, tools = conf.load_run_config(SMOKE)
    assert Path(cfg["run_dir"]).is_absolute()
    enabled = {k for k, v in tools.items() if v is True}
    assert "evaluator" in enabled
    design_tools = {k for k, _s, _l, _d in conf.TOOL_SEQUENCE}
    missing = design_tools - enabled
    assert not missing, f"the smoke test no longer exercises every design tool: missing {sorted(missing)}"


def test_every_required_key_is_present_for_every_enabled_tool():
    """Runs the configurator's own preflight, so the example cannot drift out of
    sync with REQUIRED_CFG_KEYS."""
    cfg, tools = conf.load_run_config(SMOKE)
    for tool, enabled in tools.items():
        if not enabled or tool not in conf.REQUIRED_CFG_KEYS:
            continue
        missing = [k for k in conf.REQUIRED_CFG_KEYS[tool] if k not in cfg and k != "target_pdb"]
        assert not missing, f"{tool}: example config is missing {missing}"


@pytest.mark.parametrize(("key", "limit"), [("n_designs", 2), ("bindcraft_n_designs", 2), ("rfd3_n_designs", 2)])
def test_the_example_stays_small(key, limit):
    """It is a smoke test. If someone raises these it stops being minutes."""
    cfg = json.loads(SMOKE.read_text())["cfg"]
    if key in cfg:
        assert cfg[key] <= limit, f"{key}={cfg[key]} is too large for a smoke test"
