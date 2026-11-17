"""Watch vs. act: which drift alarms should become maintenance tickets?

An alarm only says the series moved more than chance would explain. Whether the
move is big enough to send a technician is a separate, practical question. This
replays each alarm day by day: a finding escalates on the first day its alarm is
active AND its trailing 7-day mean shift is at least ``tau`` x the metric's
repeatability sigma. tau = 0 escalates every alarm (the old behaviour).

Scored per tau: planted faults escalated within MAX_DELAY_DAYS of onset, the
delay from onset, and false escalations (alarms on series with no planted
drift/step, or before onset) per station-month.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from fabsim.backtest.run import MAX_DELAY_DAYS, _faults
from fabsim.config import BASELINE_DAYS, METRICS, RESULTS
from fabsim.warehouse.build import connect

TAUS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
WINDOW = 7


def _alarm_days(eps: pd.DataFrame, n: int) -> np.ndarray:
    on = np.zeros(n, bool)
    for e in eps.itertuples():
        on[int(e.start_day): int(e.end_day) + 1] = True
    return on


def escalation_curve(variant: str = "raw") -> pd.DataFrame:
    con = connect(read_only=True)
    s = con.execute("SELECT station_id, metric, residual FROM drift_series WHERE variant = ? ORDER BY date",
                    [variant]).df()
    eps = con.execute("""SELECT station_id, metric, start_day, end_day FROM drift_episodes
                         WHERE variant = ? AND detector IN ('ewma', 'cusum')""", [variant]).df()
    con.close()
    f = _faults()
    moving = {(r.station_id, r.metric): r for r in f[f.kind.isin(["drift", "step"])].itertuples()}
    series = {k: g["residual"].to_numpy(float) for k, g in s.groupby(["station_id", "metric"], sort=False)}
    n = len(next(iter(series.values())))
    station_months = len({k[0] for k in series}) * (n - BASELINE_DAYS) / 30.44
    rows = []
    for tau in TAUS:
        false_esc, delays, hit = 0, [], 0
        for key, x in series.items():
            mu = np.nanmean(x[:BASELINE_DAYS])
            trail = pd.Series(x).rolling(WINDOW, min_periods=3).mean().to_numpy()
            big = np.abs(trail - mu) / METRICS[key[1]].repeat_sd >= tau
            e = eps[(eps.station_id == key[0]) & (eps.metric == key[1])]
            on = _alarm_days(e, n) & big
            on[:BASELINE_DAYS] = False
            fault = moving.get(key)
            # count escalation *events*: starts of runs of escalated days
            starts = np.flatnonzero(on & ~np.r_[False, on[:-1]])
            for d in starts:
                if fault is None or d < fault.onset_day:
                    false_esc += 1
            if fault is not None:
                after = starts[starts >= fault.onset_day]
                if len(after) and after[0] - fault.onset_day <= MAX_DELAY_DAYS:
                    hit += 1
                    delays.append(int(after[0] - fault.onset_day))
        rows.append(dict(tau=tau, escalated=hit, faults=len(moving),
                         median_delay_days=float(np.median(delays)) if delays else None,
                         false_escalations=false_esc,
                         false_escalations_per_station_month=false_esc / station_months))
    return pd.DataFrame(rows)


def run(verbose: bool = True) -> pd.DataFrame:
    df = escalation_curve()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "escalation.json").write_text(df.to_json(orient="records", indent=2))
    lines = ["# Watch vs. act: escalation threshold", "",
             "A drift alarm escalates to a ticket once its trailing 7-day mean shift reaches τ × repeatability σ. "
             "τ = 0 escalates every alarm.", "",
             "| τ (σ) | Planted faults escalated | Median delay from onset (days) | False escalations | per station-month |",
             "|---|---|---|---|---|"]
    for r in df.itertuples():
        d = f"{r.median_delay_days:.0f}" if r.median_delay_days is not None and not np.isnan(r.median_delay_days) else "–"
        lines.append(f"| {r.tau} | {r.escalated}/{r.faults} | {d} | {r.false_escalations} | "
                     f"{r.false_escalations_per_station_month:.2f} |")
    (RESULTS / "escalation.md").write_text("\n".join(lines) + "\n")
    if verbose:
        print("\n".join(lines))
    return df


if __name__ == "__main__":
    run()
