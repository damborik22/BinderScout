"""The installers and shell tooling name no cluster and no lab machine.

This repo is public. tests/test_no_infrastructure_identifiers_in_tree.py bans the *shapes*
(private IPs, host-key fingerprints, this box's own account and hostname); it cannot ban a
name it has no list of. These scripts carried comments such as "bisected on <box>", "died on
<cluster>" and a whole-"fleet" reinstall, which identify the lab's machines by alias. Machines
are described by architecture (x86_64, aarch64) or generically ("a cluster", "a GB10 host");
GPU model names are measurements and stay.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import REPO


def tools_lane(root: Path, tracked: set[str] | None = None) -> list[Path]:
    """The non-Python files under ``root/tools`` that the lane scans.

    Only what the repo tracks is its content. An untracked ``__pycache__/*.pyc`` is a build
    artifact that embeds the absolute path of whoever ran the tests, so scanning it made this
    guard fail on its second run (any test that imports a tools/*.py writes one). Bytecode and
    ``__pycache__`` are excluded outright, and ``tracked`` (repo-relative POSIX paths) narrows
    the rest to tracked files; ``None`` means no tracked filter, for a tree that is not a checkout.
    """
    return [
        p
        for p in sorted((root / "tools").rglob("*"))
        if p.is_file()
        and p.suffix not in {".py", ".pyc", ".pyo"}
        and "__pycache__" not in p.parts
        and "aarch64" not in p.parts
        and (tracked is None or p.relative_to(root).as_posix() in tracked)
    ]


def _tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return set(out.split("\0"))


# Everything in the installers-and-shell lane: the two installers, the Evaluator shell entry
# points, the Docker test harness, and every tracked non-Python file under tools/.
SCRIPTS = [
    *(REPO / "install").glob("*.sh"),
    *(REPO / "Evaluator").glob("*.sh"),
    REPO / "test_env.sh",
    REPO / "docker-entrypoint.sh",
    REPO / "Dockerfile.test",
    *tools_lane(REPO, _tracked_files()),
]

# The names are assembled from fragments: spelling one out here would put it in a tracked file,
# which is the thing being tested for.
_NAMES = ["cla" + "ra", "ciir" + "c", "cvu" + "t", "ll" + "23"]
_FORBIDDEN = re.compile(
    r"\b(?:" + "|".join(_NAMES) + r")\b|\bbm[0-9]\b|\bbindmaster[0-9]\b|\bfleet\b|PLAN_bm[0-9]|\bCIFS share\b",
    re.IGNORECASE,
)


def test_the_lane_is_not_empty():
    assert len(SCRIPTS) > 10, SCRIPTS


def test_the_lane_ignores_bytecode_and_untracked_files(tmp_path):
    """A .pyc carrying the runner's own path must not be scanned as a shell script."""
    (tmp_path / "tools" / "__pycache__").mkdir(parents=True)
    (tmp_path / "tools" / "run.sh").write_text("echo ok\n")
    (tmp_path / "tools" / "stray.txt").write_text("echo untracked\n")
    pyc = tmp_path / "tools" / "__pycache__" / "loss_screen.cpython-310.pyc"
    pyc.write_bytes(b"\x00\x00" + f"/home/{_NAMES[0]}/tools/loss_screen.py".encode())
    # Control: the file is exactly what the guard flags when it is scanned.
    assert _FORBIDDEN.search(pyc.read_bytes().decode("latin-1"))
    assert {p.relative_to(tmp_path).as_posix() for p in tools_lane(tmp_path)} == {"tools/run.sh", "tools/stray.txt"}
    assert {p.name for p in tools_lane(tmp_path, {"tools/run.sh"})} == {"run.sh"}


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_machine_or_cluster_names(script):
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(script.read_text(errors="replace").splitlines(), 1)
        if _FORBIDDEN.search(line)
    ]
    assert not hits, "names a machine or cluster (describe it by architecture or generically):\n" + "\n".join(hits)
