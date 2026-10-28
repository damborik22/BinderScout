"""Three ways a headless `--config` replay produced something other than it said.

All three were found by running real campaigns, and all three are silent -- the
operator's evidence arrives as a GPU bill, a 15-hour tool, or an empty shortlist.

BUG-18  `n_designs: 1` carried `--num_designs 10000`, because the intermediate
        pool defaulted to a flat 10 000 and was never reconciled with the request.
        Measured on an RTX 3090: 1000 dataloader steps at ~53 s/step, ETA 14 h 53 m,
        for one requested design, while every other tool honoured the count.
BUG-13  run_evaluate.sh adapts to the engines installed but not to the GATE that
        depends on them, so on any host without the gated AF3 weights every design
        failed a 3-engine gate and the shortlist came back empty with no error.
BUG-22  An unrecognised key was silently ignored and the built-in default used
        instead -- then written straight back out by write_run_config, so the typo
        became a permanent property of the run folder.
"""

import ast
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf


def _cfg(**over):
    cfg = {
        "name": "T",
        "min_length": 20,
        "max_length": 30,
        "n_designs": 1,
        "chains": "A",
        "hotspots": None,
        "target_sequence": "AAAAA",
    }
    cfg.update(over)
    return cfg


# ------------------------------------------------------- BUG-18: one budget, not three


def test_the_pool_scales_with_the_request():
    """One design must not imply ten thousand."""
    assert conf.boltzgen_intermediate(_cfg(n_designs=1)) == 100
    assert conf.boltzgen_intermediate(_cfg(n_designs=10)) == 1000
    assert conf.boltzgen_intermediate(_cfg(n_designs=100)) == 10000


def test_the_pool_has_a_floor():
    """Filtering still needs something to filter, so the pool cannot follow the
    request all the way down."""
    assert conf.boltzgen_intermediate(_cfg(n_designs=1)) >= 50
    assert conf.boltzgen_intermediate_default(0) == 50


def test_an_explicit_pool_still_wins():
    """The key stays an override for anyone who knows they want a production pool."""
    assert conf.boltzgen_intermediate(_cfg(n_designs=1, boltzgen_intermediate=10000)) == 10000


def test_the_per_tool_budget_override_is_honoured():
    """The whole point of prompting for it.

    `--budget` and settings.json's "budget" both read cfg["n_designs"] directly and
    ignored cfg["boltzgen_budget"] -- the per-tool override the wizard explicitly
    asks for -- while the YAML header comment and the Step-8 summary DID consult it.
    So a wizard run with budget 20 over a global count of 10 showed the operator 20
    and passed BoltzGen 10.
    """
    assert conf.boltzgen_budget(_cfg(n_designs=10, boltzgen_budget=20)) == 20
    assert conf.boltzgen_budget(_cfg(n_designs=10)) == 10
    # And the pool follows the override, not the global count.
    assert conf.boltzgen_intermediate(_cfg(n_designs=10, boltzgen_budget=20)) == 2000


def test_every_emitted_budget_is_the_same_number(tmp_path):
    """The three emission sites must not be able to disagree again.

    They are the executed `--budget`, settings.json's "budget" (the reproducibility
    record CLAUDE.md's convention requires) and the YAML header's documented run
    line. A reader who checks one and trusts the others was wrong before this.
    """
    cfg = _cfg(
        n_designs=10,
        boltzgen_budget=20,
        run_dir=tmp_path,
        target_pdb=tmp_path / "t.pdb",
        target_sequence="AAAAA",
        boltzgen_mode="protein",
    )
    script = tmp_path / "run_boltzgen.sh"
    conf.write_run_boltzgen(script, cfg)
    yaml = tmp_path / "config.yaml"
    conf.write_boltzgen_yaml(yaml, cfg)

    body = script.read_text() + yaml.read_text()
    assert "--budget 20" in body
    assert '"budget": 20' in body
    assert "--budget 10" not in body, "the executed budget still ignores the override"
    assert body.count("--num_designs 2000") == 2, "the pool must agree between the script and the YAML header"


def test_the_cost_is_stated_in_hours_not_in_designs():
    """A count of designs is not a cost; the operator cannot price it.

    evaluate.sh already states its GPU costs before spending them rather than
    reporting them afterwards. This is the same thing one prompt earlier -- and the
    intermediate pool IS the BoltzGen runtime.
    """
    note = conf.boltzgen_cost_note(10000)
    assert "10,000 intermediate designs" in note
    assert "~15 h" in note, note
    assert "min" in conf.boltzgen_cost_note(100), "a short pool must read in minutes, not 0 h"


# ------------------------------------------------------------- BUG-13: --min-engines


def _evaluate_script(tmp_path, cfg_over=None, tools=None):
    cfg = _cfg(run_dir=tmp_path, target_sequence="AAAAA", **(cfg_over or {}))
    path = tmp_path / "run_evaluate.sh"
    conf.write_run_evaluate(path, cfg, tools or {"evaluator": True, "bindcraft": True})
    return path.read_text()


def test_min_engines_is_emitted_when_the_operator_chose_it(tmp_path):
    assert "--min-engines 2" in _evaluate_script(tmp_path, {"min_engines": 2})


def test_min_engines_is_absent_by_default(tmp_path):
    """Absent means evaluate.sh keeps its own default of 3.

    The gate must NOT be derived from the engines this host happens to have:
    deriving it would make two operators with the same designs produce different
    rankings, which is the property the single ranking exists to guarantee
    (CLAUDE.md, Part U).
    """
    body = _evaluate_script(tmp_path)
    assert "--min-engines" not in body


@pytest.mark.parametrize("value", [0, None, False])
def test_a_falsy_gate_is_not_emitted(tmp_path, value):
    """`--min-engines 0` is not a gate, and evaluate.sh's floor is 2."""
    assert "--min-engines" not in _evaluate_script(tmp_path, {"min_engines": value})


def test_the_wizard_offers_the_gate_only_where_it_bites():
    """Prompted at two engines, refused at one, silent at three.

    Checked against the wizard's source rather than by driving ~80 prompts: what
    matters is that both shortfall branches exist and that neither lowers the gate
    without asking.
    """
    src = (Path(conf.__file__).parent / "configurator.py").read_text()
    tree = ast.parse(src)
    wizard = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "wizard")
    body = ast.dump(wizard)
    assert "min_engines" in body, "the wizard must record the answer in cfg"
    assert "Only 2 refold engines selected" in src
    assert "Only 1 refold engine selected" in src
    # The one-engine branch must NOT offer to lower the gate: the floor is 2, so
    # there is no value that produces a shortlist and offering one would be a lie.
    one_engine = src[src.index("Only 1 refold engine selected") :]
    one_engine = one_engine[: one_engine.index("─")]
    assert "ask_yn" not in one_engine, "a single engine cannot meet any gate — do not offer to lower it"


# ----------------------------------------------------------- BUG-22: unknown cfg keys


def _config_file(tmp_path, cfg, tools=None):
    pdb = tmp_path / "t.pdb"
    pdb.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n")
    payload = {
        "config_version": 1,
        "tools_enabled": tools or {"bindcraft": True},
        "cfg": {"name": "T", "run_dir": str(tmp_path / "run"), "target_pdb_src": str(pdb), **cfg},
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(payload))
    return p


def test_an_unread_key_is_fatal_not_ignored(tmp_path, capsys):
    """The campaign config said `pxdesign_n_designs: 1` and got 1000.

    Plausible, because `bindcraft_n_designs` is real -- but the writer reads
    `pxdesign_n_samples`, so the key was dropped and PXDesign ran its 1000-sample
    default: ~1000x the requested GPU work, with the only symptom being 1000 of 1003
    sequences arriving at the evaluator hours later.
    """
    path = _config_file(tmp_path, {"pxdesign_n_designs": 1})
    with pytest.raises(SystemExit) as exc:
        conf.load_run_config(path)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "pxdesign_n_designs" in out
    assert "default is used instead" in out, "say what happens, not just that the key is unknown"


def test_the_near_miss_is_suggested(tmp_path, capsys):
    path = _config_file(tmp_path, {"pxdesign_n_designs": 1})
    with pytest.raises(SystemExit):
        conf.load_run_config(path)
    assert "pxdesign_n_samples" in capsys.readouterr().out, "the real key must be among the suggestions"


def test_underscore_keys_are_exempt(tmp_path):
    """`_comment` is written by this module and is meant to be inert."""
    path = _config_file(tmp_path, {"_comment": "anything", "_note": "also fine"})
    cfg, _tools = conf.load_run_config(path)
    assert cfg["_comment"] == "anything"


def test_a_real_key_passes(tmp_path):
    path = _config_file(tmp_path, {"min_length": 20, "max_length": 30, "n_designs": 1})
    cfg, _tools = conf.load_run_config(path)
    assert cfg["n_designs"] == 1


def test_the_valid_key_set_comes_from_the_source_not_a_list():
    """A hand list is how `pxdesign_n_samples` and `bindcraft_n_designs` came to be
    siblings with different suffixes in the first place."""
    known = conf.known_cfg_keys()
    assert "pxdesign_n_samples" in known
    assert "n_designs" in known
    assert "min_engines" in known, "a key the writer reads must be accepted by the validator"
    assert "pxdesign_n_designs" not in known


def test_the_repo_s_own_example_replays():
    """The example is the thing a new user copies, so it has to survive its own
    validator. It did not: `boltzgen_n_designs: 1` is read nowhere in either branch,
    and `boltzgen_intermediate: false` was indexed unconditionally and emitted
    `--num_designs False` -- a Python literal in the JSON reproducibility record.
    """
    example = Path(conf.__file__).resolve().parents[1] / "examples" / "CALCA" / "smoke.json"
    cfg = json.loads(example.read_text())["cfg"]
    unknown = sorted(k for k in cfg if k not in conf.known_cfg_keys() and not k.startswith("_"))
    assert not unknown, f"{example.name} carries keys the configurator does not read: {unknown}"
