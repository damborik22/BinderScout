"""ESMFold2-gated autosize controller — decide whether enough independent designs
have cleared the gate, and how many more to generate if not.

This is the deployment-agnostic *core* of the autosize loop (SKILL Phase 1). It owns
two pure pieces and no I/O:

  - ``count_independent_passers`` — collapse a scored pool to one entry per design
    group (backbone / trajectory, via ``add_design_groups``) and count how many
    groups clear the gate. This is what makes the target "X independent designs",
    not "X sequences".
  - ``autosize_decision`` — given (have, n_independent) decide complete / budget /
    continue, and size the next batch from the running yield.

The generation step (launch a tool locally, or write a "need M more" signal into
PROGRESS.md for a remote worker) is a thin wrapper around this core and lives with
the deployment mode, not here.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass

# When no design has cleared the gate yet, the yield is unknown (0) and we cannot
# back-compute a batch size. Explore at least this many more before giving up.
MIN_PROBE = 50


@dataclass
class Verdict:
    """The autosize decision for one tool at one point in the loop."""

    complete: bool
    stop_reason: str  # "complete" | "budget" | "continue"
    have: int  # independent designs at or above the gate threshold
    n_target: int
    n_independent: int  # total independent designs (backbones) scored so far
    yield_per_design: float  # have / n_independent (0 if none scored)
    next_batch: int  # additional designs to generate next round (0 if stopped)
    budget_spent: float
    budget_cap: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def autosize_decision(
    *,
    have: int,
    n_independent: int,
    n_target: int,
    budget_spent: float = 0.0,
    budget_cap: float | None = None,
    margin: float = 1.2,
) -> Verdict:
    """Decide whether the tool is done and, if not, how many more designs to draw.

    - ``have >= n_target`` → ``complete``.
    - else if a ``budget_cap`` is set and ``budget_spent >= budget_cap`` → stop with
      reason ``budget`` (report the shortfall; never loop forever).
    - else ``continue``: size the next batch from the running yield,
      ``ceil((n_target - have) / yield * margin)``. When the yield is still 0 (no
      passers yet) we can't estimate, so explore ``max(n_independent, MIN_PROBE)`` more.
    """
    yield_per_design = have / n_independent if n_independent else 0.0

    if have >= n_target:
        return _verdict(True, "complete", 0, locals())
    if budget_cap is not None and budget_spent >= budget_cap:
        return _verdict(False, "budget", 0, locals())

    remaining = n_target - have
    if yield_per_design > 0:
        next_batch = math.ceil(remaining / yield_per_design * margin)
    else:
        next_batch = max(n_independent, MIN_PROBE)
    return _verdict(False, "continue", next_batch, locals())


def _verdict(complete: bool, reason: str, next_batch: int, ns: dict) -> Verdict:
    return Verdict(
        complete=complete,
        stop_reason=reason,
        have=ns["have"],
        n_target=ns["n_target"],
        n_independent=ns["n_independent"],
        yield_per_design=ns["yield_per_design"],
        next_batch=next_batch,
        budget_spent=ns["budget_spent"],
        budget_cap=ns["budget_cap"],
    )


def count_independent_passers(pool, *, threshold: float, score_col: str, group_col: str = "design_group"):
    """Return ``(n_passers, n_independent)`` from a scored pool.

    Collapses to the best ``score_col`` per ``group_col`` (one design = one
    backbone / trajectory — see ``add_design_groups``), then counts groups whose best
    score is ``>= threshold``. Non-numeric / missing scores are ignored. ``n_independent``
    counts groups with at least one numeric score.
    """
    import pandas as pd

    if pool is None or len(pool) == 0 or score_col not in pool.columns or group_col not in pool.columns:
        return 0, 0
    scores = pd.to_numeric(pool[score_col], errors="coerce")
    best = scores.groupby(pool[group_col]).max()
    n_independent = int(best.notna().sum())
    n_passers = int((best >= threshold).sum())
    return n_passers, n_independent


def run_autosize_loop(
    *,
    generate: Callable[[int], None],
    score_pool: Callable[[], tuple[int, int]],
    n_target: int,
    budget_cap: float | None = None,
    gpu_h_per_design: float = 0.0,
    margin: float = 1.2,
    max_rounds: int = 100,
) -> list[Verdict]:
    """Drive generate → score → decide until the tool is done.

    Deployment-agnostic: ``generate(n)`` produces ``n`` more designs (a subprocess
    locally, or a "need n more" signal to a worker), and ``score_pool()`` re-reads the
    full accumulated pool and returns ``(independent_passers, n_independent)`` — the same
    pair ``count_independent_passers`` yields. The designs ``generate(n)`` makes must be
    visible to the next ``score_pool()`` call.

    Budget is accrued as ``designs_generated * gpu_h_per_design`` and checked *between*
    rounds, so the final round may overshoot the cap by at most one batch — the cap is a
    stop signal, not a hard ceiling. ``max_rounds`` guards against a never-converging loop
    when no ``budget_cap`` is set. Returns the Verdict history (one per round)."""
    history: list[Verdict] = []
    budget_spent = 0.0
    for _ in range(max_rounds):
        have, n_independent = score_pool()
        verdict = autosize_decision(
            have=have,
            n_independent=n_independent,
            n_target=n_target,
            budget_spent=budget_spent,
            budget_cap=budget_cap,
            margin=margin,
        )
        history.append(verdict)
        if verdict.stop_reason in ("complete", "budget"):
            break
        generate(verdict.next_batch)
        budget_spent += verdict.next_batch * gpu_h_per_design
    return history
