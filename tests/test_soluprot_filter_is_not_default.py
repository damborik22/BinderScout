"""Dropping designs before refolding must never be the default answer.

`--soluprot-filter` removes sub-threshold sequences from the FASTA *before* any refold
engine runs, so anything it drops is gone from the report — it cannot be recovered by
re-ranking. `Evaluator/evaluate.sh` has it off by default (`SOLUPROT_FILTER=0`), which is
right. The configurator did not: it asked "Drop sub-threshold designs BEFORE refolding
(saves GPU)?" with `default=True`, so a user pressing Enter through the *recommended*
path enabled it at the paper threshold of 0.5.

Measured 2026-09-28 against our own experimental results on two targets (numbers in the
internal `Claude outputs/` folders, not here — this repo is public and the SPOC data is
unpublished):

* at the shipped 0.5 threshold the filter discarded **4 of the 10 tightest measured
  binders** on one target, including a sub-0.1 nM binder, and lost designs from the full
  run's own top-10 and top-30 on both targets;
* sweeping the threshold, **no value above 0.0 met Part Z's recall gate** ("loses <=1 of
  the top 30 and 0 of the top 10") on either target. Passing the gate requires keeping
  everything, which saves no GPU at all.

SoluProt remains valuable as a *screen* — the score still reaches the report either way,
and it was the best available predictor of which designs yielded a measurement. What is
refused here is letting it silently delete designs before they are ever folded.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIGURATOR = REPO / "configurator" / "configurator.py"
EVALUATE = REPO / "Evaluator" / "evaluate.sh"


def test_evaluate_sh_keeps_the_filter_off_by_default():
    text = EVALUATE.read_text()
    assert re.search(r"^SOLUPROT_FILTER=0\s*$", text, re.M), (
        "evaluate.sh must default SOLUPROT_FILTER to 0 — a pre-refold drop is unrecoverable"
    )


def test_the_configurator_does_not_default_to_dropping_designs():
    """The wizard is the documented path, so its default IS the effective default."""
    text = CONFIGURATOR.read_text()
    m = re.search(
        r"soluprot_filter\s*=\s*ask_yn\(\s*(?P<prompt>.*?)default\s*=\s*(?P<default>True|False)",
        text,
        re.S,
    )
    assert m, "could not find the configurator's soluprot_filter question — did it move?"
    assert m.group("default") == "False", (
        "the configurator offers to drop sub-threshold designs before refolding with "
        "default=True. Measured on two targets, that discards top-10 designs and several "
        "of the tightest measured binders. Anything dropped here never reaches the report."
    )


def test_the_prompt_warns_that_the_drop_is_unrecoverable():
    """A user saying yes should know what it costs, not just that it 'saves GPU'.

    This checks only what the OPERATOR SEES -- printed lines and the prompt itself.
    An earlier version searched a character window around the call, which passed on the
    explanatory *comment* sitting above it: deleting every printed warning left the test
    green. Comments do not reach the person answering the question.
    """
    lines = CONFIGURATOR.read_text().splitlines()
    idx = next(i for i, line in enumerate(lines) if "soluprot_filter = ask_yn" in line)
    # user-facing text only: drop comment lines, keep print(...) and the prompt string
    visible = [
        line
        for line in lines[max(0, idx - 15) : idx + 6]
        if not line.lstrip().startswith("#") and ("print(" in line or '"' in line)
    ]
    blob = " ".join(visible)
    # Deliberately does NOT accept "discards" on its own. The prompt already says
    # "discards them", and that word alone satisfied an earlier version of this test --
    # so deleting every printed warning left it green. What must be conveyed is
    # PERMANENCE: a discarded design is not merely set aside, it never reaches the report.
    assert re.search(r"(?i)unrecoverab|cannot be recovered|never reaches", blob), (
        "the filter question must tell the user the drop is PERMANENT, not just that "
        f"designs are discarded. Operator-visible text found was: {blob[:300]}"
    )
