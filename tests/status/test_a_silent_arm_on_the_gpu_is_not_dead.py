"""The measurement this whole module exists for.

Measured 2026-10-30 on the completed pMHC RFD3 arm: designs land 10 at a time,
every ~4185 s. So for ~70 minutes the design count does not move at all. At the
same moment the live TfR1 RFD3 arm read: 0 designs, log silent 664 s, and GPU
99% with 6692 MiB held by its PID.

On the count alone that arm is indistinguishable from one that died. Anything
that classifies it as dead, or that lets output age override a live process, is
the bug -- not a cosmetic one, because the campaign's response to "dead" is to
relaunch an arm that is in fact working.
"""

from status.collect import classify
from status.schema import DEAD, DONE, QUEUED, RUNNING


def test_a_live_process_with_zero_output_is_running_not_dead():
    assert classify(done=0, total=50, proc_alive=True, started=True) == RUNNING


def test_output_age_never_overrides_a_live_process():
    # 70 minutes of silence is normal for RFD3, so age is not an input at all.
    for age in (0, 60, 4200, 86_400):
        assert classify(done=20, total=50, proc_alive=True, started=True, output_age_s=age) == RUNNING


def test_no_process_and_a_partial_pool_is_dead():
    assert classify(done=20, total=50, proc_alive=False, started=True) == DEAD


def test_a_full_pool_is_done_even_with_no_process():
    assert classify(done=50, total=50, proc_alive=False, started=True) == DONE


def test_a_full_pool_is_done_rather_than_running_when_the_process_lingers():
    assert classify(done=50, total=50, proc_alive=True, started=True) == DONE


def test_nothing_started_is_queued_not_dead():
    assert classify(done=0, total=50, proc_alive=False, started=False) == QUEUED
