"""The data an agent can see and change, behind one interface.

``World.from_databases`` reads the real system of record (SQLite) and the analysis
findings (DuckDB). ``World.from_fixture`` builds a small, fully specified world for
evaluation scenarios. Tools only talk to a World, so the same tools and agents run
against either.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from fabsim.config import ACTION_SHIFT_SIGMA, INSTRUMENT_FOR_METRIC, INSTRUMENT_PREFIX, INSTRUMENT_TYPES, SOR_DB, WAREHOUSE_DB, all_stations


@dataclass
class World:
    as_of: date
    instruments: pd.DataFrame        # instrument_id, instrument_type, station_id, retired_on
    certifications: pd.DataFrame     # cert_id, instrument_id, issued_on, expires_on, issued_by
    tickets: pd.DataFrame            # service_tickets columns
    schedule: pd.DataFrame           # station_id, window_start, window_end, load
    drift_findings: pd.DataFrame     # finding_id, station_id, metric, detectors, first/last_alarm_date, status, ...
    grr: pd.DataFrame = field(default_factory=pd.DataFrame)
    sor_path: Path | None = None     # when set, drafted tickets are persisted here
    created: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ constructors
    @classmethod
    def from_databases(cls, sor: Path = SOR_DB, warehouse: Path = WAREHOUSE_DB) -> "World":
        import duckdb

        con = sqlite3.connect(sor)
        inst = pd.read_sql("SELECT * FROM instruments", con)
        certs = pd.read_sql("SELECT * FROM certifications", con)
        tickets = pd.read_sql("SELECT * FROM service_tickets", con)
        sched = pd.read_sql("SELECT * FROM line_schedule", con)
        con.close()
        w = duckdb.connect(str(warehouse), read_only=True)
        findings = w.execute("SELECT * FROM drift_findings").df()
        grr = w.execute("SELECT station_id, metric, pct_grr, pct_grr_ci_low, pct_grr_ci_high, verdict FROM grr_results").df()
        as_of = pd.Timestamp(w.execute("SELECT data_through FROM analysis_runs").fetchone()[0]).date()
        w.close()
        for c in ("first_alarm_date", "last_alarm_date"):
            findings[c] = findings[c].astype(str)
        return cls(as_of, inst, certs, tickets, sched, findings, grr, sor_path=sor)

    @classmethod
    def from_fixture(cls, spec: dict) -> "World":
        """spec keys (all optional):
        as_of: 'YYYY-MM-DD'
        cert_days: {instrument_id: days until expiry (negative = expired)}; default 200
        drift: [{station_id, metric, status, shift_sigma}]
        tickets: [{instrument_id, status, priority, reason}]
        schedule: 'normal' | 'none' | 'late' | {station_id: 'none'|'late'}
        grr: [{station_id, metric, pct_grr, verdict}]
        """
        as_of = date.fromisoformat(spec.get("as_of", "2026-07-05"))
        rows, certs = [], []
        for s in all_stations():
            for t in INSTRUMENT_TYPES:
                iid = f"{INSTRUMENT_PREFIX[t]}-{s.station_id}"
                rows.append(dict(instrument_id=iid, instrument_type=t, station_id=s.station_id, retired_on=None))
                left = spec.get("cert_days", {}).get(iid, 200)
                exp = as_of + timedelta(days=left)
                certs.append(dict(cert_id=f"CERT-{iid}", instrument_id=iid, issued_on=(exp - timedelta(days=365)).isoformat(),
                                  expires_on=exp.isoformat(), issued_by="LAB-SV"))
        tickets = []
        for k, t in enumerate(spec.get("tickets", [])):
            inst = next(r for r in rows if r["instrument_id"] == t["instrument_id"])
            tickets.append(dict(ticket_id=f"TKT-{k+1:04d}", instrument_id=t["instrument_id"], station_id=inst["station_id"],
                                status=t.get("status", "open"), priority=t.get("priority", "P3"),
                                reason=t.get("reason", "routine fixture cleaning"), finding_ids=None,
                                created_on=(as_of - timedelta(days=2)).isoformat(), created_by="jdoe",
                                service_window_start=None, service_window_end=None))
        sched_spec = spec.get("schedule", "normal")
        sched = []
        for s in all_stations():
            mode = sched_spec.get(s.station_id, "normal") if isinstance(sched_spec, dict) else sched_spec
            if mode == "none":
                continue
            first = 10 if mode == "late" else 1
            for d in range(first, 22):
                day = as_of + timedelta(days=d)
                if day.weekday() == 2:
                    sched.append(dict(station_id=s.station_id, window_start=f"{day}T06:00", window_end=f"{day}T14:00",
                                      load="planned_downtime"))
                sched.append(dict(station_id=s.station_id, window_start=f"{day}T22:00",
                                  window_end=f"{day + timedelta(days=1)}T05:00", load="low" if d % 3 else "normal"))
        findings = []
        for k, f in enumerate(spec.get("drift", [])):
            sigma = f.get("shift_sigma", 2.0)
            findings.append(dict(
                finding_id=f"DF-{k+1:04d}", station_id=f["station_id"], metric=f["metric"],
                detectors=f.get("detectors", "cusum,ewma"),
                first_alarm_date=(as_of - timedelta(days=f.get("age_days", 6))).isoformat(),
                last_alarm_date=(as_of - timedelta(days=0 if f.get("status", "active") == "active" else 20)).isoformat(),
                n_episodes=1, status=f.get("status", "active"),
                recent_shift_sigma=sigma, peak_shift_sigma=abs(sigma), direction="reading high" if sigma > 0 else "reading low",
                action_level="act" if abs(sigma) >= ACTION_SHIFT_SIGMA else "watch",
                instrument_id=f"{INSTRUMENT_PREFIX[INSTRUMENT_FOR_METRIC[f['metric']]]}-{f['station_id']}"))
        grr = pd.DataFrame(spec.get("grr", []), columns=["station_id", "metric", "pct_grr", "pct_grr_ci_low",
                                                         "pct_grr_ci_high", "verdict"])
        return cls(as_of, pd.DataFrame(rows), pd.DataFrame(certs),
                   pd.DataFrame(tickets, columns=["ticket_id", "instrument_id", "station_id", "status", "priority",
                                                  "reason", "finding_ids", "created_on", "created_by",
                                                  "service_window_start", "service_window_end"]),
                   pd.DataFrame(sched, columns=["station_id", "window_start", "window_end", "load"]),
                   pd.DataFrame(findings, columns=["finding_id", "station_id", "metric", "detectors", "first_alarm_date",
                                                   "last_alarm_date", "n_episodes", "status", "recent_shift_sigma", "peak_shift_sigma", "action_level",
                                                   "direction", "instrument_id"]), grr)

    # ------------------------------------------------------------------ writes
    def add_ticket(self, t: dict) -> None:
        self.tickets = pd.concat([self.tickets, pd.DataFrame([t])], ignore_index=True)
        self.created.append(t)
        if self.sor_path is not None:
            con = sqlite3.connect(self.sor_path)
            cols = ["ticket_id", "instrument_id", "station_id", "status", "priority", "reason", "finding_ids",
                    "created_on", "created_by", "service_window_start", "service_window_end"]
            con.execute(f"INSERT INTO service_tickets ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [t.get(c) for c in cols])
            con.commit()
            con.close()

    def now(self) -> datetime:
        return datetime.combine(self.as_of, datetime.min.time()).replace(hour=18)
