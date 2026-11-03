"""The generated conda search must not turn an UNSET variable into `/etc/profile.d/conda.sh`.

`"${BINDERSCOUT_CONDA:-}/etc/profile.d/conda.sh"` and `"${CONDA_EXE%/bin/*}/etc/profile.d/conda.sh"`
both expand to `/etc/profile.d/conda.sh` when their variable is unset -- a real file on boxes with a
packaged conda -- and they are the FIRST candidates, so a system hook could win over the checkout's
own conda. The loop is run here against a fake root (every candidate path is looked up under
$FAKE_ROOT), with the variables unset, a "system" hook at /etc/profile.d/conda.sh and the checkout's
own conda at its usual place; the checkout's must be the one sourced.
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def conda_loop(tmp_path, fake_checkout, replay):
    payload = json.loads((REPO / "examples" / "CALCA" / "smoke.json").read_text())
    payload["cfg"]["run_dir"] = str(tmp_path / "run")
    payload["cfg"]["target_pdb_src"] = str(REPO / "examples" / "CALCA" / "target.pdb")
    config = tmp_path / "cfg.json"
    config.write_text(json.dumps(payload))
    proc = replay(config, fake_checkout, tmp_path)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    lines = (tmp_path / "run" / "run_pxdesign.sh").read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("_conda_found=false"))
    end = next(i for i in range(start, len(lines)) if lines[i] == "done")
    return "\n".join(lines[start : end + 1])


def _run(loop: str, tmp_path: Path, own_conda: bool = True, **extra: str) -> str:
    root = tmp_path / "fake_root"
    (root / "etc" / "profile.d").mkdir(parents=True, exist_ok=True)
    (root / "etc" / "profile.d" / "conda.sh").write_text("echo SYSTEM_HOOK\n")
    if own_conda:
        own = root / "checkout" / "conda" / "etc" / "profile.d"
        own.mkdir(parents=True, exist_ok=True)
        (own / "conda.sh").write_text("echo CHECKOUT_CONDA\n")
    (root / "home").mkdir(exist_ok=True)
    # Every candidate is looked up (and sourced) under $FAKE_ROOT, which stands in for `/`.
    loop = loop.replace('"$_conda_sh"', '"$FAKE_ROOT$_conda_sh"')
    script = f'set -euo pipefail\nBINDERSCOUT_DIR=/checkout\nset +u\n{loop}\necho "found=$_conda_found"\n'
    env = {"PATH": "/usr/bin:/bin", "HOME": str(root / "home"), "FAKE_ROOT": str(root), **extra}
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def test_unset_variables_do_not_let_a_system_hook_win(conda_loop, tmp_path):
    out = _run(conda_loop, tmp_path)
    assert "CHECKOUT_CONDA" in out
    assert "SYSTEM_HOOK" not in out


def _hook(tmp_path: Path, where: str, marker: str) -> None:
    d = tmp_path / "fake_root" / where / "etc" / "profile.d"
    d.mkdir(parents=True, exist_ok=True)
    (d / "conda.sh").write_text(f"echo {marker}\n")


def test_conda_exe_is_still_honoured_when_set(conda_loop, tmp_path):
    _hook(tmp_path, "elsewhere", "FROM_CONDA_EXE")
    out = _run(conda_loop, tmp_path, own_conda=False, CONDA_EXE="/elsewhere/bin/conda")
    assert out.splitlines()[0] == "FROM_CONDA_EXE"


def test_binderscout_conda_is_still_honoured_when_set(conda_loop, tmp_path):
    _hook(tmp_path, "chosen", "CHOSEN")
    out = _run(conda_loop, tmp_path, BINDERSCOUT_CONDA="/chosen")
    assert out.splitlines()[0] == "CHOSEN"
