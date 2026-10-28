"""A tool can be "enabled" and generate nothing, and nothing said so.

PXDesign is the one tool with a MODE on top of its switch, and the two halves were
gated on different keys: the generator on `pxdesign_local`, a headless config's
obvious spelling being `pxdesign`. So `pxdesign: true` in a --config replay wrote no
run_pxdesign.sh, printed no warning, and did not appear in the "Tools:" line either
-- the operator's only clue was an absence from a list whose length they would have
to already know. The campaign that found it ran six tools believing it ran seven.

Two layers are pinned here: the INSTANCE (the mode is inferred from the evidence),
and the CLASS (any enabled tool the generator has no writer for is refused before a
file is written, and again from the filesystem afterwards).
"""

import ast
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

ROOT = Path(__file__).resolve().parents[2]

PDB = "".join(
    f"ATOM  {i:5d}  CA  ALA A {i:3d}       0.000   0.000   0.000  1.00  0.00           C\n" for i in range(1, 6)
)


def _cfg(tmp_path, tools, extra=None):
    pdb = tmp_path / "t.pdb"
    pdb.write_text(PDB)
    cfg = {
        "name": "T",
        "run_dir": str(tmp_path / "run"),
        "target_pdb_src": str(pdb),
        "target_sequence": "AAAAA",
        "chains": "A",
        "hotspots": None,
        "min_length": 20,
        "max_length": 30,
        "n_designs": 1,
        "pxdesign_binder_length": 25,
    }
    cfg.update(extra or {})
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"config_version": 1, "tools_enabled": tools, "cfg": cfg}))
    return p


# ------------------------------------------------------------------ the instance


def test_pxdesign_true_alone_infers_a_local_run(tmp_path, capsys):
    tools = {"pxdesign": True}
    conf._default_pxdesign_mode(tools, {})
    assert tools["pxdesign_local"] is True
    out = capsys.readouterr().out
    assert "without a mode" in out, "inferring silently is the bug one layer down"
    assert "pxdesign_local" in out


def test_pxdesign_with_an_output_dir_infers_an_import(tmp_path, capsys):
    """The shape that defaulting unconditionally to local would have BROKEN.

    `{pxdesign: true}` plus pxdesign_output_dir is unambiguously an import, and
    forcing local mode then hard-fails preflight on local mode's required keys --
    turning a config that worked into one that does not.
    """
    tools = {"pxdesign": True}
    conf._default_pxdesign_mode(tools, {"pxdesign_output_dir": "/elsewhere/pxdesign"})
    assert tools["pxdesign_import"] is True
    assert not tools.get("pxdesign_local")
    assert "IMPORT" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["pxdesign_local", "pxdesign_import"])
def test_an_explicit_mode_always_wins(mode):
    """The wizard sets all three keys, so this must stay a no-op there."""
    tools = {"pxdesign": True, mode: True}
    conf._default_pxdesign_mode(tools, {"pxdesign_output_dir": "/elsewhere"})
    other = "pxdesign_import" if mode == "pxdesign_local" else "pxdesign_local"
    assert tools[mode] is True
    assert not tools.get(other)


def test_pxdesign_not_enabled_is_untouched():
    tools = {"bindcraft": True}
    conf._default_pxdesign_mode(tools, {"pxdesign_output_dir": "/elsewhere"})
    assert "pxdesign_local" not in tools
    assert "pxdesign_import" not in tools


def test_the_replay_path_actually_writes_the_script(tmp_path, monkeypatch, capsys):
    """End to end, because the bug was a missing run_pxdesign.sh, not a missing flag."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(conf, "_missing_tool_assets", lambda cfg, tools: [])
    cfg_path = _cfg(tmp_path, {"pxdesign": True})
    conf.cmd_from_config(str(cfg_path), run_now=False)
    assert (tmp_path / "run" / "run_pxdesign.sh").is_file()


# -------------------------------------------------------------------- the class


def _keys_generate_branches_on() -> set[str]:
    """tools_enabled keys that generate()'s own source gates a write on.

    Re-derived from the AST rather than compared against a second hand list,
    because a hand list is how the drift this file exists for happened in the
    first place.
    """
    src = (ROOT / "configurator" / "configurator.py").read_text()
    tree = ast.parse(src)
    gen = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "generate")
    keys: set[str] = set()
    for node in ast.walk(gen):
        if not isinstance(node, ast.If):
            continue
        call = node.test
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "get"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "tools_enabled"
            and call.args
            and isinstance(call.args[0], ast.Constant)
        ):
            # Only branches that actually write a run script: generate() also
            # branches on these keys merely to mkdir an output directory.
            body = ast.dump(node)
            if "write_run_" in body:
                keys.add(call.args[0].value)
    return keys


def test_the_writer_key_set_matches_what_generate_branches_on():
    """The registry preflight consults must equal the generator's real branches.

    If a tenth tool joins TOOL_SEQUENCE and generate() grows a writer for it, this
    fails until _SCRIPT_WRITER_KEYS is updated -- which is the point: the
    alternative is the preflight silently reporting a tool as ungeneratable, or
    silently accepting one it cannot generate.
    """
    derived = _keys_generate_branches_on()
    assert derived, "the AST walk found no writer branches — the derivation itself is broken"

    # The Evaluator is a writer branch that is deliberately NOT a TOOL_SEQUENCE entry:
    # it is not a design tool, it runs after all of them, and run_all.sh / run_pipeline
    # dispatch it separately. Named explicitly rather than filtered silently, so a
    # TENTH design tool that gets a writer and is left out of TOOL_SEQUENCE -- which
    # would make it invisible to run_all.sh, the preview tree and the "Tools:" line --
    # fails here instead of shipping.
    sequence_keys = {k for k, *_ in conf.TOOL_SEQUENCE}
    outside = derived - sequence_keys
    assert outside == {"evaluator"}, f"writer branches outside TOOL_SEQUENCE: {sorted(outside)}"

    derived &= sequence_keys
    assert derived == set(conf._SCRIPT_WRITER_KEYS), (
        f"_SCRIPT_WRITER_KEYS drifted from generate(): "
        f"only in generate(): {sorted(derived - set(conf._SCRIPT_WRITER_KEYS))}, "
        f"only in the set: {sorted(set(conf._SCRIPT_WRITER_KEYS) - derived)}"
    )


def test_every_tool_in_the_sequence_has_a_writer():
    """The enabled-tools list and the generator must cover the same tools.

    TOOL_SEQUENCE is what the UI calls "enabled" and what run_all.sh iterates; a
    key in it with no writer is a tool that is advertised and never runs.
    """
    missing = [k for k, *_ in conf.TOOL_SEQUENCE if k not in conf._SCRIPT_WRITER_KEYS]
    assert not missing, f"enabled-but-ungeneratable tools: {missing}"


def test_preflight_refuses_an_enabled_tool_with_no_writer(tmp_path, capsys, monkeypatch):
    """The class-level guard, exercised by inventing the drift."""
    monkeypatch.setattr(conf, "TOOL_SEQUENCE", [*conf.TOOL_SEQUENCE, ("ghost", "run_ghost.sh", "Ghost", "ghost")])
    monkeypatch.setattr(conf, "_missing_tool_assets", lambda cfg, tools: [])
    with pytest.raises(SystemExit) as exc:
        conf.preflight({"name": "T"}, {"ghost": True})
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "no writer for" in out
    assert "run_ghost.sh" in out
    assert "configurator bug, not a problem with your config" in out


def test_the_post_write_check_catches_a_writer_that_wrote_nothing(tmp_path, capsys):
    """Defence in depth: preflight asks the registry, this asks the filesystem.

    A writer branch that exists but silently produces no file -- an early return, a
    path built wrong -- passes preflight and would otherwise surface as run_all.sh
    invoking a script that is not there.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(SystemExit) as exc:
        conf.verify_enabled_tools_generated(run_dir, {"bindcraft": True})
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "no run script" in out
    assert "run_bindcraft.sh" in out


def test_the_post_write_check_passes_when_every_script_is_there(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_bindcraft.sh").write_text("#!/bin/sh\n")
    conf.verify_enabled_tools_generated(run_dir, {"bindcraft": True})


def test_generate_itself_consults_the_post_write_check(tmp_path, monkeypatch, capsys):
    """The call site, not just the function.

    The function passing in isolation says nothing about whether generate() runs it:
    deleting the call left every direct test of verify_enabled_tools_generated green.
    So break a writer -- make it write nothing, the exact failure the check exists
    for -- and require generate() to refuse.
    """
    monkeypatch.setattr(conf, "_missing_tool_assets", lambda cfg, tools: [])
    monkeypatch.setattr(conf, "write_bindcraft_target", lambda *a, **k: None)
    monkeypatch.setattr(conf, "copy_bindcraft_preset", lambda *a, **k: None)
    monkeypatch.setattr(conf, "write_run_bindcraft", lambda *a, **k: None)  # writes nothing

    pdb = tmp_path / "t.pdb"
    pdb.write_text(PDB)
    cfg = {
        "name": "T",
        "run_dir": tmp_path / "run",
        "target_pdb_src": str(pdb),
        "target_sequence": "AAAAA",
        "chains": "A",
        "hotspots": None,
        "min_length": 20,
        "max_length": 30,
        "n_designs": 1,
        "filter_preset": "no_filters",
        "advanced_preset": "default_4stage_multimer",
    }
    with pytest.raises(SystemExit) as exc:
        conf.generate(cfg, {"bindcraft": True})
    assert exc.value.code == 1
    assert "no run script" in capsys.readouterr().out
