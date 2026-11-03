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
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import REPO

# Everything in the installers-and-shell lane: the two installers, the Evaluator shell entry
# points, the Docker test harness, and every non-Python file under tools/.
SCRIPTS = [
    *(REPO / "install").glob("*.sh"),
    *(REPO / "Evaluator").glob("*.sh"),
    REPO / "test_env.sh",
    REPO / "docker-entrypoint.sh",
    REPO / "Dockerfile.test",
    *(p for p in (REPO / "tools").rglob("*") if p.is_file() and p.suffix != ".py" and "aarch64" not in p.parts),
]

# The names are assembled from fragments: spelling one out here would put it in a tracked file,
# which is the thing being tested for.
_NAMES = ["cla" + "ra", "ciir" + "c", "cvu" + "t", "ll" + "23"]
_FORBIDDEN = re.compile(
    r"\b(?:" + "|".join(_NAMES) + r")\b|\bbm[0-9]\b|\bbindmaster[0-9]\b|\bfleet\b|PLAN_bm[0-9]",
    re.IGNORECASE,
)


def test_the_lane_is_not_empty():
    assert len(SCRIPTS) > 10, SCRIPTS


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_machine_or_cluster_names(script):
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(script.read_text(errors="replace").splitlines(), 1)
        if _FORBIDDEN.search(line)
    ]
    assert not hits, "names a machine or cluster (describe it by architecture or generically):\n" + "\n".join(hits)
