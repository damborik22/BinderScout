"""A run with design tools but no Evaluator tells you how to get run_evaluate.sh.

The Evaluator is its own yes/no. Answering no writes no `run_evaluate.sh`, and the end of
generation said nothing about it, so the absent ranking step looked like a generator bug.
One line now names the answer / the config key.

Replayed as a subprocess by path (see conftest.py).
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "examples" / "CALCA" / "smoke.json"
TARGET = REPO / "examples" / "CALCA" / "target.pdb"
HINT = "No run_evaluate.sh"


def _config(tmp_path: Path, name: str, tools: dict) -> Path:
    payload = json.loads(SMOKE.read_text())
    payload["cfg"]["target_pdb_src"] = str(TARGET)
    payload["cfg"]["name"] = name
    payload["cfg"]["run_dir"] = f"runs/{name}"
    payload["tools_enabled"] = tools
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload))
    return path


def test_design_tools_without_the_evaluator_get_one_line(tmp_path, fake_checkout, replay):
    proc = replay(_config(tmp_path, "noeval", {"mosaic": True}), fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    run = fake_checkout / "runs" / "noeval"
    assert (run / "run_mosaic.sh").is_file(), "control: the design tool was generated"
    assert not (run / "run_evaluate.sh").exists(), "control: no evaluator, no run_evaluate.sh"
    lines = [ln for ln in proc.stdout.splitlines() if HINT in ln]
    assert len(lines) == 1, proc.stdout
    assert "evaluator" in lines[0] and "config.json" in lines[0] and "cross-evaluation" in lines[0]


def test_following_the_hint_produces_run_evaluate_and_silences_it(tmp_path, fake_checkout, replay):
    proc = replay(_config(tmp_path, "witheval", {"mosaic": True, "evaluator": True}), fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert (fake_checkout / "runs" / "witheval" / "run_evaluate.sh").is_file(), "control: the script was written"
    assert HINT not in proc.stdout


def test_an_evaluator_only_run_is_not_told_to_enable_the_evaluator(tmp_path, fake_checkout, replay):
    proc = replay(_config(tmp_path, "evalonly", {"evaluator": True}), fake_checkout, tmp_path)
    assert HINT not in proc.stdout


def test_both_ends_of_generation_print_it():
    """The wizard's ending is interactive and not replayed here, so pin that it is wired in:
    the helper is called after the headless AND the wizard 'To run' blocks."""
    src = (REPO / "configurator" / "configurator.py").read_text()
    assert src.count("    print_evaluator_hint(tools_enabled, run_dir)\n") == 2
