"""Map whatever a station calls itself to one canonical station ID.

The resolver only knows the station master list (site, line, station number), not
the simulator's alias table. It tokenises the label, reads site / line / station
numbers from it, fills in the site from the file's origin when the label omits it,
and refuses to guess when two stations fit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from fabsim.config import Station, all_stations

SITE_WORDS = {"cm", "c"}
LINE_WORDS = {"l", "line"}
STATION_WORDS = {"st", "station", "s", "b", "bench", "stn"}
LAB_WORDS = {"sv": "LAB-SV", "rd": "LAB-RD"}


@dataclass(frozen=True)
class Resolution:
    station_id: str | None
    method: str          # exact | parsed | inferred_line | unresolved
    reason: str | None = None   # for unresolved: missing_station | ambiguous_station | unknown_station | site_conflict


def _tokens(label: str) -> list[str]:
    s = label.strip().lower()
    s = re.sub(r"([a-z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([a-z])", r"\1 \2", s)
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def parse_label(label: str) -> dict:
    toks = _tokens(label)
    out: dict = {}
    i = 0
    while i < len(toks):
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        num = int(nxt) if nxt is not None and nxt.isdigit() else None
        if t in LAB_WORDS:
            out["site"] = LAB_WORDS[t]
        elif t == "lab":
            pass
        elif t in SITE_WORDS and num is not None:
            out["site"] = f"CM{num}"
            i += 1
        elif t in LINE_WORDS and num is not None:
            out["line"] = num
            i += 1
        elif t in STATION_WORDS and num is not None:
            out["station"] = num
            i += 1
        i += 1
    return out


class StationResolver:
    def __init__(self, stations: list[Station] | None = None):
        self.stations = stations or all_stations()
        self.by_id = {s.station_id: s for s in self.stations}
        self.by_key = {(s.site_id, s.line, s.number): s.station_id for s in self.stations}

    @lru_cache(maxsize=None)
    def resolve(self, label: str | None, site_context: str) -> Resolution:
        if label is None or str(label).strip() == "" or str(label).lower() == "nan":
            return Resolution(None, "unresolved", "missing_station")
        label = str(label).strip()
        if label in self.by_id:
            if self.by_id[label].site_id != site_context:
                return Resolution(None, "unresolved", "site_conflict")
            return Resolution(label, "exact")
        p = parse_label(label)
        site = p.get("site", site_context)
        if site != site_context:
            return Resolution(None, "unresolved", "site_conflict")
        if "station" not in p:
            return Resolution(None, "unresolved", "unknown_station")
        if site.startswith("LAB"):
            sid = self.by_key.get((site, 0, p["station"]))
            return Resolution(sid, "parsed") if sid else Resolution(None, "unresolved", "unknown_station")
        if "line" in p:
            sid = self.by_key.get((site, p["line"], p["station"]))
            return Resolution(sid, "parsed") if sid else Resolution(None, "unresolved", "unknown_station")
        cands = [s.station_id for s in self.stations if s.site_id == site and s.number == p["station"]]
        if len(cands) == 1:
            return Resolution(cands[0], "inferred_line")
        if not cands:
            return Resolution(None, "unresolved", "unknown_station")
        return Resolution(None, "unresolved", "ambiguous_station")
