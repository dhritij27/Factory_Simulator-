import numpy as np

from fabsim.analytics import gauge_rr as G


def test_hand_computed_components():
    # 2 parts x 2 operators x 2 trials, small enough to check by hand
    y = np.array([[[1.0, 1.2], [1.4, 1.6]],
                  [[3.0, 3.2], [3.4, 3.6]]])
    var_e, var_o, var_po, var_p, pooled = (float(np.asarray(v)) for v in G._components(y))
    # within-cell variance: each cell is {a, a+0.2} -> 0.02 ; interaction is exactly zero -> pooled
    assert pooled
    ms_pool = (0.0 + 4 * 0.02) / (1 + 4)
    assert np.isclose(var_e, ms_pool)
    assert np.isclose(var_o, (2 * 2 * 0.2 ** 2 * 2 / 1 - ms_pool) / 4)   # operator means 2.1 vs 2.5
    assert np.isclose(var_p, (2 * 2 * 1.0 ** 2 * 2 / 1 - ms_pool) / 4)   # part means 1.3 vs 3.3


def test_recovers_components_on_large_study():
    rng = np.random.default_rng(1)
    y = G.simulate_studies(0.04, 0.01, 0.0, 1.0, p=200, o=10, r=4, n=1, rng=rng)[0]
    var_e, var_o, _, var_p, _ = (float(np.asarray(v)) for v in G._components(y))
    assert abs(var_e - 0.04) / 0.04 < 0.1
    assert abs(var_p - 1.0) < 0.25
    assert 0.002 < var_o < 0.03


def test_ci_brackets_estimate_and_noisier_gauge_scores_worse():
    rng = np.random.default_rng(2)
    good = G.simulate_studies(0.01, 0.002, 0.0, 1.0, 20, 3, 3, 1, rng)[0]
    bad = G.simulate_studies(0.12, 0.002, 0.0, 1.0, 20, 3, 3, 1, rng)[0]
    rg, rb = G.gauge_rr(good, rng=rng, n_boot=500), G.gauge_rr(bad, rng=rng, n_boot=500)
    assert rg.pct_grr_ci_low <= rg.pct_grr <= rg.pct_grr_ci_high
    assert rb.pct_grr > rg.pct_grr
