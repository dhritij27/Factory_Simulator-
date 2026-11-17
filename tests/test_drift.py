import numpy as np

from fabsim.analytics import correlation, drift


def _series(shift_at=None, size=0.0, n=182, seed=0):
    x = np.random.default_rng(seed).normal(0, 1, n)
    if shift_at is not None:
        x[shift_at:] += size
    return x


def test_step_is_caught_soon_after_onset():
    r = drift.detect(_series(100, 2.0))
    starts = [e.start_day for e in r["episodes"] if e.start_day >= 100]
    assert starts and min(starts) - 100 <= 10


def test_changepoint_localises_step():
    r = drift.detect(_series(90, 2.5, seed=3))
    assert any(abs(b - 90) <= 5 for b in r["changepoints"])


def test_cusum_resets_after_alarm():
    _, _, alarms = drift.cusum(np.r_[np.zeros(10), np.full(30, 3.0)], 0.0, 1.0)
    assert len(alarms) >= 2


def test_deming_recovers_slope_with_error_in_both():
    rng = np.random.default_rng(0)
    t = rng.normal(0, 1, 5000)
    x = t + rng.normal(0, 0.3, t.size)
    y = 2 + 1.5 * t + rng.normal(0, 0.3, t.size)
    slope, icpt = correlation.deming(x, y, lam=1.0)
    assert abs(slope - 1.5) < 0.05 and abs(icpt - 2) < 0.05
