"""RFD3 must be refused at configure time when there is nothing for it to aim at.

`infer_ori_strategy: hotspots` is load-bearing in the RFD3 input YAML, and it asserts inside RFD3
-- after the 2.5 GB model has loaded -- when no hotspots exist (the `is_atom_level_hotspot`
annotation is never created). Two wrong answers exist and both are worse than refusing:

* emit the key anyway: every run dies in the dataloader, after the GPU is committed;
* fall back to `infer_ori_strategy: com`: the crash goes away and the output becomes unfoldable.
  Centring on the whole fixed motif's centre of mass seeds every diffused atom at the target's
  centre, the binder nucleates inside the target and grows as an extended coil, `n_chainbreaks`
  stays 0 and every downstream gate passes (measured: binder Rg 23.1 A vs 10.9 A, helix fraction
  0.27 vs 0.85).

So the configurator says no, before a single file is written, and names both ways out. The shipped
smoke config enables every tool, so it carries `rfd3_hotspots`; the replay test below removes it.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "examples" / "CALCA" / "smoke.json"

PDB = "".join(
    f"ATOM  {i:5d}  CA  ALA A{i:4d}    {float(i):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C\n"
    for i in range(1, 6)
)


@pytest.fixture
def cfg(tmp_path):
    run_dir = tmp_path / "runs" / "t"
    run_dir.mkdir(parents=True)
    pdb = tmp_path / "target.pdb"
    pdb.write_text(PDB)
    return {
        "name": "t",
        "run_dir": run_dir,
        "target_pdb": pdb,
        "target_pdb_src": str(pdb),
        "target_sequence": "AAAAA",
        "chains": "A",
        "hotspots": "",
        "min_length": 20,
        "max_length": 30,
        "n_designs": 1,
    }


def _text(capsys):
    out = capsys.readouterr()
    return out.out + out.err


# ------------------------------------------------------------------ the writer


@pytest.mark.parametrize("blank", ["", None, "   "])
def test_the_writer_refuses_and_writes_nothing(cfg, tmp_path, capsys, blank):
    cfg["hotspots"] = blank
    script = tmp_path / "run_rfd3.sh"
    with pytest.raises(SystemExit) as exc:
        conf.write_run_rfd3(script, cfg)
    assert exc.value.code not in (0, None)
    assert not script.exists(), "a half-written script is worse than none: run_all.sh would still call it"
    assert "hotspot" in _text(capsys).lower()


def test_the_refusal_names_both_remedies(cfg, tmp_path, capsys):
    with pytest.raises(SystemExit):
        conf.write_run_rfd3(tmp_path / "run_rfd3.sh", cfg)
    text = _text(capsys)
    assert '"hotspots"' in text and '"rfd3_hotspots"' in text, "remedy 1: supply hotspots (campaign-wide or RFD3-only)"
    assert '"rfd3": false' in text, "remedy 2: leave RFD3 out of this campaign"


@pytest.mark.parametrize("key", ["hotspots", "rfd3_hotspots"])
def test_control_with_hotspots_the_script_aims_at_them(cfg, tmp_path, key):
    """Proves the refusal is about the hotspots and that the writer is reached when they exist."""
    cfg[key] = "2,3"
    script = tmp_path / "run_rfd3.sh"
    conf.write_run_rfd3(script, cfg)
    text = script.read_text()
    assert "infer_ori_strategy: hotspots" in text
    assert 'select_hotspots: "A2,A3"' in text
    assert "infer_ori_strategy: com" not in text


def test_a_tool_specific_value_is_enough_when_the_global_one_is_blank(cfg, tmp_path):
    cfg["hotspots"] = ""
    cfg["rfd3_hotspots"] = "4"
    conf.write_run_rfd3(tmp_path / "run_rfd3.sh", cfg)
    assert 'select_hotspots: "A4"' in (tmp_path / "run_rfd3.sh").read_text()


# ------------------------------------------------------------------ preflight


def test_preflight_refuses_before_anything_is_written(cfg, capsys):
    run_dir = Path(cfg["run_dir"]) / "fresh"
    cfg["run_dir"] = run_dir
    with pytest.raises(SystemExit) as exc:
        conf.generate(cfg, {"rfd3": True})
    assert exc.value.code not in (0, None)
    assert not run_dir.exists(), "generate() must refuse before it creates the run folder"
    text = _text(capsys)
    assert "RFD3" in text and "hotspot" in text.lower()


def test_preflight_reports_it_alongside_other_problems(cfg, capsys):
    """preflight lists everything that is wrong at once; a hotspot-less RFD3 is one entry in that list."""
    with pytest.raises(SystemExit):
        conf.preflight({k: v for k, v in cfg.items() if k != "target_pdb"}, {"rfd3": True})
    assert "hotspot" in _text(capsys).lower()


def test_control_preflight_passes_with_hotspots_and_without_rfd3(cfg):
    conf.preflight({**cfg, "hotspots": "2"}, {"rfd3": True})
    # Hotspots are optional for the other tools; only RFD3 needs them.
    conf.preflight(cfg, {"rfd3": False})


# ------------------------------------------------------------------ headless replay


def _staged_smoke(tmp_path, fake_checkout, **cfg_overrides):
    payload = json.loads(SMOKE.read_text())
    payload["cfg"].update(cfg_overrides)
    ex = fake_checkout / "examples" / "CALCA"
    ex.mkdir(parents=True)
    (ex / "target.pdb").write_bytes((SMOKE.parent / "target.pdb").read_bytes())
    config = ex / "smoke.json"
    config.write_text(json.dumps(payload))
    return config


def test_a_headless_replay_without_hotspots_exits_nonzero_with_a_clear_message(tmp_path, fake_checkout, replay):
    config = _staged_smoke(tmp_path, fake_checkout, rfd3_hotspots=None, hotspots=None)
    proc = replay(config, fake_checkout, tmp_path)
    text = proc.stdout + proc.stderr
    assert proc.returncode != 0, text[-1500:]
    assert "RFD3 needs hotspot residues" in text
    assert '"rfd3": false' in text
    assert not (fake_checkout / "runs" / "CALCA_smoke" / "run_rfd3.sh").exists()
    assert not (fake_checkout / "runs" / "CALCA_smoke" / "run_all.sh").exists(), "nothing may be generated"


def test_control_the_shipped_smoke_config_replays_because_it_carries_rfd3_hotspots(tmp_path, fake_checkout, replay):
    config = _staged_smoke(tmp_path, fake_checkout)
    proc = replay(config, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1500:]
    script = (fake_checkout / "runs" / "CALCA_smoke" / "run_rfd3.sh").read_text()
    assert "infer_ori_strategy: hotspots" in script and "select_hotspots:" in script


# ------------------------------------------------------------------ the wizard prompt


def test_the_wizard_cannot_answer_the_rfd3_hotspot_prompt_with_nothing():
    assert conf.validate_hotspots_required("") is not True
    assert conf.validate_hotspots_required("  ") is not True
    assert conf.validate_hotspots_required("56,60-62") is True
    assert conf.validate_hotspots_required("A56") is not True, "format errors still come from validate_hotspots"


def test_the_wizard_actually_asks_it_when_step_3_left_hotspots_blank():
    """The validator alone proves nothing if the prompt that uses it is deleted: find the call."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(conf.wizard))
    asks = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "ask"
        and any(
            k.arg == "validator" and isinstance(k.value, ast.Name) and k.value.id == "validate_hotspots_required"
            for k in n.keywords
        )
    ]
    assert len(asks) == 1, "the wizard must ask for RFD3 hotspots, with the required-hotspots validator, exactly once"


def test_the_template_does_not_promise_a_com_fallback():
    text = (REPO / "binderscout_examples" / "run_rfd3.sh.template").read_text().lower()
    assert "falls back to target com" not in text
    assert "falls back to com" not in text
