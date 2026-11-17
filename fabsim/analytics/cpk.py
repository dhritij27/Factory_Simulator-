"""Process capability with Bissell's approximate confidence interval."""
from __future__ import annotations

import numpy as np
from scipy import stats


def cpk(x: np.ndarray, lsl: float | None, usl: float | None, ci: float = 0.95) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    mu, sd = float(x.mean()), float(x.std(ddof=1))
    parts = []
    if usl is not None:
        parts.append((usl - mu) / (3 * sd))
    if lsl is not None:
        parts.append((mu - lsl) / (3 * sd))
    c = float(min(parts))
    z = stats.norm.ppf(1 - (1 - ci) / 2)
    half = z * np.sqrt(1 / (9 * n) + c ** 2 / (2 * (n - 1)))
    below = float(np.mean(x < lsl)) if lsl is not None else 0.0
    above = float(np.mean(x > usl)) if usl is not None else 0.0
    return dict(n=n, mean=mu, sd=sd, cpk=c, cpk_ci_low=float(c - half), cpk_ci_high=float(c + half),
                frac_out_of_spec=below + above)
