"""The self-matching trap, tested by behaviour rather than by grepping the source.

A full-command-line process match finds ITS OWN command line, because the thing
it searches for is the thing it was asked about. The consequence is not a cosmetic
false positive: every arm reports `running`, including the dead ones, so the
monitor can never report a failure and is worse than having none.

CLAUDE.local.md records this; tfr1_queue.sh avoids it by waiting with `kill -0`.

A text assertion that `getpid` appears in the module does NOT catch it -- the
exclusion can be gutted while the symbol stays. Proven: that mutation survived.
So this test runs the check from inside a process whose own argv carries the
needle, which is the exact situation the trap springs in.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_PROBE_FROM_INSIDE = """
import json, sys
sys.path.insert(0, {repo!r})
from status.liveness import tool_alive
# This process's own argv contains both the run dir and the tool name below.
print(json.dumps(tool_alive("rfd3", {run_dir!r})))
"""


def test_a_process_asking_about_itself_is_not_counted_as_the_tool(tmp_path):
    run_dir = tmp_path / "runs" / "camp"
    run_dir.mkdir(parents=True)

    # The needle is in this child's OWN command line, twice over.
    code = _PROBE_FROM_INSIDE.format(repo=str(REPO), run_dir=str(run_dir))
    proc = subprocess.run(
        [sys.executable, "-c", code, f"--marker={run_dir}/rfd3"],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    verdict = json.loads(proc.stdout)
    assert verdict["alive"] is False, "the probe matched its own command line -- every arm would read as running"


def test_a_genuine_descendant_process_is_still_found(tmp_path):
    """The exclusion must not be so broad that it hides real work.

    A tool runs as a DESCENDANT of its run script, never as an ancestor of the
    monitor, so excluding our own lineage cannot hide it.
    """
    run_dir = tmp_path / "runs" / "camp"
    run_dir.mkdir(parents=True)

    # Waits on stdin rather than sleeping, so it dies when we close the pipe.
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()", f"rfd3 out_dir={run_dir}/rfd3"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        from status.liveness import tool_alive

        # Give the kernel a moment to publish /proc/<pid>/cmdline.
        for _ in range(100):
            verdict = tool_alive("rfd3", run_dir)
            if verdict["alive"]:
                break
        assert verdict["alive"] is True, "a real tool process must be detected"
        assert verdict["pid"] == child.pid
    finally:
        child.stdin.close()
        child.wait(timeout=30)
