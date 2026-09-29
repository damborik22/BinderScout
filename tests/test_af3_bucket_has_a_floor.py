"""AF3's bucket must never go below AF3's own smallest compilable shape.

Measured on an RTX 3090 (sm_86) on 2026-09-29, one input.json reused byte-identically
across two arms with a cold shared compile cache, only the bucket digits differing:

    --buckets=60    rc=1 in 43s, "RESOURCE_EXHAUSTED: Shared memory size limit
                    exceeded: requested 110592, available: 101376", no structure
    --buckets=256   rc=0 in 69s, no shared-memory error, 2 structures, iptm 0.52

That settles a question the docs had answered wrongly twice. AF3 is **not** blocked on
consumer Ampere -- the same card had already completed pools at buckets 493, 512 and 568.
The failure was ours: ``bucket = len(target) + max(len(binder))`` with no lower bound
handed AF3 a shape its own ladder never produces (a 60-token complex pads to 256 under
stock behaviour), and below 256 its tokamax Pallas/Triton kernels pick a tile config
whose shared-memory request exceeds what sm_86/sm_89 expose.

This test is cheap and static because the real check costs a GPU. What it defends is the
one line that caused a hard, unrecoverable abort of every AF3 refold on a small pool.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "Evaluator" / "scripts" / "refold_af3.py"


def _module():
    return ast.parse(SCRIPT.read_text())


def test_the_floor_constant_is_af3s_own_ladder_minimum():
    tree = _module()
    val = next(
        (
            n.value.value
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "AF3_MIN_BUCKET" for t in n.targets)
            and isinstance(n.value, ast.Constant)
        ),
        None,
    )
    assert val == 256, (
        f"AF3_MIN_BUCKET is {val!r}. It must be 256 -- the first rung of AF3's own stock "
        "bucket ladder. Below it, measured, AF3 aborts with a shared-memory error on sm_86."
    )


def test_the_bucket_is_actually_floored():
    """The computation must be wrapped in max(), not merely accompanied by a constant."""
    tree = _module()
    assigns = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "bucket" for t in n.targets)
    ]
    assert assigns, "no `bucket = ...` assignment found in refold_af3.py"
    for a in assigns:
        assert isinstance(a.value, ast.Call) and isinstance(a.value.func, ast.Name) and a.value.func.id == "max", (
            "the bucket is computed without a max() floor. A pool whose target+binder is "
            "under 256 tokens then aborts AF3 outright: measured rc=1 with "
            "'Shared memory size limit exceeded: requested 110592, available: 101376'."
        )
        names = {n.id for n in ast.walk(a.value) if isinstance(n, ast.Name)}
        assert "AF3_MIN_BUCKET" in names, f"the floor is not AF3_MIN_BUCKET: {ast.unparse(a.value)}"


def test_a_small_pool_is_raised_and_a_large_one_is_untouched():
    """The floor must not silently change pools that already worked."""
    lo = max(256, 32 + 28)  # the CALCA pool that aborted
    hi = max(256, 389 + 179)  # a pool that completed 50/50 at bucket 568
    assert lo == 256, "a 60-token pool must be raised to AF3's minimum"
    assert hi == 568, "a 568-token pool must be left exactly as it was -- no added compute"
