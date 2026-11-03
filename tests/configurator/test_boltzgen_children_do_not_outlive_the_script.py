"""BoltzGen's child processes must not keep the GPU after the run script is terminated.

BoltzGen forks dataloader / worker processes. Terminating the generated script left them
running, still holding the card. The script now runs BoltzGen in its own session (setsid)
and signals that whole process group on exit and on TERM / INT / HUP.

BoltzGen itself is never run here. The guard block is cut out of the generated script and
driven with a stand-in that sleeps and forks a sleeping grandchild, which is the shape of
the real process tree.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

# A stand-in for BoltzGen: records its own and its grandchild's pid, then waits.
STAND_IN = 'sleep 300 & echo "$$ $!" > "$PIDS"; : > "$READY"; wait'


@pytest.fixture
def generated(tmp_path):
    pdb = tmp_path / "t.pdb"
    pdb.write_text("ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00  0.00           C\n")
    cfg = {
        "name": "demo",
        "run_dir": tmp_path / "run",
        "target_pdb": pdb,
        "target_sequence": "MAE",
        "chains": "A",
        "hotspots": "",
        "min_length": 20,
        "max_length": 30,
        "n_designs": 1,
    }
    path = tmp_path / "run_boltzgen.sh"
    conf.write_run_boltzgen(path, cfg)
    return path.read_text()


def _guard(text: str) -> str:
    begin, end = conf.BOLTZGEN_GROUP_GUARD_BEGIN, conf.BOLTZGEN_GROUP_GUARD_END
    assert begin in text and end in text, "the generated BoltzGen script has no process-group guard"
    return text[text.index(begin) : text.index(end) + len(end)]


def _alive(pid: int) -> bool:
    """True while `pid` is a live process; a zombie is already dead."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _drive(tmp_path, body: str, guard: str):
    """Run `guard` + `body` as a script under the generated script's own shell options."""
    script = tmp_path / "driver.sh"
    script.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{guard}\n{body}\n")
    env = {**os.environ, "PIDS": str(tmp_path / "pids"), "READY": str(tmp_path / "ready")}
    proc = subprocess.Popen(["bash", str(script)], env=env, start_new_session=True)
    return proc, tmp_path / "pids", tmp_path / "ready"


def _pids(pids_file: Path) -> list[int]:
    return [int(x) for x in pids_file.read_text().split()]


def test_terminating_the_script_takes_the_whole_tree_with_it(tmp_path, generated):
    proc, pids, ready = _drive(tmp_path, f"_bg_run bash -c '{STAND_IN}'", _guard(generated))
    try:
        assert _wait_for(ready.exists), "the stand-in never started"
        child, grandchild = _pids(pids)
        # Control: both are really running, so the assertions below are about the guard.
        assert _alive(child) and _alive(grandchild)

        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=15) == 143
        assert _wait_for(lambda: not _alive(child)), "BoltzGen's own process survived the script"
        assert _wait_for(lambda: not _alive(grandchild)), "a BoltzGen child outlived the script"
    finally:
        proc.kill()
        for pid in (locals().get("child"), locals().get("grandchild")):
            if pid and _alive(pid):
                os.kill(pid, signal.SIGKILL)


def test_a_clean_exit_does_not_leave_a_lingering_child_behind(tmp_path, generated):
    """The tool returns, but something it forked is still running: the EXIT trap reaps it."""
    body = '_bg_run bash -c \'sleep 300 & echo "$$ $!" > "$PIDS"\''
    proc, pids, _ready = _drive(tmp_path, body, _guard(generated))
    try:
        assert proc.wait(timeout=15) == 0
        _child, grandchild = _pids(pids)
        assert _wait_for(lambda: not _alive(grandchild)), "a child outlived a script that exited normally"
    finally:
        proc.kill()
        if "grandchild" in locals() and _alive(grandchild):
            os.kill(grandchild, signal.SIGKILL)


def test_a_failing_tool_still_fails_the_script(tmp_path, generated):
    proc, _pids_file, _ready = _drive(tmp_path, "_bg_run bash -c 'exit 7'", _guard(generated))
    assert proc.wait(timeout=15) == 7


def test_the_control_without_the_guard_leaks_the_grandchild(tmp_path):
    """Proves the stand-in is a real leak: with a plain foreground call the grandchild survives SIGTERM.

    Without this, the assertions above could pass on a stand-in that never leaked anything.
    """
    proc, pids, ready = _drive(tmp_path, f"bash -c '{STAND_IN}'", "")
    grandchild = None
    try:
        assert _wait_for(ready.exists)
        child, grandchild = _pids(pids)
        os.kill(child, signal.SIGTERM)
        proc.wait(timeout=15)
        time.sleep(0.3)
        assert _alive(grandchild), "the stand-in no longer reproduces the leak, so the tests above prove nothing"
    finally:
        proc.kill()
        if grandchild and _alive(grandchild):
            os.kill(grandchild, signal.SIGKILL)


def test_the_generated_script_launches_boltzgen_through_the_guard(generated):
    assert '_bg_run "$CONDA_PREFIX/bin/boltzgen" run' in generated
    assert '\n"$CONDA_PREFIX/bin/boltzgen" run' not in generated, "BoltzGen is still launched unguarded"
    assert "setsid" in _guard(generated)


def test_the_generated_script_is_valid_bash(tmp_path, generated):
    script = tmp_path / "run_boltzgen.sh"
    script.write_text(generated)
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True).returncode == 0
