"""SoluProt labels; it does not rank, gate, or delete.

Decision 2026-09-28, after measuring it against our own experimental results on two
targets: SoluProt is kept as a **label** only. It was never part of `rank` or
`consensus_iptm_mean`, but it had two other powers, and both have been removed.

**Why.** SoluProt is good at its real job — in the BindPred run it was the best available
predictor of whether a design yielded a measurement at all, which is expression and
solubility. But solubility and affinity are close to orthogonal on these pools: at the
paper threshold of 0.5 it failed **four of the ten tightest measured binders** on one
target, including a sub-0.1 nM design. So anything that lets SoluProt *withhold* or
*delete* a design loses top binders at a rate no threshold controls.

What it may still do: report its score and its pass/fail verdict, so a human weighing
what to order can see it. That is a label.

(Numbers live in the internal `Claude outputs/` folders — this repo is public and the
SPOC results are unpublished.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.scoring import annotate_wetlab_recommended  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EVALUATE = REPO / "Evaluator" / "evaluate.sh"
CONFIGURATOR = REPO / "configurator" / "configurator.py"


def _clean_pool(n=3):
    """A pool with nothing else wrong, so SoluProt is the only thing under test."""
    return pd.DataFrame(
        {
            "sequence": [f"{'A' * 30}{i}" for i in range(n)],
            "consensus_iptm_mean": [0.9] * n,
            "consensus_iptm_n": [3] * n,
            "passes_engine_gate": [True] * n,
            "agreement_count": [2] * n,
            "plddt_binder_min": [0.9] * n,
        }
    )


def test_a_soluprot_failure_does_not_withhold_the_wetlab_recommendation():
    d = _clean_pool(3)
    d["native_soluprot_passes"] = [True, False, None]
    out = annotate_wetlab_recommended(d)
    assert list(out["wetlab_recommended"]) == [True, True, True], (
        "a SoluProt failure must not set wetlab_recommended to False — it would withhold "
        "the recommendation from designs measured to be among the tightest binders"
    )


def test_the_soluprot_verdict_is_still_reported():
    """Removing the block must not remove the information."""
    d = _clean_pool(2)
    d["native_soluprot_passes"] = [True, False]
    out = annotate_wetlab_recommended(d)
    assert "soluprot" in str(out.loc[1, "wetlab_reason"]).lower(), (
        "the SoluProt verdict must still appear for the operator, just not as a blocker"
    )
    assert "soluprot" not in str(out.loc[0, "wetlab_reason"]).lower(), (
        "a passing design should not carry a SoluProt note"
    )


def test_evaluate_sh_refuses_the_pre_refold_filter():
    """RUNS evaluate.sh with the flag rather than reading its text.

    Two text-scanning versions of this test were hollow. The first read a fixed character
    window that held only the explanatory comment. The second scanned lines until a bare
    `;;` -- so when a mutation collapsed the branch onto one line, the scan ran off the
    end of the file and matched an `exit 1` belonging to something else. Invoking the
    script cannot be fooled that way: either the flag is refused or it is not.
    """
    import subprocess

    r = subprocess.run(
        ["bash", str(EVALUATE), "--soluprot-filter"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO,
    )
    assert r.returncode != 0, (
        "--soluprot-filter must fail loudly. Silently accepting or ignoring it hands the "
        f"caller different data than they asked for. stdout={r.stdout[:200]!r}"
    )
    combined = (r.stderr + r.stdout).lower()
    assert "soluprot" in combined and ("removed" in combined or "label" in combined), (
        f"the refusal must explain itself. Got: {(r.stderr or r.stdout)[:300]!r}"
    )


def test_the_configurator_no_longer_offers_to_filter():
    text = CONFIGURATOR.read_text()
    assert "soluprot_filter = ask_yn" not in text, (
        "the wizard must not offer pre-refold filtering any more — SoluProt is a label"
    )
    assert '"    --soluprot-filter \\\\"' not in text and "--soluprot-filter \\" not in text, (
        "the configurator must not emit --soluprot-filter into a run script"
    )
