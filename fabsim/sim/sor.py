"""System of record for instruments: certifications, calibration history, tickets, line schedule.

Built by the simulator so its instrument IDs match the measurement data. The
agent reads and writes this database; analytics never does.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from fabsim.config import SimConfig, Station

DDL = """
CREATE TABLE instruments (
    instrument_id TEXT PRIMARY KEY,
    instrument_type TEXT NOT NULL,
    station_id TEXT NOT NULL,
    vendor TEXT NOT NULL,
    installed_on TEXT NOT NULL,
    retired_on TEXT
);
CREATE TABLE certifications (
    cert_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
    issued_on TEXT NOT NULL,
    expires_on TEXT NOT NULL,
    issued_by TEXT NOT NULL
);
CREATE TABLE calibration_events (
    event_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
    performed_on TEXT NOT NULL,
    kind TEXT NOT NULL,
    result TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE service_tickets (
    ticket_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    status TEXT NOT NULL,          -- draft | open | scheduled | closed
    priority TEXT NOT NULL,        -- P1 | P2 | P3
    reason TEXT NOT NULL,
    finding_ids TEXT,
    created_on TEXT NOT NULL,
    created_by TEXT NOT NULL,
    service_window_start TEXT,
    service_window_end TEXT
);
CREATE TABLE line_schedule (
    station_id TEXT NOT NULL,
    window_start TEXT NOT NULL,    -- ISO datetime
    window_end TEXT NOT NULL,
    load TEXT NOT NULL             -- planned_downtime | low | normal | high
);
"""

VENDORS = {"camera": "Radiant-like", "colorimeter": "Konica-like", "align_rig": "in-house"}


def build_sor(cfg: SimConfig, stations: list[Station], instruments: list[dict], faults, rng: np.random.Generator,
              path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(DDL)
    as_of = cfg.start + timedelta(days=cfg.days - 1)
    start = cfg.start
    ev = 0
    for k, inst in enumerate(instruments):
        installed = start + timedelta(days=inst["valid_from_day"]) if inst["valid_from_day"] else start - timedelta(days=400)
        retired = (start + timedelta(days=inst["valid_to_day"])) if inst["valid_to_day"] is not None else None
        con.execute("INSERT INTO instruments VALUES (?,?,?,?,?,?)",
                    (inst["instrument_id"], inst["instrument_type"], inst["station_id"],
                     VENDORS[inst["instrument_type"]], installed.isoformat(), retired.isoformat() if retired else None))
        if retired:
            continue
        # Annual certificates. Spread expiry so that, as of the end of the simulation,
        # some are expired, some expire within 14 / 30 days, and most are fine.
        if inst["valid_from_day"]:
            issued = installed
        else:
            u = rng.random()
            if u < 0.08:
                days_left = int(rng.integers(-20, 0))          # expired
            elif u < 0.20:
                days_left = int(rng.integers(1, 15))           # expiring within 2 weeks
            elif u < 0.32:
                days_left = int(rng.integers(15, 31))          # expiring within a month
            else:
                days_left = int(rng.integers(31, 330))
            issued = as_of + timedelta(days=days_left) - timedelta(days=365)
        expires = issued + timedelta(days=365)
        con.execute("INSERT INTO certifications VALUES (?,?,?,?,?)",
                    (f"CERT-{k+1:04d}", inst["instrument_id"], issued.isoformat(), expires.isoformat(), "LAB-SV"))
        ev += 1
        con.execute("INSERT INTO calibration_events VALUES (?,?,?,?,?,?)",
                    (f"CAL-{ev:05d}", inst["instrument_id"], issued.isoformat(), "annual_certification", "pass", None))

    # A couple of tickets already open, so the agent has to avoid duplicates.
    open_on = [i for i in instruments if i["valid_to_day"] is None][:: max(1, len(instruments) // 3)][:2]
    for j, inst in enumerate(open_on):
        con.execute("INSERT INTO service_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (f"TKT-{j+1:04d}", inst["instrument_id"], inst["station_id"], "open", "P3",
                     "routine fixture cleaning", None, (as_of - timedelta(days=3)).isoformat(), "jdoe", None, None))

    # Line schedule for the 21 days after as_of: nightly low-load windows, weekly planned downtime.
    for s in stations:
        dow_down = int(rng.integers(0, 7))
        for d in range(1, 22):
            day = as_of + timedelta(days=d)
            if day.weekday() == dow_down:
                con.execute("INSERT INTO line_schedule VALUES (?,?,?,?)",
                            (s.station_id, f"{day.isoformat()}T06:00", f"{day.isoformat()}T14:00", "planned_downtime"))
            con.execute("INSERT INTO line_schedule VALUES (?,?,?,?)",
                        (s.station_id, f"{day.isoformat()}T22:00", f"{(day + timedelta(days=1)).isoformat()}T05:00",
                         "low" if d % 3 else "normal"))
    con.commit()
    con.close()
