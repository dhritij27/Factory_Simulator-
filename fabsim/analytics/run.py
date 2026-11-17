"""Run every analysis against the warehouse and write the results back as tables.

grr_results            one row per station x metric (the day-2 MSA study)
correlation_results    golden-unit bias, Bland-Altman and Deming per station x metric
station_pair_diff      within-site bias differences, for the heatmap
drift_series           daily residual + EWMA + limits, for control charts
drift_episodes         alarm episodes per detector
changepoints           PELT change points
drift_findings         consolidated per station x metric, what the agent reads
cpk_results            capability per station x metric x eye, last 30 days
analysis_runs          when the analysis ran and what data it covered
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from fabsim.analytics import correlation, cpk as cpk_mod, drift, gauge_rr
from fabsim.config import ACTION_SHIFT_SIGMA, BASELINE_DAYS, METRICS, WAREHOUSE_DB
from fabsim.warehouse.build import connect

ACTIVE_WINDOW_DAYS = 7


def _golden_residuals(con) -> pd.DataFrame:
    return con.execute("""
        SELECT f.station_id, f.site_id, f.operator_id, f.metric, f.eye, f.unit_id, f.measured_date, f.value,
               f.instrument_id,
               r.reference_value, r.cert_uncertainty_1s, f.value - r.reference_value AS residual
        FROM fact_measurement f
        JOIN dim_golden_reference r USING (unit_id, metric, eye)
        WHERE f.test_type = 'golden'
    """).df()


def run_grr(con, rng) -> pd.DataFrame:
    # Not every vendor exports a trial number (CM1 doesn't), but repeats happen in time order,
    # so the trial is derived from timestamp order within part x operator.
    msa = con.execute("""
        SELECT station_id, metric, unit_id, eye, operator_id, value,
               row_number() OVER (PARTITION BY station_id, metric, unit_id, eye, operator_id
                                  ORDER BY measured_at, measurement_id) AS trial
        FROM fact_measurement WHERE test_type = 'msa'""").df()
    rows = []
    for (sid, metric), g in msa.groupby(["station_id", "metric"]):
        g = g.assign(part=g["unit_id"] + ":" + g["eye"])
        ops = sorted(g["operator_id"].unique())
        trials = sorted(g["trial"].unique())
        cube = g.pivot_table(index="part", columns=["operator_id", "trial"], values="value", aggfunc="first")
        cube = cube.dropna()                     # keep only parts with a complete, balanced set
        if len(cube) < 5 or len(ops) < 2:
            continue
        y = cube.to_numpy().reshape(len(cube), len(ops), len(trials))
        spec = METRICS[metric]
        res = gauge_rr.gauge_rr(y, spec.lsl, spec.usl, rng=rng)
        verdict = "acceptable" if res.pct_grr < 10 else ("marginal" if res.pct_grr <= 30 else "unacceptable")
        rows.append(dict(station_id=sid, metric=metric, verdict=verdict, **res.to_dict()))
    return pd.DataFrame(rows)


def run_correlation(gold: pd.DataFrame, start: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = gold[pd.to_datetime(gold["measured_date"]) < start + pd.Timedelta(days=BASELINE_DAYS)]
    rows = []
    for (sid, metric), g in base.groupby(["station_id", "metric"]):
        per_part_var = g.groupby(["unit_id", "eye"])["value"].agg(lambda v: v.var(ddof=1) / len(v)).mean()
        lam = float(per_part_var / (g["cert_uncertainty_1s"].iloc[0] ** 2))
        r = correlation.station_bias(g, METRICS[metric].bias_threshold, lam)
        rows.append(dict(station_id=sid, site_id=sid.rsplit("-", 2)[0] if sid.startswith("LAB") else sid.split("-")[0],
                         metric=metric, **r))
    corr = pd.DataFrame(rows)
    corr["site_id"] = corr["station_id"].map(lambda s: "-".join(s.split("-")[:2]) if s.startswith("LAB") else s.split("-")[0])
    pairs = []
    for (site, metric), g in corr.groupby(["site_id", "metric"]):
        for a in g.itertuples():
            for b in g.itertuples():
                pairs.append(dict(site_id=site, metric=metric, station_a=a.station_id, station_b=b.station_id,
                                  diff=a.bias - b.bias, diff_over_threshold=(a.bias - b.bias) / a.threshold))
    return corr, pd.DataFrame(pairs)


def operator_adjust(gold: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    """Remove each operator's effect from golden residuals.

    Each day's golden run is done by one operator, and operator-to-operator
    differences are larger than the day's averaged repeatability noise, so the raw
    daily series is a mixture of operator levels. Operators are shared by every
    station at a site, so their effects are estimated in the baseline window from
    residuals pooled across the site's stations (after removing each station's own
    baseline mean), then subtracted everywhere.
    """
    g = gold.copy()
    base = g[pd.to_datetime(g["measured_date"]) < start + pd.Timedelta(days=BASELINE_DAYS)]
    st_mean = base.groupby(["station_id", "metric"])["residual"].mean().rename("st_mean")
    b = base.join(st_mean, on=["station_id", "metric"])
    b["centred"] = b["residual"] - b["st_mean"]
    op = b.groupby(["site_id", "operator_id", "metric"])["centred"].mean().rename("op_effect")
    g = g.join(op, on=["site_id", "operator_id", "metric"])
    g["residual"] = g["residual"] - g["op_effect"].fillna(0.0)
    return g.drop(columns=["op_effect"])


VARIANTS = ("raw", "operator_adjusted")
# What drift_findings (and so the agent) is built from. Operator adjustment cut false alarms on seed 7
# but not on seed 11, so it isn't the default; both variants are still computed and scored.
PRIMARY_VARIANT = "raw"


def run_drift(con, gold: pd.DataFrame, start: pd.Timestamp, n_days: int):
    days = pd.date_range(start, periods=n_days, freq="D")
    series_rows, ep_rows, cp_rows, findings = [], [], [], []
    inst = con.execute("""SELECT station_id, instrument_type, instrument_id FROM dim_instrument
                          WHERE retired_on IS NULL""").df()
    from fabsim.config import INSTRUMENT_FOR_METRIC
    current_inst = {(r.station_id, r.instrument_type): r.instrument_id for r in inst.itertuples()}
    last_day = n_days - 1
    for variant in VARIANTS:
        data = gold if variant == "raw" else operator_adjust(gold, start)
        wide = drift.daily_series(data, days)
        for (sid, metric) in wide.columns:
            x = wide[(sid, metric)].to_numpy(dtype=float)
            if np.isnan(x[:BASELINE_DAYS]).sum() > BASELINE_DAYS // 2:
                continue
            r = drift.detect(x)
            for t in range(n_days):
                series_rows.append((variant, sid, metric, days[t].date(), x[t], r["ewma"][t], r["lcl"][t], r["ucl"][t]))
            eps = r["episodes"]
            for e in eps:
                ep_rows.append(dict(variant=variant, station_id=sid, metric=metric, detector=e.detector,
                                    start_date=days[e.start_day].date(), end_date=days[e.end_day].date(),
                                    start_day=e.start_day, end_day=e.end_day,
                                    peak_sigma=e.peak_sigma, direction=e.direction))
            for bkp in r["changepoints"]:
                cp_rows.append(dict(variant=variant, station_id=sid, metric=metric, day=bkp, date=days[bkp].date()))
            if eps and variant == PRIMARY_VARIANT:
                recent = x[~np.isnan(x)][-7:]
                shift = float(np.mean(recent) - r["mu"])
                sd = METRICS[metric].repeat_sd
                # Hysteresis: a finding is "act" if its trailing 7-day shift reached the threshold on any alarm day
                # of its current alarm run, not just today. Otherwise a finding that already earned a ticket could
                # flip back to "watch" when noise dips the latest estimate. This matches the back-test replay
                # (fabsim/backtest/escalation.py) that the threshold was validated with.
                spans = sorted((e.start_day, e.end_day) for e in eps)
                cur = list(spans[-1])
                for a, b in reversed(spans[:-1]):
                    if b >= cur[0] - 1:
                        cur[0] = min(cur[0], a)
                trail = pd.Series(x).rolling(7, min_periods=3).mean().to_numpy() - r["mu"]
                peak = float(np.nanmax(np.abs(trail[cur[0]:cur[1] + 1]))) / sd
                findings.append(dict(
                    station_id=sid, metric=metric,
                    detectors=",".join(sorted({e.detector for e in eps})),
                    first_alarm_date=days[min(e.start_day for e in eps)].date(),
                    last_alarm_date=days[max(e.end_day for e in eps)].date(),
                    n_episodes=len(eps),
                    status="active" if max(e.end_day for e in eps) >= last_day - ACTIVE_WINDOW_DAYS else "cleared",
                    recent_shift=shift, recent_shift_sigma=shift / sd, peak_shift_sigma=peak,
                    action_level="act" if peak >= ACTION_SHIFT_SIGMA else "watch",
                    direction="reading high" if shift > 0 else "reading low",
                    instrument_id=current_inst.get((sid, INSTRUMENT_FOR_METRIC[metric])),
                ))
    series = pd.DataFrame(series_rows, columns=["variant", "station_id", "metric", "date", "residual", "ewma", "lcl", "ucl"])
    f = pd.DataFrame(findings)
    if len(f):
        f.insert(0, "finding_id", [f"DF-{i+1:04d}" for i in range(len(f))])
    return series, pd.DataFrame(ep_rows), pd.DataFrame(cp_rows), f


def run_cpk(con, end: pd.Timestamp) -> pd.DataFrame:
    prod = con.execute(f"""
        SELECT station_id, metric, eye, value FROM fact_measurement
        WHERE test_type = 'production' AND measured_date > DATE '{(end - pd.Timedelta(days=30)).date()}'
    """).df()
    rows = []
    for (sid, metric, eye), g in prod.groupby(["station_id", "metric", "eye"]):
        if len(g) < 30:
            continue
        spec = METRICS[metric]
        rows.append(dict(station_id=sid, metric=metric, eye=eye, window="last_30_days",
                         **cpk_mod.cpk(g["value"].to_numpy(), spec.lsl, spec.usl)))
    return pd.DataFrame(rows)


def run_all(db=WAREHOUSE_DB, verbose: bool = True) -> dict:
    con = connect(db)
    rng = np.random.default_rng(20260705)
    lo, hi = con.execute("SELECT min(measured_date), max(measured_date) FROM fact_measurement").fetchone()
    start, end = pd.Timestamp(lo), pd.Timestamp(hi)
    n_days = (end - start).days + 1
    gold = _golden_residuals(con)
    out = {}
    out["grr_results"] = run_grr(con, rng)
    out["correlation_results"], out["station_pair_diff"] = run_correlation(gold, start)
    (out["drift_series"], out["drift_episodes"], out["changepoints"],
     out["drift_findings"]) = run_drift(con, gold, start, n_days)
    out["cpk_results"] = run_cpk(con, end)
    out["analysis_runs"] = pd.DataFrame([dict(ran_at=pd.Timestamp.now().isoformat(timespec="seconds"),
                                              data_from=start.date(), data_through=end.date(), n_days=n_days)])
    for name, df in out.items():
        con.register("tmp_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM tmp_df")
        con.unregister("tmp_df")
    con.close()
    if verbose:
        g = out["grr_results"]
        print(f"  gauge R&R: {len(g)} studies, {int((g.verdict == 'unacceptable').sum())} unacceptable, "
              f"{int((g.verdict == 'marginal').sum())} marginal")
        print(f"  correlation: {int(out['correlation_results'].flagged.sum())} station x metric flagged for bias")
        print(f"  drift: {len(out['drift_episodes'])} alarm episodes, {len(out['drift_findings'])} findings "
              f"({int((out['drift_findings'].status == 'active').sum()) if len(out['drift_findings']) else 0} active)")
        print(f"  cpk: {len(out['cpk_results'])} rows")
    return out
