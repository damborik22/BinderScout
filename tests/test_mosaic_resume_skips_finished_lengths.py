"""A Mosaic re-run restarted from the first length. `--resume` now skips what already finished.

The template needs jax and Boltz-2 to import, so the two decision functions are lifted out of its source
and run on their own; a separate check reads main() to make sure the loop actually uses them (a helper
that is right but never called changes nothing).
"""

import ast
import csv
import json
import os
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "binderscout_examples" / "hallucinate_binderscout.py"
SRC = TEMPLATE.read_text()
TARGET = "ACDEFGHIKL"


def _load():
    tree = ast.parse(SRC)
    wanted = {"_length_already_designed", "_usable_checkpoint", "_load_checkpoint"}
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {f.name for f in funcs} == wanted
    ns = {"os": os, "csv": csv, "json": json}
    exec(compile(ast.Module(funcs, []), str(TEMPLATE), "exec"), ns)
    return ns


NS = _load()


def _write_designs(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["worker_id", "binder_length", "target_sequence"])
        w.writeheader()
        w.writerows(rows)


def test_a_length_with_rows_for_this_target_is_finished(tmp_path):
    p = tmp_path / "designs.csv"
    _write_designs(p, [{"worker_id": "a", "binder_length": "65", "target_sequence": TARGET}])
    assert NS["_length_already_designed"](65, TARGET, str(p))
    assert not NS["_length_already_designed"](70, TARGET, str(p)), "another length is not finished"
    assert not NS["_length_already_designed"](65, "OTHER", str(p)), "another target's rows do not count"


def test_no_file_or_an_empty_one_is_not_finished(tmp_path):
    assert not NS["_length_already_designed"](65, TARGET, str(tmp_path / "missing.csv"))
    (tmp_path / "empty.csv").write_text("")
    assert not NS["_length_already_designed"](65, TARGET, str(tmp_path / "empty.csv"))


def test_a_float_formatted_length_still_matches(tmp_path):
    p = tmp_path / "designs.csv"
    _write_designs(p, [{"worker_id": "a", "binder_length": "65.0", "target_sequence": TARGET}])
    assert NS["_length_already_designed"](65, TARGET, str(p))


def _ckpt(path, **over):
    data = {
        "interrupted": False,
        "binder_length": 65,
        "n_designs": 8,
        "target_sequence": TARGET,
        "candidates": [["MK", 0.1, 0]],
    }
    data.update(over)
    path.write_text(json.dumps(data))
    return str(path)


def test_only_a_complete_matching_checkpoint_is_reused(tmp_path):
    ok = NS["_usable_checkpoint"]
    assert ok(_ckpt(tmp_path / "c.json"), 65, TARGET, 8)
    assert not ok(_ckpt(tmp_path / "c.json", interrupted=True), 65, TARGET, 8), "a partial list would under-deliver"
    assert not ok(_ckpt(tmp_path / "c.json", n_designs=100), 65, TARGET, 8)
    assert not ok(_ckpt(tmp_path / "c.json", target_sequence="OTHER"), 65, TARGET, 8)
    assert not ok(_ckpt(tmp_path / "c.json", binder_length=70), 65, TARGET, 8)
    assert not ok(_ckpt(tmp_path / "c.json", candidates=[]), 65, TARGET, 8)
    assert not ok(str(tmp_path / "missing.json"), 65, TARGET, 8)
    (tmp_path / "bad.json").write_text("{not json")
    assert not ok(str(tmp_path / "bad.json"), 65, TARGET, 8)
    # the SIGINT handler's checkpoint has none of the identifying keys
    (tmp_path / "sig.json").write_text(json.dumps({"interrupted": True, "candidates": [["MK", 0.1]]}))
    assert not ok(str(tmp_path / "sig.json"), 65, TARGET, 8)


def test_main_uses_both_helpers_behind_the_flag():
    """Mutating the CALL SITE: the helpers being right is not the loop using them."""
    main = next(n for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = ast.get_source_segment(SRC, main)
    assert '"--resume" in sys.argv[1:]' in body
    assert "_length_already_designed(binder_length, target_sequence)" in body
    assert "_usable_checkpoint(ckpt_path, binder_length, target_sequence, n_designs)" in body
    assert "resume_from=resume_from" in body
    assert body.index("if resume:") < body.index("_length_already_designed(") < body.index("result = design(")


def test_the_generated_script_forwards_its_arguments(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "configurator"))
    import configurator as conf
    from tests.configurator.test_pxdesign_and_complexa_scripts_start_on_aarch64 import _cfg

    out = tmp_path / "run_mosaic.sh"
    conf.write_run_mosaic(out, {**_cfg(tmp_path), "n_designs": 8})
    assert '"$MOSAIC_PYTHON" hallucinate.py "$@"' in out.read_text()


def test_a_current_checkpoint_can_be_loaded_and_keeps_its_generation_index(tmp_path):
    """_load_checkpoint unpacked exactly two values, but every checkpoint design() writes holds three
    (sequence, loss, generation_index), so resuming from any of them raised before refolding began."""
    path = _ckpt(tmp_path / "c.json", candidates=[["MK", 0.25, 7], ["AG", None, 2]])
    loaded = NS["_load_checkpoint"](path)["candidates"]
    assert loaded[0] == ("MK", 0.25, 7)
    assert loaded[1][0] == "AG" and loaded[1][2] == 2 and loaded[1][1] != loaded[1][1], "a null loss becomes NaN"


def test_an_old_two_value_checkpoint_still_loads(tmp_path):
    path = _ckpt(tmp_path / "old.json", candidates=[["MK", 0.25]])
    assert NS["_load_checkpoint"](path)["candidates"] == [("MK", 0.25)]
