"""Recall vs false-alarm curve for EWMA and CUSUM as their control limits widen.

This is an operating curve, not a tuning step: it shows the trade-off on this
seed. Any operating point chosen from it has to be confirmed on a seed the
choice was not made on (``python -m fabsim all --seed N`` then re-run this).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from fabsim.analytics import drift
from fabsim.backtest.run import MAX_DELAY_DAYS, _faults
from fabsim.config import BASELINE_DAYS, RESULTS
from fabsim.warehouse.build import connect

EWMA_L = [2.5, 2.75, 3.0, 3.25, 3.5, 4.0]
CUSUM_H = [4.0, 5.0, 6.0, 7.0, 8.0, 10.0]


def _alarm_starts(x, det, param):
    mu, sigma = drift.baseline(x)
    if det == "ewma":
        z, lcl, ucl = drift.ewma(x, mu, sigma, L=param)
        pts = [(t, 1, 0.0) for t in range(BASELINE_DAYS, len(x)) if z[t] > ucl[t] or z[t] < lcl[t]]
    else:
        _, _, al = drift.cusum(x, mu, sigma, h=param)
        pts = [a for a in al if a[0] >= BASELINE_DAYS]
    return [e.start_day for e in drift._episodes(pts, det)]


def sweep() -> pd.DataFrame:
    con = connect(read_only=True)
    s = con.execute("SELECT variant, station_id, metric, date, residual FROM drift_series ORDER BY date").df()
    con.close()
    f = _faults()
    moving = {(r.station_id, r.metric): r for r in f[f.kind.isin(["drift", "step"])].itertuples()}
    rows = []
    for variant, sv in s.groupby("variant"):
        series = {k: g["residual"].to_numpy(float) for k, g in sv.groupby(["station_id", "metric"])}
        n_days = len(next(iter(series.values())))
        station_months = len({k[0] for k in series}) * (n_days - BASELINE_DAYS) / 30.44
        for det, grid in (("ewma", EWMA_L), ("cusum", CUSUM_H)):
            for p in grid:
                fa, hit, delays = 0, set(), []
                for key, x in series.items():
                    fault = moving.get(key)
                    for st in _alarm_starts(x, det, p):
                        if fault is None or st < fault.onset_day:
                            fa += 1
                        elif st - fault.onset_day <= MAX_DELAY_DAYS and fault.fault_id not in hit:
                            hit.add(fault.fault_id)
                            delays.append(st - fault.onset_day)
                rows.append(dict(variant=variant, detector=det, param=p, recall=len(hit) / len(moving),
                                 detected=len(hit), faults=len(moving),
                                 false_alarms_per_station_month=fa / station_months,
                                 median_delay_days=float(np.median(delays)) if delays else None))
    df = pd.DataFrame(rows)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "detector_sweep.json").write_text(df.to_json(orient="records", indent=2))
    lines = ["# Detector operating curve", "",
             "Same planted faults and series as `backtest.md`; only the control-limit width changes. "
             "Textbook defaults are L = 3 (EWMA) and h = 5 (CUSUM); the pipeline uses L = 3.5 and h = 8.", "",
             "| Series | Detector | Limit | Recall | False alarms / station-month | Median delay (days) |",
             "|---|---|---|---|---|---|"]
    for r in df.itertuples():
        lim = f"L = {r.param}" if r.detector == "ewma" else f"h = {r.param}"
        d = f"{r.median_delay_days:.0f}" if r.median_delay_days is not None and not np.isnan(r.median_delay_days) else "–"
        lines.append(f"| {r.variant} | {r.detector} | {lim} | {r.detected}/{r.faults} | "
                     f"{r.false_alarms_per_station_month:.2f} | {d} |")
    (RESULTS / "detector_sweep.md").write_text("\n".join(lines) + "\n")
    return df


if __name__ == "__main__":
    print(sweep().to_string())
