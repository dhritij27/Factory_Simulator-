"""Export everything the dashboard shows into one JSON file.

The dashboard renders this file and computes nothing itself, so every number on
screen can be checked against the warehouse; tests/test_reconciliation.py does.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

import pandas as pd

from fabsim.analytics.run import PRIMARY_VARIANT
from fabsim import jsonsafe
from fabsim.config import ACTION_SHIFT_SIGMA, GROUND_TRUTH, METRICS, RESULTS, ROOT, SOR_DB
from fabsim.warehouse.build import connect

import os

# A side-by-side seed run (FABSIM_DATA set) must not overwrite the dashboard's data.
OUT = RESULTS / "dashboard.json" if os.environ.get("FABSIM_DATA") else ROOT / "dashboard" / "public" / "dashboard.json"


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso", double_precision=6))


def build_payload() -> dict:
    con = connect(read_only=True)
    q = lambda sql, *p: con.execute(sql, list(p)).df()
    run = q("SELECT * FROM analysis_runs").iloc[0]
    as_of = pd.Timestamp(run["data_through"]).date()
    totals = dict(
        measurements=int(con.execute("SELECT count(*) FROM fact_measurement").fetchone()[0]),
        quarantined=int(con.execute("SELECT count(*) FROM quarantine").fetchone()[0]),
        files=int(con.execute("SELECT count(*) FROM ingest_files").fetchone()[0]),
        stations=int(con.execute("SELECT count(DISTINCT station_id) FROM fact_measurement").fetchone()[0]),
        imputed_instrument=int(con.execute("SELECT count(*) FROM fact_measurement WHERE instrument_imputed").fetchone()[0]),
    )
    quarantine = q("SELECT reason, count(*) AS rows FROM quarantine GROUP BY reason ORDER BY rows DESC")
    alerts = q("""SELECT alert_id, site_id, kind, field, severity, first_seen_date, last_seen_date, n_files, detail
                  FROM ingest_alerts ORDER BY first_seen_date, alert_id""")
    series = q("""SELECT station_id, metric, CAST(date AS VARCHAR) AS date, residual, ewma, lcl, ucl
                  FROM drift_series WHERE variant = ? ORDER BY station_id, metric, date""", PRIMARY_VARIANT)
    episodes = q("""SELECT station_id, metric, detector, CAST(start_date AS VARCHAR) AS start_date,
                           CAST(end_date AS VARCHAR) AS end_date, peak_sigma FROM drift_episodes WHERE variant = ?""",
                 PRIMARY_VARIANT)
    charts = []
    for (sid, metric), g in series.groupby(["station_id", "metric"], sort=True):
        e = episodes[(episodes.station_id == sid) & (episodes.metric == metric)]
        charts.append(dict(station_id=sid, metric=metric, unit=METRICS[metric].unit,
                           points=_records(g[["date", "residual", "ewma", "lcl", "ucl"]]),
                           episodes=_records(e[["detector", "start_date", "end_date"]])))
    findings = q("""SELECT finding_id, station_id, metric, detectors, CAST(first_alarm_date AS VARCHAR) AS first_alarm_date,
                           CAST(last_alarm_date AS VARCHAR) AS last_alarm_date, status, recent_shift_sigma, peak_shift_sigma, action_level, direction,
                           instrument_id FROM drift_findings ORDER BY status, finding_id""")
    corr = q("""SELECT station_id, site_id, metric, bias, bias_ci_low, bias_ci_high, threshold, flagged,
                       deming_slope, ba_loa_low, ba_loa_high FROM correlation_results ORDER BY station_id, metric""")
    pairs = q("SELECT site_id, metric, station_a, station_b, diff_over_threshold FROM station_pair_diff")
    grr = q("""SELECT station_id, metric, pct_grr, pct_grr_ci_low, pct_grr_ci_high, ndc, verdict, n_parts
               FROM grr_results ORDER BY pct_grr DESC""")
    cpk = q("""SELECT station_id, metric, eye, n, cpk, cpk_ci_low, cpk_ci_high, frac_out_of_spec
               FROM cpk_results ORDER BY cpk""")
    con.close()

    s = sqlite3.connect(SOR_DB)
    certs = pd.read_sql("""SELECT i.instrument_id, i.instrument_type, i.station_id, c.cert_id, c.expires_on
                           FROM instruments i JOIN certifications c USING (instrument_id)
                           WHERE i.retired_on IS NULL ORDER BY c.expires_on""", s)
    tickets = pd.read_sql("""SELECT ticket_id, instrument_id, station_id, status, priority, reason, created_on, created_by
                             FROM service_tickets WHERE status != 'closed' ORDER BY created_on DESC""", s)
    s.close()
    certs["days_until_expiry"] = (pd.to_datetime(certs["expires_on"]) - pd.Timestamp(as_of)).dt.days
    certs["status"] = pd.cut(certs["days_until_expiry"], [-10 ** 6, -1, 30, 10 ** 6],
                             labels=["expired", "expiring_soon", "valid"]).astype(str)

    esc = json.loads((RESULTS / "escalation.json").read_text()) if (RESULTS / "escalation.json").exists() else None
    bt = json.loads((RESULTS / "backtest.json").read_text()) if (RESULTS / "backtest.json").exists() else None
    agent = json.loads((RESULTS / "agent_eval_rule.json").read_text())["summary"] if (RESULTS / "agent_eval_rule.json").exists() else None
    faults = json.loads((GROUND_TRUTH / "faults.json").read_text()) if (GROUND_TRUTH / "faults.json").exists() else []
    return dict(
        generated_at=str(date.today()), as_of=str(as_of), data_from=str(pd.Timestamp(run["data_from"]).date()),
        totals=totals, quarantine=_records(quarantine), alerts=_records(alerts),
        charts=charts, findings=_records(findings), correlation=_records(corr), pairs=_records(pairs),
        grr=_records(grr), cpk=_records(cpk), certs=_records(certs), tickets=_records(tickets),
        metrics={k: dict(unit=m.unit, lsl=m.lsl, usl=m.usl, bias_threshold=m.bias_threshold) for k, m in METRICS.items()},
        backtest=None if bt is None else dict(detectors={k: v for k, v in bt["detectors"][PRIMARY_VARIANT].items()
                                                         if k in ("ewma", "cusum", "pelt", "ewma_or_cusum")},
                                              correlation=bt["correlation"], ingestion_events=bt["ingestion"]["schema_events"]),
        agent_eval=agent,
        escalation=esc, action_shift_sigma=ACTION_SHIFT_SIGMA,
        ground_truth=dict(note="Simulation ground truth. A real deployment would not have this.",
                          faults=[{k: f[k] for k in ("fault_id", "kind", "station_id", "metric", "onset_day")} for f in faults]),
    )


def export(path=OUT) -> dict:
    payload = build_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(jsonsafe.dumps(payload, separators=(",", ":")))
    print(f"  dashboard data -> {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return payload
