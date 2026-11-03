"""The Evaluator's Python is public: it may name an architecture or a GPU, never a machine.

Comments and docstrings in the refold runners carry measurements, and a measurement
is only worth keeping when it says what it was measured ON (a GB10, an RTX 3090) --
not whose box it was. Cluster and fleet-machine names, and pointers to documents
that live on a private share, do not belong in a public tree.

The names are assembled from fragments below so that this file does not itself
contain them.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ROOTS = (REPO / "Evaluator" / "binder_comparison", REPO / "Evaluator" / "scripts")

_BANNED = re.compile(
    "|".join(
        [
            r"\b" + "cla" + "ra" + r"\b",  # the local cluster
            r"\b" + "b" + "m" + r"[1-9]\b",  # fleet-box aliases
            "b" + "m" + r"[1-9]_",  # ...inside file names
            "bind" + "master" + r"[1-9]\b",  # the orchestrator workstation
            r"\bfl" + "eet" + r"\b",  # "the x86 fleet" says which box by saying all of them
            r"/home/[a-z_][a-z0-9_-]*/",  # absolute home paths
        ]
    ),
    re.IGNORECASE,
)


def _python_files():
    for root in ROOTS:
        yield from sorted(root.rglob("*.py"))


@pytest.mark.parametrize("path", list(_python_files()), ids=lambda p: str(p.relative_to(REPO)))
def test_no_machine_names_in_evaluator_python(path):
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _BANNED.search(line)
    ]
    assert not hits, "machine/cluster identifiers in a public file:\n" + "\n".join(hits)
