"""`trim_construct_tag` lets a --config replay accept the wizard's expression-tag trim.

The wizard offers to trim a purification tag from the target in Step 3. A headless replay
never asked, so a public target (5O45's AAALE + His6 here) kept its tag as designable
surface and in the target-MSA cache key. The config key answers that offer. `false` and
absent keep the sequence as written, which is what a replay did before the key existed.

Replayed as a subprocess by path, the way a user does (see conftest.py).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "examples" / "CALCA" / "smoke.json"

NATIVE = "ITVKVNAPY"
TAG = "AAALE" + "HHHHHH"
FIRST = 126  # the tag lands on 135-145, as deposited

_ONE_TO_THREE: dict = {}
for _three, _one in conf.AA3TO1.items():
    _ONE_TO_THREE.setdefault(_one, _three)


def _atom(serial, res, resnum):
    return (
        f"ATOM  {serial:5d}  CA {res:>4s} A{resnum:4d}    "
        f"{1.0:8.3f}{2.0:8.3f}{3.0:8.3f}{1.00:6.2f}{0.00:6.2f}           C  "
    )


def _seqadv(res, resnum):
    head = f"SEQADV TEST {res:>3s} A {resnum:4d} "
    return f"{head:<49s}{'EXPRESSION TAG':<21s}"


def _tagged_pdb(path: Path) -> Path:
    lines, atoms = ["HEADER    TEST"], []
    for i, one in enumerate(NATIVE + TAG):
        num = FIRST + i
        if i >= len(NATIVE):
            lines.append(_seqadv(_ONE_TO_THREE[one], num))
        atoms.append(_atom(len(atoms) + 1, _ONE_TO_THREE[one], num))
    path.write_text("\n".join(lines + atoms + ["END"]) + "\n")
    return path


def _config(tmp_path: Path, name: str, structure: Path, **cfg_over) -> Path:
    payload = json.loads(SMOKE.read_text())
    payload["tools_enabled"] = {"bindcraft2": True}
    payload["cfg"].update(
        {
            "name": name,
            "run_dir": f"runs/{name}",
            "target_pdb_src": str(structure),
            "target_sequence": NATIVE + TAG,
            "hotspots": None,
            **cfg_over,
        }
    )
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload))
    return path


def _saved(checkout: Path, name: str) -> dict:
    return json.loads((checkout / "runs" / name / "config.json").read_text())["cfg"]


def _prepared_sequence(checkout: Path, name: str) -> str:
    return conf.extract_sequence_from_pdb(str(checkout / "runs" / name / "target" / f"{name}.pdb"), "A")


@pytest.fixture
def structure(tmp_path):
    return _tagged_pdb(tmp_path / "tagged.pdb")


def test_true_trims_the_sequence_and_the_coordinates(tmp_path, fake_checkout, replay, structure):
    proc = replay(_config(tmp_path, "on", structure, trim_construct_tag=True), fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert _saved(fake_checkout, "on")["target_sequence"] == NATIVE
    assert _prepared_sequence(fake_checkout, "on") == NATIVE, "the coordinates still carry the tag"
    assert "SEQADV" in proc.stdout, "the evidence for the trim must be shown"
    assert "trim_construct_tag" in proc.stdout


def test_false_keeps_the_tag(tmp_path, fake_checkout, replay, structure):
    proc = replay(_config(tmp_path, "off", structure, trim_construct_tag=False), fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert _saved(fake_checkout, "off")["target_sequence"] == NATIVE + TAG
    assert _prepared_sequence(fake_checkout, "off") == NATIVE + TAG


def test_absent_is_the_old_behaviour_and_names_the_key_in_its_warning(tmp_path, fake_checkout, replay, structure):
    proc = replay(_config(tmp_path, "dflt", structure), fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert _saved(fake_checkout, "dflt")["target_sequence"] == NATIVE + TAG
    assert "trim_construct_tag" in proc.stdout, "the tag warning must name the key that fixes it"
    assert "KEEPS 11 residue(s)" in proc.stdout


def test_true_extracts_the_sequence_when_the_config_has_none(tmp_path, fake_checkout, replay, structure):
    cfg = _config(tmp_path, "noseq", structure, trim_construct_tag=True)
    payload = json.loads(cfg.read_text())
    del payload["cfg"]["target_sequence"]
    cfg.write_text(json.dumps(payload))
    proc = replay(cfg, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert _saved(fake_checkout, "noseq")["target_sequence"] == NATIVE


def test_the_generated_config_replays_without_trimming_further(tmp_path, fake_checkout, replay, structure):
    first = replay(_config(tmp_path, "twice", structure, trim_construct_tag=True), fake_checkout, tmp_path)
    assert first.returncode == 0, (first.stdout + first.stderr)[-2000:]
    again = replay(fake_checkout / "runs" / "twice" / "config.json", fake_checkout, tmp_path)
    assert again.returncode == 0, (again.stdout + again.stderr)[-2000:]
    assert _saved(fake_checkout, "twice")["target_sequence"] == NATIVE


def test_true_on_a_target_with_no_tag_changes_nothing_and_says_so(tmp_path, fake_checkout, replay):
    structure = tmp_path / "clean.pdb"
    structure.write_text(
        "\n".join([_atom(i + 1, _ONE_TO_THREE[o], 1 + i) for i, o in enumerate("MKTAYIAKQRQ")] + ["END"]) + "\n"
    )
    cfg = _config(tmp_path, "clean", structure, trim_construct_tag=True, target_sequence="MKTAYIAKQRQ")
    proc = replay(cfg, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert _saved(fake_checkout, "clean")["target_sequence"] == "MKTAYIAKQRQ"
    assert "no expression tag detected" in proc.stdout


@pytest.mark.parametrize("bad", ["yes", 1, "true"])
def test_a_non_boolean_is_refused_not_guessed(tmp_path, fake_checkout, replay, structure, bad):
    proc = replay(_config(tmp_path, "bad", structure, trim_construct_tag=bad), fake_checkout, tmp_path)
    assert proc.returncode == 1
    assert "trim_construct_tag must be true or false" in proc.stdout
    assert not (fake_checkout / "runs" / "bad").exists(), "nothing may be generated from a config that is refused"


def test_the_key_is_a_known_cfg_key():
    """Otherwise the replay would warn that it does not recognise a documented key."""
    assert "trim_construct_tag" in conf.known_cfg_keys()
