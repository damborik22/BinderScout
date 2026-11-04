"""Copying an example config and changing only `name` must not write into the example's folder.

`examples/CALCA/smoke.json` says `run_dir: runs/CALCA_smoke`. A copy that changed only
`name` kept that `run_dir`, so two differently named campaigns replayed into ONE folder
and overwrote each other's scripts, target copy and config.json. The run folder is now
derived from `name` when the two disagree, and one note says so.

Replayed as a subprocess by path, the way a user does (see conftest.py).
"""

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "examples" / "CALCA" / "smoke.json"
TARGET = REPO / "examples" / "CALCA" / "target.pdb"


def _copy(tmp_path: Path, filename: str, **cfg_over) -> Path:
    payload = json.loads(SMOKE.read_text())
    payload["cfg"]["target_pdb_src"] = str(TARGET)
    payload["cfg"].update(cfg_over)
    path = tmp_path / filename
    path.write_text(json.dumps(payload))
    return path


def test_the_shipped_example_still_writes_runs_calca_smoke(tmp_path, fake_checkout, replay):
    # The example's paths are relative to the checkout, so the example goes into it.
    shutil.copytree(REPO / "examples", fake_checkout / "examples")
    proc = replay(fake_checkout / "examples" / "CALCA" / "smoke.json", fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert (fake_checkout / "runs" / "CALCA_smoke" / "config.json").is_file()
    assert "derived from the name" not in proc.stdout, "the shipped example must not trigger the rename note"


def test_two_copies_with_different_names_make_two_folders(tmp_path, fake_checkout, replay):
    for name in ("alpha", "beta"):
        proc = replay(_copy(tmp_path, f"{name}.json", name=name), fake_checkout, tmp_path)
        assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
        assert "derived from the name" in proc.stdout, "the change of folder must be announced"
    runs = fake_checkout / "runs"
    assert (runs / "alpha" / "config.json").is_file()
    assert (runs / "beta" / "config.json").is_file()
    assert not (runs / "CALCA_smoke").exists(), "a renamed copy still wrote into the example's folder"
    saved = {n: json.loads((runs / n / "config.json").read_text())["cfg"]["name"] for n in ("alpha", "beta")}
    assert saved == {"alpha": "alpha", "beta": "beta"}


def test_the_note_names_both_folders(tmp_path, fake_checkout, replay):
    proc = replay(_copy(tmp_path, "gamma.json", name="gamma"), fake_checkout, tmp_path)
    assert str(fake_checkout / "runs" / "CALCA_smoke") in proc.stdout
    assert str(fake_checkout / "runs" / "gamma") in proc.stdout


def test_a_matching_name_is_silent(tmp_path, fake_checkout, replay):
    cfg = _copy(tmp_path, "same.json", name="same", run_dir="runs/same")
    proc = replay(cfg, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert "derived from the name" not in proc.stdout
    assert (fake_checkout / "runs" / "same" / "config.json").is_file()


def test_a_config_inside_its_own_run_folder_replays_onto_itself_even_if_renamed(tmp_path, fake_checkout, replay):
    """A generated config.json says run_dir '.', so a renamed run folder must regenerate in place."""
    first = replay(_copy(tmp_path, "orig.json", name="orig"), fake_checkout, tmp_path)
    assert first.returncode == 0, (first.stdout + first.stderr)[-2000:]
    old = fake_checkout / "runs" / "orig"
    new = fake_checkout / "runs" / "renamed_folder"
    old.rename(new)
    proc = replay(new / "config.json", fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert "derived from the name" not in proc.stdout
    assert (new / "run_all.sh").is_file()
    assert not old.exists(), "replaying a renamed run folder must not resurrect the old name beside it"


def test_the_rename_note_reads_as_information_not_as_an_error(tmp_path, fake_checkout, replay):
    """The behaviour is right and the usual cause is a copied config; the old wording
    ('run_dir ends in X but name is Y') was a yellow warning that read like a mistake."""
    proc = replay(_copy(tmp_path, "delta.json", name="delta"), fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    out = proc.stdout
    assert "derived from the name" in out, "control: the note was printed"
    assert "⚠" not in out.split("derived from the name")[0].splitlines()[-1], "the note is a warning again"
    assert "ends in" not in out and "but name is" not in out, "the old error-shaped wording is back"
    assert "Nothing is wrong with the config" in out
    assert str(fake_checkout / "runs" / "delta") in out
