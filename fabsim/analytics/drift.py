"""Drift and change detection on daily golden-unit residual series.

Each series is one (station, metric): the daily mean of (measured - certified
reference) over that day's golden-unit measurements. Golden units don't change,
so any movement in this series is the measurement system moving.

Detectors:
  EWMA     lambda = 0.2, L = 3.5       (online)
  CUSUM    k = 0.5 sigma, h = 8 sigma  (online, two-sided, resets after an alarm)
  PELT     ruptures, l2 cost, penalty 3 * log(n) on the standardised series (offline)

Baseline mean and sigma come from the first BASELINE_DAYS days.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fabsim.config import BASELINE_DAYS

# Limits: the textbook values (L = 3, h = 5) gave ~0.5-0.6 false alarms per station-month, because
# the baseline mean and sigma come from only 30 days. L = 3.5 / h = 8 were picked from the operating
# curve on seed 7 and then confirmed on seed 11, which played no part in the choice
# (results/detector_sweep.md, results/data_seed11/detector_sweep.md).
EWMA_LAMBDA, EWMA_L = 0.2, 3.5
CUSUM_K, CUSUM_H = 0.5, 8.0
EPISODE_GAP_DAYS = 14          # alarms closer than this belong to one episode
PELT_PEN_FACTOR = 3.0


@dataclass
class Episode:
    detector: str
    start_day: int
    end_day: int
    peak_sigma: float          # largest standardised statistic during the episode
    direction: int             # +1 reading high, -1 reading low


def baseline(x: np.ndarray, n: int = BASELINE_DAYS) -> tuple[float, float]:
    b = x[:n]
    b = b[~np.isnan(b)]
    return float(np.mean(b)), float(np.std(b, ddof=1))


def ewma(x: np.ndarray, mu: float, sigma: float, lam: float = EWMA_LAMBDA, L: float = EWMA_L):
    z = np.empty_like(x)
    prev = mu
    for t, v in enumerate(x):
        prev = prev if np.isnan(v) else lam * v + (1 - lam) * prev
        z[t] = prev
    t = np.arange(1, len(x) + 1)
    width = L * sigma * np.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * t)))
    return z, mu - width, mu + width


def cusum(x: np.ndarray, mu: float, sigma: float, k: float = CUSUM_K, h: float = CUSUM_H):
    """Two-sided tabular CUSUM in sigma units. Returns (s_hi, s_lo, alarm days)."""
    hi = np.zeros(len(x))
    lo = np.zeros(len(x))
    alarms = []
    sh = sl = 0.0
    for t, v in enumerate(x):
        if not np.isnan(v):
            zt = (v - mu) / sigma
            sh = max(0.0, sh + zt - k)
            sl = max(0.0, sl - zt - k)
        hi[t], lo[t] = sh, sl
        if sh > h or sl > h:
            alarms.append((t, +1 if sh > h else -1, max(sh, sl)))
            sh = sl = 0.0
    return hi, lo, alarms


def _episodes(points: list[tuple[int, int, float]], detector: str) -> list[Episode]:
    eps: list[Episode] = []
    for day, direction, mag in points:
        if eps and day - eps[-1].end_day <= EPISODE_GAP_DAYS:
            eps[-1].end_day = day
            eps[-1].peak_sigma = max(eps[-1].peak_sigma, mag)
        else:
            eps.append(Episode(detector, day, day, mag, direction))
    return eps


def detect(x: np.ndarray) -> dict:
    """Run all detectors on one daily series (NaN for days with no data)."""
    mu, sigma = baseline(x)
    z, lcl, ucl = ewma(x, mu, sigma)
    out_ewma = [(t, +1 if z[t] > ucl[t] else -1, abs(z[t] - mu) / sigma)
                for t in range(BASELINE_DAYS, len(x)) if z[t] > ucl[t] or z[t] < lcl[t]]
    _, _, c_alarms = cusum(x, mu, sigma)
    c_alarms = [a for a in c_alarms if a[0] >= BASELINE_DAYS]
    return dict(
        mu=mu, sigma=sigma, ewma=z, lcl=lcl, ucl=ucl,
        episodes=_episodes(out_ewma, "ewma") + _episodes(c_alarms, "cusum"),
        changepoints=changepoints(x, mu, sigma),
    )


def changepoints(x: np.ndarray, mu: float, sigma: float, pen_factor: float = PELT_PEN_FACTOR) -> list[int]:
    import ruptures as rpt

    s = pd.Series(x).interpolate(limit_direction="both").to_numpy()
    zs = ((s - mu) / sigma).reshape(-1, 1)
    algo = rpt.Pelt(model="l2", min_size=5, jump=1).fit(zs)
    bkps = algo.predict(pen=pen_factor * np.log(len(zs)))
    return [b for b in bkps if b < len(zs)]


def daily_series(df: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """df: golden residual rows with station_id, metric, measured_date, residual.
    Returns one column per (station, metric) indexed by day, NaN where there was no data."""
    s = df.groupby(["station_id", "metric", "measured_date"])["residual"].mean()
    wide = s.unstack(["station_id", "metric"])
    wide.index = pd.to_datetime(wide.index)
    return wide.reindex(days)
