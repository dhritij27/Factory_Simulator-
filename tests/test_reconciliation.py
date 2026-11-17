"""Every number the dashboard shows must match an independent query of the source data.

The queries here are written from scratch against fact_measurement, quarantine,
dim_golden_reference and the system of record. They don't call the analytics
code that produced the dashboard, so a regression in that code shows up as a
mismatch here.
"""
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from fabsim.analytics.run import PRIMARY_VARIANT
from fabsim.config import METRICS, SOR_DB, WAREHOUSE_DB
from fabsim.dashboard_export import OUT

pytestmark = pytest.mark.skipif(not (WAREHOUSE_DB.exists() and OUT.exists()),
                                reason="run `python -m fabsim all` first")


@pytest.fixture(scope="module")
def dash():
    return json.loads(OUT.read_text())


@pytest.fixture(scope="module")
def con():
    import duckdb
    c = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    yield c
    c.close()


def test_file_is_strict_json():
    # Browsers' JSON.parse rejects NaN / Infinity, which Python's json module accepts by default.
    def reject(token):
        raise ValueError(f"non-standard JSON constant {token}")
    json.loads(OUT.read_text(), parse_constant=reject)


def test_totals(dash, con):
    t = dash["totals"]
    assert t["measurements"] == con.execute("SELECT count(*) FROM fact_measurement").fetchone()[0]
    assert t["quarantined"] == con.execute("SELECT count(*) FROM quarantine").fetchone()[0]
    assert t["stations"] == con.execute("SELECT count(DISTINCT station_id) FROM fact_measurement").fetchone()[0]


def test_quarantine_breakdown_sums_to_total(dash, con):
    got = {r["reason"]: r["rows"] for r in dash["quarantine"]}
    want = dict(con.execute("SELECT reason, count(*) FROM quarantine GROUP BY 1").fetchall())
    assert got == want and sum(got.values()) == dash["totals"]["quarantined"]


def test_raw_control_chart_points_match_source(dash, con):
    # The raw daily golden residual, recomputed from fact rows and certified references.
    raw = con.execute("""
        SELECT f.station_id, f.metric, CAST(f.measured_date AS VARCHAR) AS date,
               avg(f.value - r.reference_value) AS residual
        FROM fact_measurement f JOIN dim_golden_reference r USING (unit_id, metric, eye)
        WHERE f.test_type = 'golden' GROUP BY ALL""").df()
    stored = con.execute("""SELECT station_id, metric, CAST(date AS VARCHAR) AS date, residual
                            FROM drift_series WHERE variant = 'raw' AND residual IS NOT NULL""").df()
    m = stored.merge(raw, on=["station_id", "metric", "date"], suffixes=("_stored", "_sql"))
    assert len(m) == len(stored)
    assert np.allclose(m["residual_stored"], m["residual_sql"], rtol=0, atol=1e-12)


def test_dashboard_charts_match_stored_series(dash, con):
    stored = con.execute("""SELECT station_id, metric, CAST(date AS VARCHAR) AS date, residual, ewma
                            FROM drift_series WHERE variant = ?""", [PRIMARY_VARIANT]).df()
    rows = [dict(station_id=c["station_id"], metric=c["metric"], **p) for c in dash["charts"] for p in c["points"]]
    d = pd.DataFrame(rows)
    d["date"] = d["date"].str[:10]
    m = d.merge(stored, on=["station_id", "metric", "date"], suffixes=("_dash", "_db"))
    assert len(m) == len(stored) == len(d)
    ok = m["residual_db"].isna() | np.isclose(m["residual_dash"], m["residual_db"], atol=1e-6)
    assert ok.all()
    assert np.allclose(m["ewma_dash"], m["ewma_db"], atol=1e-6)


def test_cpk_recomputed_in_sql(dash, con):
    end = con.execute("SELECT max(measured_date) FROM fact_measurement").fetchone()[0]
    for r in dash["cpk"][:25]:
        spec = METRICS[r["metric"]]
        mu, sd, n = con.execute("""
            SELECT avg(value), stddev_samp(value), count(*) FROM fact_measurement
            WHERE test_type = 'production' AND station_id = ? AND metric = ? AND eye = ?
              AND measured_date > CAST(? AS DATE) - INTERVAL 30 DAY""",
                                [r["station_id"], r["metric"], r["eye"], end]).fetchone()
        parts = [(spec.usl - mu) / (3 * sd)] if spec.usl is not None else []
        parts += [(mu - spec.lsl) / (3 * sd)] if spec.lsl is not None else []
        assert n == r["n"]
        assert abs(min(parts) - r["cpk"]) < 1e-6


def test_cert_days_match_system_of_record(dash):
    s = sqlite3.connect(SOR_DB)
    want = dict(s.execute("""SELECT c.instrument_id, CAST(julianday(c.expires_on) - julianday(?) AS INTEGER)
                             FROM certifications c JOIN instruments i USING (instrument_id)
                             WHERE i.retired_on IS NULL""", [dash["as_of"]]).fetchall())
    s.close()
    got = {c["instrument_id"]: c["days_until_expiry"] for c in dash["certs"]}
    assert got == want


def test_findings_and_grr_are_copied_exactly(dash, con):
    assert len(dash["findings"]) == con.execute("SELECT count(*) FROM drift_findings").fetchone()[0]
    db = dict(con.execute("SELECT station_id || '|' || metric, pct_grr FROM grr_results").fetchall())
    for g in dash["grr"]:
        assert abs(db[f"{g['station_id']}|{g['metric']}"] - g["pct_grr"]) < 1e-6
