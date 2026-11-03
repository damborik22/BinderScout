"""Every shell script that looks for conda carries the SAME discovery code.

The scripts cannot source a shared file (install.sh runs on a checkout where nothing else is
guaranteed to exist, evaluate.sh is copied around), so the discovery block is duplicated. A
duplicate that is allowed to drift is how there came to be four different algorithms; this makes
the copies byte-identical, the way tests/test_installers_do_not_drift.py does for other blocks,
and pins that no script went back to its own candidate list.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import BLOCK_BEGIN, BLOCK_END, REPO, extract_block  # noqa: E402

CARRIERS = [
    REPO / "install" / "install.sh",
    REPO / "install" / "install_aarch.sh",
    REPO / "Evaluator" / "evaluate.sh",
    REPO / "Evaluator" / "install.sh",
    REPO / "Evaluator" / "run.sh",
]


def test_every_script_that_looks_for_conda_carries_the_block():
    missing = [str(p.relative_to(REPO)) for p in CARRIERS if BLOCK_BEGIN not in p.read_text()]
    assert not missing, f"no shared conda block in: {missing}"


def test_the_copies_are_textually_identical():
    reference = extract_block(CARRIERS[0])
    drifted = [str(p.relative_to(REPO)) for p in CARRIERS[1:] if extract_block(p) != reference]
    assert not drifted, f"the conda block drifted from install/install.sh in: {drifted}"


@pytest.mark.parametrize("script", CARRIERS, ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_script_has_a_private_candidate_list(script):
    """The old loops spelled the conda.sh locations out; only the shared block may."""
    text = script.read_text()
    outside = text.split(BLOCK_BEGIN)[0] + text.split(BLOCK_END, 1)[1]
    offenders = re.findall(r"^.*(?:miniforge3|mambaforge|miniconda3|anaconda3|/opt/conda)\S*/etc/profile\.d.*$", outside, re.M)
    offenders = [line.strip() for line in offenders if not line.lstrip().startswith("#")]
    assert not offenders, f"{script.name} still carries its own conda search list: {offenders}"
