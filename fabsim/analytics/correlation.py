"""Station-to-station correlation using golden units.

Each golden unit has a certified reference value. For each station and metric:

  bias           mean of daily mean residuals (measured - reference) over the baseline
                 window, with a t-interval over days (days are the independent unit,
                 because each day's golden run has one operator)
  Bland-Altman   mean difference and 95% limits of agreement vs the reference
  Deming         regression of station reading on reference value, allowing error in both

A station is flagged when its bias exceeds the metric's practical threshold and the
95% interval excludes zero.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def deming(x: np.ndarray, y: np.ndarray, lam: float = 1.0) -> tuple[float, float]:
    """Deming regression. lam = var(error in y) / var(error in x)."""
    mx, my = x.mean(), y.mean()
    sxx = ((x - mx) ** 2).mean()
    syy = ((y - my) ** 2).mean()
    sxy = ((x - mx) * (y - my)).mean()
    slope = (syy - lam * sxx + np.sqrt((syy - lam * sxx) ** 2 + 4 * lam * sxy ** 2)) / (2 * sxy)
    return float(slope), float(my - slope * mx)


def station_bias(res: pd.DataFrame, threshold: float, lam: float) -> dict:
    """res: golden rows for one station+metric in the baseline window, with
    measured_date, unit_id, eye, value, reference_value, residual."""
    daily = res.groupby("measured_date")["residual"].mean()
    n = len(daily)
    bias = float(daily.mean())
    se = float(daily.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    tcrit = stats.t.ppf(0.975, n - 1) if n > 1 else float("nan")
    lo, hi = bias - tcrit * se, bias + tcrit * se
    d = res["residual"]
    per_part = res.groupby(["unit_id", "eye"]).agg(x=("reference_value", "first"), y=("value", "mean"))
    slope, intercept = deming(per_part["x"].to_numpy(), per_part["y"].to_numpy(), lam)
    flagged = bool(abs(bias) > threshold and (lo > 0 or hi < 0))
    return dict(bias=bias, bias_ci_low=float(lo), bias_ci_high=float(hi), n_days=n,
                ba_mean=float(d.mean()), ba_loa_low=float(d.mean() - 1.96 * d.std(ddof=1)),
                ba_loa_high=float(d.mean() + 1.96 * d.std(ddof=1)),
                deming_slope=slope, deming_intercept=intercept, threshold=threshold, flagged=flagged)
