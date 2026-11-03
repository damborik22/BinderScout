"""The CLI, TUI, status monitor and tools/*.py name no machine of ours.

This repo is public. The status monitor's tests and docstrings used the lab's own box
names as fixtures, and its checkout lookup hard-coded one fleet's directory layout. Hosts
are 'host-a', 'host-b'; a checkout is found from where the code runs, never from a
spelling of its directory. The patterns are written as character classes so this file
does not contain what it forbids.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_SCANNED = (
    [REPO / "binderscout.py"]
    + sorted((REPO / "tui").glob("*.py"))
    + sorted((REPO / "status").glob("*.py"))
    + sorted((REPO / "tools").glob("*.py"))
    + sorted((REPO / "tests" / "status").glob("*.py"))
    + sorted((REPO / "tests" / "tui").glob("*.py"))
)

_FORBIDDEN = {
    "a numbered fleet box": re.compile(r"\bbm[0-9]\b", re.IGNORECASE),
    "the cluster by name": re.compile(r"\bcl[a]ra\b", re.IGNORECASE),
    "the orchestrator workstation": re.compile(r"bindmaster[4]", re.IGNORECASE),
    "a guessed home-relative checkout directory": re.compile(r"dev/Bind(Master|Scout)\b"),
}


def test_the_lane_names_no_machine_and_guesses_no_checkout_directory():
    assert _SCANNED, "nothing scanned, so this test proved nothing"
    hits = []
    for path in _SCANNED:
        if path == Path(__file__).resolve():
            continue
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for what, pat in _FORBIDDEN.items():
                if pat.search(line):
                    hits.append(f"{path.relative_to(REPO)}:{n}: {what}: {line.strip()[:100]}")
    assert not hits, "\n".join(hits)
