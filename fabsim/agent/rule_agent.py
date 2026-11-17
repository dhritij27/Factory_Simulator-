"""Deterministic baseline agent: same tools, same policy, no LLM.

It exists so the LLM agent has something to be compared against, and so the
policy is written down twice, independently (here in code, in runtime.py as
prose). Its answers are templated from tool results only.
"""
from __future__ import annotations

import re

from fabsim.agent import tools as T
from fabsim.agent.world import World

RANK = {"P1": 3, "P2": 2, "P3": 1}
INST_RE = re.compile(r"\b(?:CAM|CLR|ALN)-[A-Z0-9-]+\b")


class Recorder:
    """Calls tools and keeps a transcript in the same shape the LLM runtime produces."""

    def __init__(self, world: World):
        self.world, self.transcript = world, []

    def __call__(self, name: str, **args):
        self.transcript.append({"type": "tool_use", "name": name, "input": args})
        r = T.call_tool(self.world, name, args)
        self.transcript.append({"type": "tool_result", "name": name, "result": r})
        return r


def _candidates(question: str) -> list[str]:
    toks = re.findall(r"[A-Za-z0-9_\-]+", question)
    out = []
    for n in (4, 3, 2, 1):
        for i in range(len(toks) - n + 1):
            out.append(" ".join(toks[i:i + n]))
    return out


def find_station(call: Recorder, question: str) -> dict:
    for m in INST_RE.findall(question):
        r = call("resolve_station", label=m)
        if "station_id" in r:
            return r
    ambiguous = None
    seen = set()
    for c in _candidates(question):
        if not re.search(r"\d", c) or c in seen:
            continue
        seen.add(c)
        r = T.resolve_station(call.world, c)        # probe silently; only the chosen call is recorded
        if "station_id" in r:
            return call("resolve_station", label=c)
        if r.get("error") == "ambiguous" and ambiguous is None:
            ambiguous = c
    if ambiguous:
        return call("resolve_station", label=ambiguous)
    # Nothing matched: record a lookup of the most station-like token so the trail shows what was tried.
    label = next((t for t in re.findall(r"[A-Za-z0-9_\-]+", question) if re.search(r"[A-Za-z].*\d", t)), question)
    return call("resolve_station", label=label)


def assess(cert: dict, drift: list[dict]) -> str | None:
    days = cert.get("days_until_expiry")
    expired = cert.get("status") == "expired"
    if drift:
        return "P1" if expired or (days is not None and days <= T.CRITICAL_DAYS) else "P2"
    if expired:
        return "P2"
    if days is not None and days <= T.EXPIRING_SOON_DAYS:
        return "P3"
    return None


def run(world: World, question: str) -> dict:
    call = Recorder(world)
    st = find_station(call, question)
    if st.get("error") == "ambiguous":
        text = (f"'{st['input']}' matches more than one station: {', '.join(st['candidates'])}. "
                "Which one did you mean?\nDECISION: CLARIFY")
        return dict(answer=text, transcript=call.transcript)
    if "station_id" not in st:
        return dict(answer="I couldn't find a station matching that request.\nDECISION: NOT_FOUND",
                    transcript=call.transcript)
    sid = st["station_id"]
    findings = call("get_drift_findings", station_id=sid, include_cleared=False)["findings"]
    insts = call("get_station_instruments", station_id=sid)["instruments"]
    plans = []
    lines = [f"Station {sid}:"]
    for inst in insts:
        iid = inst["instrument_id"]
        cert = call("get_cert_status", instrument_id=iid)
        mine = [f for f in findings if f["instrument_id"] == iid]
        drift = [f for f in mine if f["action_level"] == "act"]
        pr = assess(cert, drift)
        for f in mine:
            level = "large enough to act on" if f["action_level"] == "act" else "watch only, too small to service"
            lines.append(f"- {f['metric']} drift on {iid} ({f['detectors']}), first alarm {f['first_alarm_date']}, "
                         f"recent shift {f['recent_shift_sigma']} sigma, {f['direction']}: {level}.")
        if cert.get("status") in ("expired", "expiring_soon"):
            lines.append(f"- {iid} certificate {cert['cert_id']} expires {cert['expires_on']} "
                         f"({cert['days_until_expiry']} days from {cert['as_of']}), status {cert['status']}.")
        if pr:
            plans.append((pr, iid, cert, drift))
    if not plans:
        lines.append("- Nothing actionable: no drift large enough to service and all certificates valid. No ticket needed.")
        return dict(answer="\n".join(lines) + "\nDECISION: NONE", transcript=call.transcript)

    plans.sort(key=lambda p: -RANK[p[0]])
    decisions = []
    for pr, iid, cert, drift in plans:
        existing = call("list_open_tickets", station_id=None, instrument_id=iid)["tickets"]
        if existing:
            lines.append(f"- {iid} already has ticket {existing[0]['ticket_id']} ({existing[0]['status']}); not duplicating.")
            decisions.append("EXISTING_TICKET")
            continue
        not_after = T.deadline_for(world, pr, cert.get("expires_on"))
        w = call("propose_service_window", station_id=sid, duration_hours=4, not_after=not_after)["windows"]
        if not w:
            lines.append(f"- {pr} work on {iid} needs a window by {not_after} but none is available. "
                         "Escalating to a human planner.")
            decisions.append("NEEDS_HUMAN")
            continue
        reason = (f"{', '.join(f['metric'] for f in drift)} drift" if drift else "certificate") + \
                 (f"; certificate {cert['status']}" if cert.get("status") in ("expired", "expiring_soon") else "")
        t = call("draft_maintenance_ticket", instrument_id=iid, priority=pr, reason=reason,
                 finding_ids=[f["finding_id"] for f in drift], window_start=w[0]["window_start"],
                 window_end=w[0]["window_end"])
        lines.append(f"- Drafted {t['ticket_id']} ({pr}) for {iid}, proposed window {w[0]['window_start']} to "
                     f"{w[0]['window_end']}. Needs human approval.")
        decisions.append(pr)
    decision = decisions[0]          # outcome for the most severe issue (plans are sorted by priority)
    return dict(answer="\n".join(lines) + f"\nDECISION: {decision}", transcript=call.transcript)
