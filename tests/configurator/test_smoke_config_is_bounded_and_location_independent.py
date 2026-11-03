"""The documented demo must be bounded for every tool and must replay from any cwd.

Two defects in `examples/CALCA/smoke.json`, the one thing a new user is told to run:

1. It produced an UNBOUNDED BindCraft 2 campaign. `number_of_final_designs` there is
   a quota of ACCEPTED designs and `max_trajectories` is the only cap in the package,
   so the demo ran until it filled its quota however long that took. PXDesign (1000
   samples) and Proteina-Complexa (100 designs) were also nowhere near "smallest".
2. Its relative paths (`runs/...`, `examples/CALCA/target.pdb`) resolved against the
   caller's cwd, so the replay died with "Target structure not found" from anywhere
   but the repo root.
"""

import json
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "examples" / "CALCA" / "smoke.json"


def _stage_example(root: Path) -> Path:
    """Copy the shipped config and its target into a checkout, keeping their relative layout."""
    ex = root / "examples" / "CALCA"
    ex.mkdir(parents=True)
    shutil.copy2(SMOKE, ex / "smoke.json")
    shutil.copy2(SMOKE.parent / "target.pdb", ex / "target.pdb")
    return ex / "smoke.json"


def test_the_shipped_config_uses_repo_relative_paths_that_exist():
    cfg = json.loads(SMOKE.read_text())["cfg"]
    assert not Path(cfg["target_pdb_src"]).is_absolute()
    assert not Path(cfg["run_dir"]).is_absolute()
    assert (REPO / cfg["target_pdb_src"]).is_file()


def test_the_demo_replays_from_a_directory_that_is_not_the_repo_root(tmp_path, fake_checkout, replay):
    config = _stage_example(fake_checkout)
    elsewhere = tmp_path / "somewhere" / "else"
    elsewhere.mkdir(parents=True)

    proc = replay(config, fake_checkout, elsewhere)

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-1500:]
    run_dir = fake_checkout / "runs" / "CALCA_smoke"
    assert (run_dir / "run_all.sh").is_file(), "the run folder must land in the checkout, not under the cwd"
    assert not (elsewhere / "runs").exists(), "relative paths resolved against the cwd"


def test_the_bindcraft2_campaign_has_an_attempt_cap_and_a_small_quota(tmp_path, fake_checkout, replay):
    config = _stage_example(fake_checkout)
    proc = replay(config, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1500:]

    run_dir = fake_checkout / "runs" / "CALCA_smoke"
    campaign = json.loads((run_dir / "bindcraft2" / "campaign.json").read_text())
    assert 1 <= campaign["max_trajectories"] <= 10, campaign
    assert 1 <= campaign["number_of_final_designs"] <= 2, campaign
    script = (run_dir / "run_bindcraft2.sh").read_text()
    assert "UNBOUNDED" not in script
    assert f"max_trajectories={campaign['max_trajectories']}" in script


def test_every_tool_in_the_demo_is_asked_for_a_handful_of_designs(tmp_path, fake_checkout, replay):
    config = _stage_example(fake_checkout)
    proc = replay(config, fake_checkout, tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1500:]
    run = fake_checkout / "runs" / "CALCA_smoke"

    pxd = (run / "run_pxdesign.sh").read_text()
    assert int(re.search(r"--N_sample (\d+)", pxd).group(1)) <= 8
    pc = (run / "run_proteina_complexa.sh").read_text()
    assert int(re.search(r"filter_samples_limit=(\d+)", pc).group(1)) <= 4
    assert int(re.search(r"best_of_n\.replicas=(\d+)", pc).group(1)) <= 2
    boltz = (run / "run_boltzgen.sh").read_text()
    assert int(re.search(r"--budget (\d+)", boltz).group(1)) <= 2
