"""Tools the calibration agent can call, and the escalation policy they implement.

Every tool returns plain JSON-able data. Every number or date the agent reports
must come from one of these results; ``grounding.py`` checks that.

Escalation policy (written in the system prompt, and implemented independently by
the rule-based baseline in ``rule_agent.py``):

  "drift" below means an active finding with action_level "act": its recent shift is at least
  ACTION_SHIFT_SIGMA repeatability sigmas. "watch" findings are reported but never escalate.

  active drift  + cert expired or expiring within 14 days  -> P1, service within 3 days
  active drift  + cert otherwise valid                     -> P2, service within 7 days
  no drift      + cert expired                             -> P2, service within 7 days
  no drift      + cert expiring within 30 days             -> P3, service before expiry
  nothing wrong                                            -> no ticket
  an open/draft ticket already covers the instrument       -> don't duplicate it
  no service window before the deadline                    -> hand to a human
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from fabsim.config import INSTRUMENT_FOR_METRIC, SITES
from fabsim.agent.world import World
from fabsim.ingest.stations import StationResolver

_resolver = StationResolver()
EXPIRING_SOON_DAYS = 30
CRITICAL_DAYS = 14
DEADLINE_DAYS = {"P1": 3, "P2": 7}


def _station_exists(world: World, station_id: str) -> bool:
    return station_id in set(world.instruments["station_id"])


def resolve_station(world: World, label: str) -> dict:
    """Map any station label (or an instrument ID) to the canonical station ID."""
    label = (label or "").strip()
    inst = world.instruments[world.instruments["instrument_id"] == label]
    if len(inst):
        return {"station_id": inst.iloc[0]["station_id"], "method": "instrument_id", "input": label}
    hits = {}
    for site in SITES:
        r = _resolver.resolve(label, site.site_id)
        if r.station_id:
            hits[r.station_id] = r.method
    if len(hits) == 1:
        sid, method = next(iter(hits.items()))
        return {"station_id": sid, "method": method, "input": label}
    if len(hits) > 1:
        return {"error": "ambiguous", "input": label, "candidates": sorted(hits),
                "message": "label matches more than one station; ask which one"}
    return {"error": "not_found", "input": label, "message": "no station matches this label"}


def get_station_instruments(world: World, station_id: str) -> dict:
    if not _station_exists(world, station_id):
        return {"error": "not_found", "station_id": station_id}
    df = world.instruments[(world.instruments["station_id"] == station_id) & world.instruments["retired_on"].isna()]
    return {"station_id": station_id,
            "instruments": [{"instrument_id": r.instrument_id, "instrument_type": r.instrument_type} for r in df.itertuples()]}


def get_cert_status(world: World, instrument_id: str) -> dict:
    c = world.certifications[world.certifications["instrument_id"] == instrument_id]
    if not len(c):
        if instrument_id in set(world.instruments["instrument_id"]):
            return {"instrument_id": instrument_id, "status": "no_certificate_on_record"}
        return {"error": "not_found", "instrument_id": instrument_id}
    row = c.sort_values("expires_on").iloc[-1]
    days = (date.fromisoformat(row["expires_on"]) - world.as_of).days
    status = "expired" if days < 0 else ("expiring_soon" if days <= EXPIRING_SOON_DAYS else "valid")
    return {"instrument_id": instrument_id, "cert_id": row["cert_id"], "issued_on": row["issued_on"],
            "expires_on": row["expires_on"], "days_until_expiry": int(days), "status": status,
            "as_of": world.as_of.isoformat()}


def get_drift_findings(world: World, station_id: str | None = None, include_cleared: bool = False) -> dict:
    f = world.drift_findings
    if station_id:
        if not _station_exists(world, station_id):
            return {"error": "not_found", "station_id": station_id}
        f = f[f["station_id"] == station_id]
    if not include_cleared:
        f = f[f["status"] == "active"]
    cols = ["finding_id", "station_id", "metric", "detectors", "first_alarm_date", "last_alarm_date", "status",
            "recent_shift_sigma", "peak_shift_sigma", "action_level", "direction", "instrument_id"]
    out = []
    for r in f[cols].to_dict(orient="records"):
        r["recent_shift_sigma"] = round(float(r["recent_shift_sigma"]), 2)
        r["peak_shift_sigma"] = round(float(r["peak_shift_sigma"]), 2)
        r["first_alarm_date"], r["last_alarm_date"] = str(r["first_alarm_date"]), str(r["last_alarm_date"])
        out.append(r)
    return {"as_of": world.as_of.isoformat(), "findings": out}


def list_open_tickets(world: World, station_id: str | None = None, instrument_id: str | None = None) -> dict:
    t = world.tickets[world.tickets["status"].isin(["draft", "open", "scheduled"])]
    if station_id:
        t = t[t["station_id"] == station_id]
    if instrument_id:
        t = t[t["instrument_id"] == instrument_id]
    cols = ["ticket_id", "instrument_id", "station_id", "status", "priority", "reason", "created_on"]
    return {"tickets": t[cols].to_dict(orient="records")}


def propose_service_window(world: World, station_id: str, duration_hours: float, not_after: str) -> dict:
    """Earliest planned-downtime or low-load windows that fit, starting no later than ``not_after``."""
    if not _station_exists(world, station_id):
        return {"error": "not_found", "station_id": station_id}
    try:
        limit = datetime.fromisoformat(not_after) if "T" in not_after else datetime.fromisoformat(not_after + "T23:59")
    except ValueError:
        return {"error": "bad_date", "message": "not_after must be YYYY-MM-DD"}
    s = world.schedule[(world.schedule["station_id"] == station_id) & world.schedule["load"].isin(["planned_downtime", "low"])]
    opts = []
    for r in s.itertuples():
        start, end = datetime.fromisoformat(r.window_start), datetime.fromisoformat(r.window_end)
        if start <= world.now() or start > limit:
            continue
        if (end - start).total_seconds() / 3600 >= duration_hours:
            opts.append({"window_start": r.window_start, "window_end": r.window_end, "load": r.load})
    opts.sort(key=lambda o: (o["window_start"], o["load"] != "planned_downtime"))
    return {"station_id": station_id, "not_after": not_after, "duration_hours": duration_hours, "windows": opts[:3]}


def draft_maintenance_ticket(world: World, instrument_id: str, priority: str, reason: str,
                             finding_ids: list[str] | None = None, window_start: str | None = None,
                             window_end: str | None = None) -> dict:
    """Create a DRAFT ticket for a human to approve. Never opens or schedules anything itself."""
    inst = world.instruments[world.instruments["instrument_id"] == instrument_id]
    if not len(inst):
        return {"error": "not_found", "instrument_id": instrument_id}
    if priority not in {"P1", "P2", "P3"}:
        return {"error": "bad_priority", "message": "priority must be P1, P2 or P3"}
    existing = list_open_tickets(world, instrument_id=instrument_id)["tickets"]
    if existing:
        return {"error": "duplicate", "message": "an open or draft ticket already covers this instrument",
                "existing": existing}
    tid = f"TKT-D{len(world.tickets) + 1:04d}"
    t = dict(ticket_id=tid, instrument_id=instrument_id, station_id=inst.iloc[0]["station_id"], status="draft",
             priority=priority, reason=reason, finding_ids=",".join(finding_ids or []) or None,
             created_on=world.as_of.isoformat(), created_by="calibration-agent",
             service_window_start=window_start, service_window_end=window_end)
    world.add_ticket(t)
    return {"ticket_id": tid, "status": "draft", "priority": priority, "instrument_id": instrument_id,
            "service_window_start": window_start, "service_window_end": window_end,
            "message": "draft created; a human must approve it before it is opened"}


def deadline_for(world: World, priority: str, cert_expires_on: str | None = None) -> str:
    if priority in DEADLINE_DAYS:
        return (world.as_of + timedelta(days=DEADLINE_DAYS[priority])).isoformat()
    if cert_expires_on:
        return cert_expires_on
    return (world.as_of + timedelta(days=14)).isoformat()


TOOLS = {
    "resolve_station": resolve_station,
    "get_station_instruments": get_station_instruments,
    "get_cert_status": get_cert_status,
    "get_drift_findings": get_drift_findings,
    "list_open_tickets": list_open_tickets,
    "propose_service_window": propose_service_window,
    "draft_maintenance_ticket": draft_maintenance_ticket,
}

# JSON schemas for the LLM (strict tool use: additionalProperties false, every property required,
# optional values expressed as nullable).
def _nullable(t: str) -> dict:
    return {"type": [t, "null"]}


TOOL_SCHEMAS = [
    dict(name="resolve_station",
         description="Map any station label (e.g. 'cm2_line3_st2', 'C2L3S2', 'SV Bench 1') or an instrument ID to the "
                     "canonical station ID. Returns an error with candidates if the label is ambiguous.",
         input_schema={"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"],
                       "additionalProperties": False}),
    dict(name="get_station_instruments",
         description="List the instruments currently installed on a station (canonical station ID).",
         input_schema={"type": "object", "properties": {"station_id": {"type": "string"}}, "required": ["station_id"],
                       "additionalProperties": False}),
    dict(name="get_cert_status",
         description="Calibration certificate for one instrument: issue and expiry dates, days until expiry as of "
                     "today, and status (valid / expiring_soon / expired).",
         input_schema={"type": "object", "properties": {"instrument_id": {"type": "string"}},
                       "required": ["instrument_id"], "additionalProperties": False}),
    dict(name="get_drift_findings",
         description="Drift findings from the measurement analytics (EWMA / CUSUM on golden-unit residuals). Active "
                     "findings only unless include_cleared is true. Each finding names the affected instrument and has "
                     "action_level 'act' (shift reached the service threshold during this alarm) or 'watch' (alarm is real but the "
                     "shift has stayed too small to service).",
         input_schema={"type": "object", "properties": {"station_id": _nullable("string"),
                                                        "include_cleared": {"type": "boolean"}},
                       "required": ["station_id", "include_cleared"], "additionalProperties": False}),
    dict(name="list_open_tickets",
         description="Open, draft or scheduled service tickets, filtered by station and/or instrument.",
         input_schema={"type": "object", "properties": {"station_id": _nullable("string"),
                                                        "instrument_id": _nullable("string")},
                       "required": ["station_id", "instrument_id"], "additionalProperties": False}),
    dict(name="propose_service_window",
         description="Earliest low-load or planned-downtime windows on a station that fit the duration and start no "
                     "later than not_after (YYYY-MM-DD). Returns up to three.",
         input_schema={"type": "object", "properties": {"station_id": {"type": "string"},
                                                        "duration_hours": {"type": "number"},
                                                        "not_after": {"type": "string"}},
                       "required": ["station_id", "duration_hours", "not_after"], "additionalProperties": False}),
    dict(name="draft_maintenance_ticket",
         description="Create a DRAFT maintenance ticket for a human to approve. Refuses if a ticket already covers the "
                     "instrument. Never opens or schedules work by itself.",
         input_schema={"type": "object", "properties": {
             "instrument_id": {"type": "string"}, "priority": {"type": "string", "enum": ["P1", "P2", "P3"]},
             "reason": {"type": "string"}, "finding_ids": {"type": "array", "items": {"type": "string"}},
             "window_start": _nullable("string"), "window_end": _nullable("string")},
             "required": ["instrument_id", "priority", "reason", "finding_ids", "window_start", "window_end"],
             "additionalProperties": False}),
]
for _s in TOOL_SCHEMAS:
    _s["strict"] = True


def call_tool(world: World, name: str, args: dict) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": "unknown_tool", "name": name}
    try:
        return fn(world, **args)
    except TypeError as e:
        return {"error": "bad_arguments", "message": str(e)}


def instrument_for(metric: str) -> str:
    return INSTRUMENT_FOR_METRIC[metric]
