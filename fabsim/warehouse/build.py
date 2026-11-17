"""Build the DuckDB star schema from the lake.

fact_measurement            one row per loaded measurement
dim_site / dim_station      master data
dim_station_alias           every station label seen, and what it resolved to
dim_instrument              from the system of record (install / retire dates)
dim_unit                    every unit seen; golden units flagged
dim_test_spec               spec limits per metric and eye
dim_golden_reference        certified values for golden units
quarantine                  rows that failed validation, with the reason
ingest_alerts               schema / scale alerts, deduplicated to first and last sighting
ingest_files                one row per ingested file
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from fabsim.config import LAKE, METRICS, RAW, SITES, SOR_DB, WAREHOUSE_DB, all_stations


def connect(path: Path = WAREHOUSE_DB, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def build(lake: Path = LAKE, db: Path = WAREHOUSE_DB, raw: Path = RAW, sor: Path = SOR_DB, verbose: bool = True) -> None:
    con = connect(db)
    staged = str(lake / "staged" / "*.parquet")
    con.execute(f"""
        CREATE OR REPLACE TABLE fact_measurement AS
        SELECT row_number() OVER (ORDER BY measured_at, source_file, record_no, metric, eye) AS measurement_id,
               CAST(measured_at AS TIMESTAMP) AS measured_at,
               CAST(measured_at AS DATE)      AS measured_date,
               site_id, station_id, unit_id, instrument_id, instrument_imputed, operator_id,
               test_type, CAST(trial AS INTEGER) AS trial, metric, eye, value, source_file, record_no
        FROM read_parquet('{staged}', union_by_name = true)
    """)

    sites = pd.DataFrame([dict(site_id=s.site_id, kind=s.kind, vendor_format=s.vendor_format) for s in SITES])
    stations = pd.DataFrame([dict(station_id=s.station_id, site_id=s.site_id, line=s.line, station_number=s.number)
                             for s in all_stations()])
    specs = pd.DataFrame([dict(metric=m.name, eye=e, unit=m.unit, lsl=m.lsl, usl=m.usl,
                               plausible_min=m.plausible[0], plausible_max=m.plausible[1],
                               bias_threshold=m.bias_threshold)
                          for m in METRICS.values() for e in (["L", "R"] if m.per_eye else ["B"])])
    con.register("sites_df", sites)
    con.register("stations_df", stations)
    con.register("specs_df", specs)
    con.execute("CREATE OR REPLACE TABLE dim_site AS SELECT * FROM sites_df")
    con.execute("CREATE OR REPLACE TABLE dim_station AS SELECT * FROM stations_df")
    con.execute("CREATE OR REPLACE TABLE dim_test_spec AS SELECT * FROM specs_df")

    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"""
        CREATE OR REPLACE TABLE dim_instrument AS
        SELECT instrument_id, instrument_type, station_id, vendor,
               CAST(installed_on AS DATE) AS installed_on, CAST(retired_on AS DATE) AS retired_on
        FROM sqlite_scan('{sor}', 'instruments')
    """)
    cert = raw / "LAB-SV" / "golden_reference_certificates.csv"
    con.execute(f"CREATE OR REPLACE TABLE dim_golden_reference AS SELECT * FROM read_csv_auto('{cert}')")
    con.execute("""
        CREATE OR REPLACE TABLE dim_unit AS
        SELECT unit_id,
               any_value(site_id) AS first_site_id,
               unit_id IN (SELECT DISTINCT unit_id FROM dim_golden_reference) AS is_golden,
               min(measured_at) AS first_seen, count(*) AS n_measurements
        FROM fact_measurement GROUP BY unit_id
    """)

    q = list((lake / "quarantine").glob("*.parquet"))
    if q:
        con.execute(f"""CREATE OR REPLACE TABLE quarantine AS
                        SELECT * FROM read_parquet('{lake / "quarantine" / "*.parquet"}', union_by_name = true)""")
    else:
        con.execute("""CREATE OR REPLACE TABLE quarantine (record_no BIGINT, measured_at TIMESTAMP, site_id VARCHAR,
                       station_label VARCHAR, station_id VARCHAR, unit_id VARCHAR, metric VARCHAR, eye VARCHAR,
                       value DOUBLE, reason VARCHAR, source_file VARCHAR)""")

    con.execute(f"""
        CREATE OR REPLACE TABLE dim_station_alias AS
        SELECT station_label AS alias, site_id AS site_context, station_id, resolve_method AS method,
               count(*) AS n_rows
        FROM read_parquet('{staged}', union_by_name = true)
        GROUP BY ALL
        UNION ALL
        SELECT station_label, site_id, NULL, 'unresolved:' || reason, count(*)
        FROM quarantine WHERE reason IN ('ambiguous_station', 'unknown_station', 'site_conflict')
        GROUP BY ALL
    """)

    alerts = list((lake / "alerts").glob("*.parquet"))
    if alerts:
        con.execute(f"CREATE OR REPLACE TABLE ingest_alert_log AS SELECT * FROM read_parquet('{lake / 'alerts' / '*.parquet'}', union_by_name = true)")
        con.execute("""
            CREATE OR REPLACE TABLE ingest_alerts AS
            SELECT row_number() OVER (ORDER BY min(file_date), site_id, kind, field) AS alert_id,
                   site_id, vendor, kind, field, severity,
                   min(file_date) AS first_seen_date, max(file_date) AS last_seen_date,
                   arg_min(source_file, file_date) AS first_seen_file,
                   count(DISTINCT source_file) AS n_files,
                   arg_min(detail, file_date) AS detail
            FROM ingest_alert_log
            GROUP BY site_id, vendor, kind, field, severity
        """)
    manifest = json.loads((lake / "manifest.json").read_text())
    files = pd.DataFrame(list(manifest.values()))
    con.register("files_df", files)
    con.execute("CREATE OR REPLACE TABLE ingest_files AS SELECT * FROM files_df")
    if verbose:
        n = con.execute("SELECT count(*) FROM fact_measurement").fetchone()[0]
        nq = con.execute("SELECT count(*) FROM quarantine").fetchone()[0]
        na = con.execute("SELECT count(*) FROM ingest_alerts").fetchone()[0] if alerts else 0
        print(f"  warehouse: {n:,} measurements, {nq:,} quarantined, {na} distinct alerts -> {db}")
    con.close()
