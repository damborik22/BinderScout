"""A generated PXDesign / RFD3 / Protein-Hunter script finds an env made under a previous project name.

Both installers reuse such an env (`bindmaster_<tool>`) in place and write the success marker, so on
that box there is no `binderscout_<tool>`. A script that activates the new name dies in 0 s with
`EnvironmentNameNotFound`, which looks like a fast crash. The block is EXECUTED here against a fake
`conda` function, under the same `set -euo pipefail` the generated scripts run with.
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOLS = ("pxdesign", "rfd3", "protein_hunter")


@pytest.fixture
def scripts(tmp_path, fake_checkout, replay):
    payload = json.loads((REPO / "examples" / "CALCA" / "smoke.json").read_text())
    payload["cfg"]["run_dir"] = str(tmp_path / "run")
    payload["cfg"]["target_pdb_src"] = str(REPO / "examples" / "CALCA" / "target.pdb")
    config = tmp_path / "cfg.json"
    config.write_text(json.dumps(payload))
    proc = replay(config, fake_checkout, tmp_path)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    return {t: (tmp_path / "run" / f"run_{t}.sh").read_text() for t in TOOLS}


def _activated(script: str, listed: list[str]) -> tuple[str, str]:
    """Run only the env-selection lines of a generated script; return (activated env, stderr)."""
    lines = script.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("_bs_env="))
    end = next(i for i in range(start, len(lines)) if lines[i].startswith('conda activate "$_bs_env"'))
    block = "\n".join(lines[start : end + 1])
    listing = "\\n".join(f"{name}   /envs/{name}" for name in ["base", *listed])
    harness = (
        "set -euo pipefail\n"
        "conda() {\n"
        '    if [ "$1 $2" = "env list" ]; then printf \'# conda environments:\\n' + listing + "\\n'; return 0; fi\n"
        '    if [ "$1" = activate ]; then echo "ACTIVATED $2"; return 0; fi\n'
        "    return 99\n"
        "}\n" + block + "\n"
    )
    proc = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.strip().removeprefix("ACTIVATED "), proc.stderr


@pytest.mark.parametrize("tool", TOOLS)
def test_only_the_prerename_env_is_activated_when_it_is_all_there_is(scripts, tool):
    env, err = _activated(scripts[tool], [f"bindmaster_{tool}", "BindCraft"])
    assert env == f"bindmaster_{tool}"
    assert "previous project name" in err


@pytest.mark.parametrize("tool", TOOLS)
def test_the_canonical_env_wins_when_both_exist(scripts, tool):
    env, err = _activated(scripts[tool], [f"bindmaster_{tool}", f"binderscout_{tool}"])
    assert env == f"binderscout_{tool}"
    assert err == ""


@pytest.mark.parametrize("tool", TOOLS)
def test_with_neither_the_canonical_name_is_tried_so_the_failure_names_it(scripts, tool):
    env, _ = _activated(scripts[tool], ["BindCraft"])
    assert env == f"binderscout_{tool}"
