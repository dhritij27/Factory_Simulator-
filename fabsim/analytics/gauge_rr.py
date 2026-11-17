"""Crossed Gauge R&R by the ANOVA method, with parametric-bootstrap confidence intervals.

Design: p parts x o operators x r trials, balanced. Variance components follow
AIAG MSA (4th ed.): the part x operator interaction is pooled into error when its
p-value exceeds 0.25. Negative component estimates are set to zero.

All functions are vectorised over leading axes, so ``y`` may have shape
(..., p, o, r) and the bootstrap runs thousands of studies as one array op.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats

POOL_ALPHA = 0.25


@dataclass
class GRRResult:
    n_parts: int
    n_operators: int
    n_trials: int
    var_repeatability: float
    var_operator: float
    var_interaction: float
    var_part: float
    interaction_pooled: bool
    pct_grr: float              # 100 * sigma_GRR / sigma_total
    pct_grr_ci_low: float
    pct_grr_ci_high: float
    pct_tolerance: float | None
    ndc: float

    def to_dict(self) -> dict:
        return asdict(self)


def _components(y: np.ndarray, pool_alpha: float = POOL_ALPHA):
    p, o, r = y.shape[-3:]
    grand = y.mean(axis=(-3, -2, -1), keepdims=True)
    part_m = y.mean(axis=(-2, -1), keepdims=True)
    op_m = y.mean(axis=(-3, -1), keepdims=True)
    cell_m = y.mean(axis=-1, keepdims=True)
    ss_p = o * r * ((part_m - grand) ** 2).sum(axis=(-3, -2, -1))
    ss_o = p * r * ((op_m - grand) ** 2).sum(axis=(-3, -2, -1))
    ss_po = r * ((cell_m - part_m - op_m + grand) ** 2).sum(axis=(-3, -2, -1))
    ss_e = ((y - cell_m) ** 2).sum(axis=(-3, -2, -1))
    df_p, df_o, df_po, df_e = p - 1, o - 1, (p - 1) * (o - 1), p * o * (r - 1)
    ms_p, ms_o, ms_po, ms_e = ss_p / df_p, ss_o / df_o, ss_po / df_po, ss_e / df_e
    with np.errstate(divide="ignore", invalid="ignore"):
        f_po = ms_po / ms_e
    p_po = stats.f.sf(f_po, df_po, df_e)
    pooled = p_po > pool_alpha
    ms_pool = (ss_po + ss_e) / (df_po + df_e)
    var_e = np.where(pooled, ms_pool, ms_e)
    var_po = np.where(pooled, 0.0, np.maximum((ms_po - ms_e) / r, 0.0))
    denom = np.where(pooled, ms_pool, ms_po)
    var_o = np.maximum((ms_o - denom) / (p * r), 0.0)
    var_p = np.maximum((ms_p - denom) / (o * r), 0.0)
    return var_e, var_o, var_po, var_p, pooled


def pct_grr_from_components(var_e, var_o, var_po, var_p):
    grr = var_e + var_o + var_po
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100.0 * np.sqrt(grr / (grr + var_p))


def gauge_rr(y: np.ndarray, lsl: float | None = None, usl: float | None = None, n_boot: int = 2000,
             ci: float = 0.95, rng: np.random.Generator | None = None) -> GRRResult:
    """y has shape (parts, operators, trials)."""
    y = np.asarray(y, dtype=float)
    p, o, r = y.shape
    var_e, var_o, var_po, var_p, pooled = (float(np.asarray(v)) for v in _components(y))
    pooled = bool(pooled)
    pct = float(pct_grr_from_components(var_e, var_o, var_po, var_p))
    lo, hi = bootstrap_ci(var_e, var_o, var_po, var_p, p, o, r, n_boot=n_boot, ci=ci, rng=rng)
    sigma_grr = np.sqrt(var_e + var_o + var_po)
    if lsl is not None and usl is not None:
        pct_tol = 100.0 * 6 * sigma_grr / (usl - lsl)
    elif lsl is not None or usl is not None:
        # one-sided spec: distance from the process mean to the single limit (AIAG)
        limit = lsl if lsl is not None else usl
        pct_tol = 100.0 * 3 * sigma_grr / abs(float(y.mean()) - limit)
    else:
        pct_tol = None
    ndc = float(1.41 * np.sqrt(var_p) / sigma_grr) if sigma_grr > 0 else float("inf")
    return GRRResult(p, o, r, var_e, var_o, var_po, var_p, pooled, pct, lo, hi, pct_tol, ndc)


def simulate_studies(var_e, var_o, var_po, var_p, p, o, r, n, rng):
    """Draw n balanced studies from the random-effects model."""
    P = rng.normal(0, np.sqrt(var_p), (n, p, 1, 1))
    O = rng.normal(0, np.sqrt(var_o), (n, 1, o, 1))
    PO = rng.normal(0, np.sqrt(var_po), (n, p, o, 1))
    E = rng.normal(0, np.sqrt(var_e), (n, p, o, r))
    return P + O + PO + E


def bootstrap_ci(var_e, var_o, var_po, var_p, p, o, r, n_boot=2000, ci=0.95, rng=None):
    """Parametric bootstrap percentile interval for %GRR."""
    rng = rng or np.random.default_rng(0)
    ys = simulate_studies(var_e, var_o, var_po, var_p, p, o, r, n_boot, rng)
    comps = _components(ys)
    pct = pct_grr_from_components(*comps[:4])
    a = (1 - ci) / 2
    return float(np.nanquantile(pct, a)), float(np.nanquantile(pct, 1 - a))


def coverage_study(var_e, var_o, var_p, p=20, o=3, r=3, n_studies=400, n_boot=800, ci=0.95, seed=0) -> dict:
    """How often does the bootstrap interval contain the true %GRR? Monte Carlo over fresh studies."""
    rng = np.random.default_rng(seed)
    true = float(pct_grr_from_components(var_e, var_o, 0.0, var_p))
    studies = simulate_studies(var_e, var_o, 0.0, var_p, p, o, r, n_studies, rng)
    hits, widths, ests = 0, [], []
    for y in studies:
        c = [float(np.asarray(v)) for v in _components(y)[:4]]
        lo, hi = bootstrap_ci(*c, p, o, r, n_boot=n_boot, ci=ci, rng=rng)
        ests.append(float(pct_grr_from_components(*c)))
        hits += lo <= true <= hi
        widths.append(hi - lo)
    return dict(true_pct_grr=true, coverage=hits / n_studies, nominal=ci, n_studies=n_studies,
                median_ci_width=float(np.median(widths)), median_estimate=float(np.median(ests)))
