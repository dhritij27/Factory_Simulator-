"""Ingest raw vendor exports into the lake (Parquet), then build the DuckDB warehouse.

Per file:  parse -> schema check -> row validation -> station canonicalisation
           -> instrument imputation -> stream scale check -> staged / quarantine Parquet

Files already ingested (same path and content hash) are skipped, so the job can run
on a schedule and only pick up new exports.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd

from fabsim.config import INSTRUMENT_FOR_METRIC, LAKE, METRICS, RAW, SITES, SOR_DB
from fabsim.ingest.parsers import PARSERS, FileRejected
from fabsim.ingest.schema import load_mappings
from fabsim.ingest.stations import StationResolver

PROFILE_WARMUP_FILES = 5
SCALE_RATIO_LIMITS = (0.2, 5.0)
SCALE_MIN_VALUES = 8
FILE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class InstrumentRegistry:
    """Which instrument was installed on which station on which date (from the system of record)."""

    def __init__(self, sor_path: Path = SOR_DB):
        con = sqlite3.connect(sor_path)
        self.df = pd.read_sql("SELECT instrument_id, instrument_type, station_id, installed_on, retired_on FROM instruments", con)
        con.close()
        self.df["installed_on"] = pd.to_datetime(self.df["installed_on"])
        self.df["retired_on"] = pd.to_datetime(self.df["retired_on"]).fillna(pd.Timestamp("2100-01-01"))
        self._owner = dict(zip(self.df["instrument_id"], self.df["station_id"]))

    def owner(self, instrument_id: str) -> str | None:
        return self._owner.get(instrument_id)

    def lookup(self, station_id: pd.Series, metric: pd.Series, when: pd.Series) -> pd.Series:
        itype = metric.map(INSTRUMENT_FOR_METRIC)
        q = pd.DataFrame({"station_id": station_id.values, "instrument_type": itype.values,
                          "when": when.dt.normalize().values, "_i": np.arange(len(station_id))})
        m = q.merge(self.df, on=["station_id", "instrument_type"], how="left")
        m = m[(m["when"] >= m["installed_on"]) & (m["when"] <= m["retired_on"])]
        out = pd.Series([None] * len(q), dtype=object)
        out.iloc[m["_i"].to_numpy()] = m["instrument_id"].to_numpy()
        return out.set_axis(station_id.index)


class Ingestor:
    def __init__(self, raw: Path = RAW, lake: Path = LAKE, sor: Path = SOR_DB, full: bool = False):
        self.raw, self.lake = raw, lake
        self.mappings = load_mappings()
        self.resolver = StationResolver()
        self.instruments = InstrumentRegistry(sor)
        self.manifest_path = lake / "manifest.json"
        self.profile_path = lake / "stream_profiles.json"
        if full and lake.exists():
            for p in sorted(lake.rglob("*"), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
        lake.mkdir(parents=True, exist_ok=True)
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        self.profiles = json.loads(self.profile_path.read_text()) if self.profile_path.exists() else {}

    # ------------------------------------------------------------------ helpers
    def _write(self, kind: str, rel: str, df: pd.DataFrame) -> None:
        out = self.lake / kind / (rel.replace("/", "__") + ".parquet")
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)

    def _issue_rows(self, site_id, vendor, rel, fdate, issues):
        return [dict(site_id=site_id, vendor=vendor, source_file=rel, file_date=fdate, kind=i.kind, field=i.field,
                     severity=i.severity, detail=i.detail) for i in issues]

    # ------------------------------------------------------------------ per file
    def ingest_file(self, path: Path, site_id: str, vendor: str) -> dict:
        rel = f"{site_id}/{path.name}"
        m = FILE_DATE.search(path.name)
        fdate = m.group(1) if m else None
        t0 = time.time()
        try:
            df, issues = PARSERS[vendor](path, self.mappings)
        except FileRejected as e:
            alerts = self._issue_rows(site_id, vendor, rel, fdate, e.issues)
            alerts.append(dict(site_id=site_id, vendor=vendor, source_file=rel, file_date=fdate, kind="file_rejected",
                               field="*", severity="error", detail=e.reason))
            self._write("alerts", rel, pd.DataFrame(alerts))
            return dict(source_file=rel, status="rejected", rows_loaded=0, rows_quarantined=0, seconds=time.time() - t0)
        alerts = self._issue_rows(site_id, vendor, rel, fdate, issues)

        reason = pd.Series(df["parse_reason"].to_numpy(), index=df.index, dtype=object)

        def flag(mask, why):
            nonlocal reason
            reason = reason.where(~(mask & reason.isna()), why)

        flag(df["measured_at"].isna(), "missing_timestamp")
        res = df["station_label"].map(lambda s: self.resolver.resolve(s, site_id))
        df["station_id"] = res.map(lambda r: r.station_id)
        df["resolve_method"] = res.map(lambda r: r.method)
        # An ambiguous label (e.g. "ST-01" when two lines have a station 1) can still be settled by the
        # instrument ID, which is unique to one station in the registry. Never guess otherwise.
        amb = res.map(lambda r: r.reason == "ambiguous_station") & df["instrument_id"].notna()
        if amb.any():
            owner = df.loc[amb, "instrument_id"].map(self.instruments.owner)
            site_ok = owner.notna() & owner.astype(str).str.startswith(site_id + "-")
            idx = owner[site_ok].index
            df.loc[idx, "station_id"] = owner[site_ok]
            df.loc[idx, "resolve_method"] = "instrument_lookup"
        unresolved = df["station_id"].isna()
        reason = reason.where(~(unresolved & reason.isna()), res.map(lambda r: r.reason))
        flag(df["unit_id"].isna(), "missing_unit")
        flag(df["test_type"].isna(), "unknown_test_type")
        flag(~df["eye"].isin(["L", "R", "B"]), "bad_eye")
        flag(df["value"].isna(), "bad_value")
        known = df["metric"].isin(list(METRICS))
        flag(~known, "unmapped_field")
        lo = df["metric"].map(lambda k: METRICS[k].plausible[0] if k in METRICS else np.nan)
        hi = df["metric"].map(lambda k: METRICS[k].plausible[1] if k in METRICS else np.nan)
        flag(known & ((df["value"] < lo) | (df["value"] > hi)), "out_of_range")

        # Instrument imputation: fill a missing instrument from the registry, and say so.
        df["instrument_imputed"] = False
        need = reason.isna() & df["instrument_id"].isna()
        if need.any():
            filled = self.instruments.lookup(df.loc[need, "station_id"], df.loc[need, "metric"], df.loc[need, "measured_at"])
            df.loc[need, "instrument_id"] = filled
            df.loc[need & df["instrument_id"].notna(), "instrument_imputed"] = True
        flag(df["instrument_id"].isna(), "missing_instrument")

        # Stream scale check: catches silent unit changes that range checks miss. A unit change
        # rescales the spread of a stream; a drift or step moves its location but not its spread,
        # so we compare robust spread (MAD) to the stream's baseline.
        ok = reason.isna()
        for (sid, metric), g in df[ok].groupby(["station_id", "metric"]):
            if len(g) < SCALE_MIN_VALUES:
                continue
            key = f"{sid}|{metric}"
            v = g["value"].to_numpy()
            typical = float(np.median(np.abs(v - np.median(v))))
            prof = self.profiles.get(key)
            if prof is None or prof["n_files"] < PROFILE_WARMUP_FILES:
                prev = prof or {"n_files": 0, "typicals": []}
                prev["typicals"].append(typical)
                prev["n_files"] += 1
                prev["typical"] = float(np.median(prev["typicals"]))
                self.profiles[key] = prev
                continue
            ratio = typical / prof["typical"] if prof["typical"] > 0 else np.inf
            if not (SCALE_RATIO_LIMITS[0] <= ratio <= SCALE_RATIO_LIMITS[1]):
                reason.loc[g.index] = "scale_shift_suspected"
                alerts.append(dict(site_id=site_id, vendor=vendor, source_file=rel, file_date=fdate, kind="scale_shift",
                                   field=f"{sid}:{metric}", severity="error",
                                   detail=f"spread (MAD) of {metric} is {ratio:.3g}x its baseline; possible unit change. "
                                          f"Rows quarantined."))

        df["site_id"] = site_id
        df["source_file"] = rel
        good = df[reason.isna()].drop(columns=["parse_reason"])
        bad = df[reason.notna()].assign(reason=reason[reason.notna()]).drop(columns=["parse_reason"])
        good = good.astype({"trial": "int32", "instrument_imputed": bool})
        self._write("staged", rel, good[["record_no", "measured_at", "site_id", "station_id", "station_label",
                                         "resolve_method", "unit_id", "instrument_id", "instrument_imputed",
                                         "operator_id", "test_type", "trial", "metric", "eye", "value", "source_file"]])
        if len(bad):
            b = bad[["record_no", "measured_at", "site_id", "station_label", "station_id", "unit_id", "metric", "eye",
                     "value", "reason", "source_file"]].copy()
            b["metric"] = b["metric"].astype(str)
            b["station_id"] = b["station_id"].astype(object)
            self._write("quarantine", rel, b)
        if alerts:
            self._write("alerts", rel, pd.DataFrame(alerts))
        return dict(source_file=rel, status="loaded", rows_loaded=int(len(good)), rows_quarantined=int(len(bad)),
                    seconds=round(time.time() - t0, 3))

    # ------------------------------------------------------------------ run
    def run(self, verbose: bool = True) -> list[dict]:
        results = []
        for site in SITES:
            d = self.raw / site.site_id
            if not d.exists():
                continue
            files = sorted(p for p in d.iterdir() if p.suffix in {".csv", ".jsonl", ".xlsx"}
                           and not p.name.startswith("golden_reference"))
            n_new = 0
            for p in files:
                rel = f"{site.site_id}/{p.name}"
                h = _sha1(p)
                if self.manifest.get(rel, {}).get("sha1") == h:
                    continue
                r = self.ingest_file(p, site.site_id, site.vendor_format)
                r["sha1"] = h
                r["ingested_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
                self.manifest[rel] = r
                results.append(r)
                n_new += 1
            if verbose:
                print(f"  {site.site_id}: {n_new} new file(s), {len(files) - n_new} unchanged")
        self.manifest_path.write_text(json.dumps(self.manifest, indent=1))
        self.profile_path.write_text(json.dumps(self.profiles))
        return results
