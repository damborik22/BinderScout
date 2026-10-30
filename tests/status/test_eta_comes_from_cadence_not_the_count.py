"""ETA is derived from observed batch cadence, and is None until it is real.

Fixture is the ACTUAL mtime sequence of the completed pMHC RFD3 arm, read off
disk 2026-10-30: five bursts of ten, ~4185 s apart. done/total alone supports no
prediction at all; the cadence does.

A fabricated ETA is worse than none, so one batch must yield None.
"""

from status.collect import cadence, eta_seconds

# Real: 1 design at t, 9 at t+1, repeated -- five bursts of ten.
BURST_STARTS = [1793302373, 1793306587, 1793310770, 1793314957, 1793319122]
MEASURED_MTIMES = []
for _start in BURST_STARTS:
    MEASURED_MTIMES.append(float(_start))
    MEASURED_MTIMES.extend(float(_start + 1) for _ in range(9))


def test_cadence_recovers_the_batch_size_and_the_gap():
    c = cadence(MEASURED_MTIMES)
    assert c["batches"] == 5
    assert c["batch_size"] == 10
    # Gaps measured: 4214, 4183, 4187, 4165 -> median 4185
    assert 4180 <= c["gap_s"] <= 4190


def test_eta_uses_the_gap_not_a_per_design_average():
    # 20 of 50 done: 3 more batches of 10, at ~4185 s each.
    eta = eta_seconds(done=20, total=50, mtimes=MEASURED_MTIMES)
    assert eta is not None
    assert 12_400 <= eta <= 12_700


def test_one_batch_is_not_a_cadence():
    one_burst = MEASURED_MTIMES[:10]
    assert cadence(one_burst)["gap_s"] is None
    assert eta_seconds(done=10, total=50, mtimes=one_burst) is None


def test_no_output_yields_no_eta():
    assert eta_seconds(done=0, total=50, mtimes=[]) is None


def test_a_finished_arm_has_no_eta():
    assert eta_seconds(done=50, total=50, mtimes=MEASURED_MTIMES) is None
