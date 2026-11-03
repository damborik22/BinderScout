"""A generated run folder must work where it is, not where it was generated.

Generated scripts and config.json baked the generating machine's absolute run folder,
checkout and conda base, so a moved or copied run folder silently kept operating on
the OLD location (and a folder with a space, `$` or `'` in its path broke the
unquoted interpolations).

Nothing here runs a design tool. Each script's self-locating header (everything up to
LOCATE_BLOCK_END) is cut out, placed in the run folder under a probe name, and run from
an unrelated cwd; that executes exactly the lines that decide where the script thinks it
is, and nothing after them.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "examples" / "CALCA" / "smoke.json"
END = "# -- end of locate block --"

# Scripts that read a config file with absolute paths inside it, and so refuse after a move.
READS_TOOL_CONFIG = {
    "run_bindcraft.sh",
    "run_bindcraft2.sh",
    "run_boltzgen.sh",
    "run_mosaic.sh",
    "run_pxdesign.sh",
}
# Scripts that locate themselves and build every path from RUN_DIR / BINDERSCOUT_DIR.
SELF_CONTAINED = {
    "run_all.sh",
    "run_evaluate.sh",
    "run_proteina_complexa.sh",
    "run_protein_hunter.sh",
    "run_rfd3.sh",
}

AWKWARD = "it's a $HOME run"  # a space, a single quote and a dollar sign


def _generate(tmp_path, fake_checkout, replay, run_dir: Path) -> None:
    payload = json.loads(SMOKE.read_text())
    payload["cfg"]["run_dir"] = str(run_dir)
    payload["cfg"]["target_pdb_src"] = str(REPO / "examples" / "CALCA" / "target.pdb")
    config = tmp_path / "smoke_copy.json"
    config.write_text(json.dumps(payload))
    proc = replay(config, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def _header(script: Path) -> str:
    text = script.read_text()
    assert END in text, f"{script.name} has no self-locating header"
    return text[: text.index(END) + len(END)] + "\n"


def _probe(script: Path, checkout: Path, cwd: Path) -> subprocess.CompletedProcess:
    """Run only the header of `script`, as if it lived in its folder."""
    probe = script.parent / f"_probe_{script.name}"
    probe.write_text(_header(script) + 'echo "RUN_DIR=$RUN_DIR"\necho "BINDERSCOUT_DIR=$BINDERSCOUT_DIR"\n')
    try:
        return subprocess.run(
            ["bash", str(probe)],
            capture_output=True,
            text=True,
            cwd=cwd,
            env={"PATH": "/usr/bin:/bin", "HOME": str(cwd), "BINDERSCOUT_DIR": str(checkout)},
        )
    finally:
        probe.unlink()


@pytest.fixture
def moved(tmp_path, fake_checkout, replay):
    """(old_dir, new_dir): a replayed smoke run, then the folder moved elsewhere."""
    old = tmp_path / AWKWARD / "CALCA_smoke"
    _generate(tmp_path, fake_checkout, replay, old)
    new = tmp_path / "somewhere else" / "CALCA_smoke"
    new.parent.mkdir()
    shutil.move(str(old), str(new))
    return old, new


def test_every_script_is_classified():
    """A new run script must be added to one of the two sets above, deliberately."""
    assert READS_TOOL_CONFIG.isdisjoint(SELF_CONTAINED)


def test_no_script_names_the_location_it_was_generated_in(tmp_path, fake_checkout, replay):
    old = tmp_path / AWKWARD / "CALCA_smoke"
    _generate(tmp_path, fake_checkout, replay, old)
    scripts = sorted(old.glob("run_*.sh"))
    assert {s.name for s in scripts} >= READS_TOOL_CONFIG | SELF_CONTAINED
    for script in scripts:
        text = script.read_text()
        assert str(old) not in text, f"{script.name} still bakes the run folder"
        assert str(old.parent) not in text, f"{script.name} still bakes the run folder's parent"
        assert str(fake_checkout / "BindCraft") not in text, f"{script.name} bakes a tool path under the checkout"
        assert text.count(str(fake_checkout)) <= 1, f"{script.name} bakes the checkout more than once"
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_every_script_finds_its_own_folder_wherever_it_is(moved, fake_checkout, tmp_path):
    _old, new = moved
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    for name in sorted(SELF_CONTAINED):
        proc = _probe(new / name, fake_checkout, elsewhere)
        assert proc.returncode == 0, f"{name}: {proc.stderr}"
        assert f"RUN_DIR={new}\n" in proc.stdout, f"{name} did not follow the folder: {proc.stdout!r}"


def test_a_script_reached_through_a_symlink_locates_the_real_folder(moved, fake_checkout, tmp_path):
    _old, new = moved
    real = new / "_probe_real.sh"
    real.write_text(_header(new / "run_rfd3.sh") + 'echo "RUN_DIR=$RUN_DIR"\n')
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    via = link_dir / "run_rfd3.sh"
    via.symlink_to(real)
    proc = subprocess.run(
        ["bash", str(via)],
        capture_output=True,
        text=True,
        cwd=link_dir,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "BINDERSCOUT_DIR": str(fake_checkout)},
    )
    assert proc.returncode == 0, proc.stderr
    assert f"RUN_DIR={new}\n" in proc.stdout


def test_scripts_that_read_a_tool_config_refuse_after_a_move_and_say_how_to_fix_it(moved, fake_checkout, tmp_path):
    old, new = moved
    for name in sorted(READS_TOOL_CONFIG):
        proc = _probe(new / name, fake_checkout, tmp_path)
        assert proc.returncode == 1, f"{name} carried on with configs that point at {old}"
        assert "not where its tool configs were generated" in proc.stderr
        assert str(old) in proc.stderr and str(new) in proc.stderr
        assert "binderscout configure --config" in proc.stderr


def test_regenerating_in_place_from_the_moved_config_json_fixes_it(moved, fake_checkout, replay, tmp_path):
    old, new = moved
    cfg_json = new / "config.json"
    saved = json.loads(cfg_json.read_text())
    assert saved["path_base"] == "config"
    assert saved["cfg"]["run_dir"] == "."
    assert not Path(saved["cfg"]["target_pdb"]).is_absolute()
    assert not Path(saved["cfg"]["target_pdb_src"]).is_absolute()

    proc = replay(cfg_json, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]

    for name in sorted(READS_TOOL_CONFIG):
        result = _probe(new / name, fake_checkout, tmp_path)
        assert result.returncode == 0, f"{name}: {result.stderr}"
        assert f"RUN_DIR={new}\n" in result.stdout
    campaign = (new / "bindcraft2" / "campaign.json").read_text()
    assert str(old) not in campaign
    assert json.loads(campaign)["project_folder"] == str(new / "bindcraft2")
    assert str(old) not in (new / "bindcraft" / "target_settings.json").read_text()


def test_a_missing_checkout_is_refused_with_a_message_not_followed(moved, tmp_path):
    _old, new = moved
    gone = tmp_path / "no such checkout"
    proc = _probe(new / "run_rfd3.sh", gone, tmp_path)
    assert proc.returncode == 1
    assert "no BinderScout checkout" in proc.stderr
    assert str(gone) in proc.stderr
