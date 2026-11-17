"""One parser per vendor format. Each returns a long frame in the common shape:

record_no, measured_at, station_label, unit_id, instrument_id, operator_id,
test_type, trial, metric, eye, value, parse_reason

``parse_reason`` is set for rows the parser could read but not map (e.g. a value
under an unapproved field name); those go to quarantine rather than being dropped.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fabsim.ingest.schema import REQUIRED, SchemaIssue, check_schema

COLUMNS = ["record_no", "measured_at", "station_label", "unit_id", "instrument_id", "operator_id",
           "test_type", "trial", "metric", "eye", "value", "parse_reason"]

TEST_TYPES = {
    "PROD": "production", "GOLDEN": "golden", "MSA": "msa",
    "prod": "production", "golden": "golden", "grr": "msa",
    "Production": "production", "Golden": "golden", "GRR": "msa",
    "Eng": "production",
}


class FileRejected(Exception):
    """The file is unusable as a whole (a required field is missing)."""

    def __init__(self, reason: str, issues: list[SchemaIssue]):
        super().__init__(reason)
        self.reason = reason
        self.issues = issues


def _blank_to_none(s: pd.Series) -> pd.Series:
    return s.where(s.notna() & (s.astype(str).str.strip() != ""), None)


def _require(vendor: str, rename: dict, observed: list[str], issues: list[SchemaIssue]) -> None:
    present = {rename.get(f, f) for f in observed}
    missing = REQUIRED[vendor] - present
    if missing:
        raise FileRejected(f"missing required field(s): {sorted(missing)}", issues)


def parse_cm1(path: Path, mappings) -> tuple[pd.DataFrame, list[SchemaIssue]]:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    rename, issues = check_schema("cm1_csv", list(raw.columns), mappings, ordered=True)
    _require("cm1_csv", rename, list(raw.columns), issues)
    raw = raw.rename(columns=rename)
    df = pd.DataFrame({
        "record_no": np.arange(len(raw)),
        "measured_at": pd.to_datetime(_blank_to_none(raw["timestamp"]), format="%Y-%m-%d %H:%M:%S", errors="coerce"),
        "station_label": _blank_to_none(raw["station"]),
        "unit_id": _blank_to_none(raw["unit_sn"]),
        "instrument_id": _blank_to_none(raw.get("instrument", pd.Series([""] * len(raw)))),
        "operator_id": _blank_to_none(raw.get("operator", pd.Series([""] * len(raw)))),
        "test_type": raw.get("test_type", pd.Series([""] * len(raw))).map(TEST_TYPES),
        "trial": 1,
        "metric": raw["metric"],
        "eye": raw["eye"],
        "value": pd.to_numeric(raw["value"], errors="coerce"),
        "parse_reason": None,
    })
    return df[COLUMNS], issues


def parse_cm2(path: Path, mappings) -> tuple[pd.DataFrame, list[SchemaIssue]]:
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    top, inner = set(), set()
    for r in recs:
        top.update(r.keys())
        for blk in (r.get("results") or {}).values():
            inner.update(blk.keys())
    observed = sorted(top) + [f"results.{k}" for k in sorted(inner)]
    rename, issues = check_schema("cm2_jsonl", observed, mappings)
    _require("cm2_jsonl", rename, observed, issues)
    key_map = {k.split(".", 1)[1]: v.split(".", 1)[1] for k, v in rename.items() if k.startswith("results.")}
    known = {"mtf50", "lum_uniformity", "delta_uv", "vert_misalign"}
    rows = []
    for i, r in enumerate(recs):
        inst = r.get("instruments") or {}
        meta = (i, r.get("ts"), r.get("station_name"), r.get("serial"), r.get("op"),
                TEST_TYPES.get(r.get("kind")), r.get("trial", 1))
        for eye_key, blk in (r.get("results") or {}).items():
            eye = "B" if eye_key == "binocular" else eye_key
            for k, v in blk.items():
                metric = key_map.get(k, k)
                reason = None if metric in known else "unmapped_field"
                inst_id = {"mtf50": inst.get("camera"), "lum_uniformity": inst.get("camera"),
                           "delta_uv": inst.get("colorimeter"), "vert_misalign": inst.get("align")}.get(metric)
                rows.append((meta[0], meta[1], meta[2], meta[3], inst_id, meta[4], meta[5], meta[6],
                             metric, eye, v, reason))
    df = pd.DataFrame(rows, columns=COLUMNS)
    ts = pd.to_datetime(df["measured_at"], errors="coerce", utc=True)
    df["measured_at"] = ts.dt.tz_convert("Etc/GMT-8").dt.tz_localize(None)   # back to site-local (UTC+8)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df, issues


CM3_MEASURES = {"MTF50_L": ("mtf50", "L", "Cam_ID"), "MTF50_R": ("mtf50", "R", "Cam_ID"),
                "LumUnif_L": ("lum_uniformity", "L", "Cam_ID"), "LumUnif_R": ("lum_uniformity", "R", "Cam_ID"),
                "dUV_L": ("delta_uv", "L", "Clr_ID"), "dUV_R": ("delta_uv", "R", "Clr_ID"),
                "VertMisalign": ("vert_misalign", "B", "Aln_ID")}


def parse_cm3(path: Path, mappings) -> tuple[pd.DataFrame, list[SchemaIssue]]:
    grid = pd.read_excel(path, header=None, dtype=object)
    # Header row is wherever "Station" appears; exports put a banner above it.
    hdr = next(i for i in range(min(10, len(grid))) if "Station" in set(grid.iloc[i].astype(str)))
    raw = grid.iloc[hdr + 1:].reset_index(drop=True)
    raw.columns = [str(c) for c in grid.iloc[hdr]]
    rename, issues = check_schema("cm3_xlsx", list(raw.columns), mappings, ordered=True)
    _require("cm3_xlsx", rename, list(raw.columns), issues)
    raw = raw.rename(columns=rename)
    date = pd.to_datetime(raw["Date"], errors="coerce")
    ts = pd.to_datetime(date.dt.strftime("%Y-%m-%d") + " " + raw["Time"].astype(str), errors="coerce")
    parts = []
    for col, (metric, eye, icol) in CM3_MEASURES.items():
        if col not in raw:
            continue
        parts.append(pd.DataFrame({
            "record_no": np.arange(len(raw)), "measured_at": ts, "station_label": _blank_to_none(raw["Station"]),
            "unit_id": _blank_to_none(raw["SN"]), "instrument_id": _blank_to_none(raw[icol]) if icol in raw else None,
            "operator_id": raw.get("Operator"), "test_type": raw["Type"].map(TEST_TYPES),
            "trial": pd.to_numeric(raw.get("Trial", 1), errors="coerce").fillna(1).astype(int),
            "metric": metric, "eye": eye, "value": pd.to_numeric(raw[col], errors="coerce"), "parse_reason": None,
        }))
    return pd.concat(parts, ignore_index=True)[COLUMNS], issues


LAB_PARAMS = {"MTF50": "mtf50", "LumUniformity": "lum_uniformity", "dUV": "delta_uv", "VertMisalign": "vert_misalign"}
LAB_SIDES = {"Left": "L", "Right": "R", "Both": "B"}


def parse_lab(path: Path, mappings) -> tuple[pd.DataFrame, list[SchemaIssue]]:
    raw = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False)
    rename, issues = check_schema("lab_csv", list(raw.columns), mappings, ordered=True)
    _require("lab_csv", rename, list(raw.columns), issues)
    raw = raw.rename(columns=rename)
    metric = raw["Param"].map(LAB_PARAMS)
    df = pd.DataFrame({
        "record_no": np.arange(len(raw)),
        "measured_at": pd.to_datetime(_blank_to_none(raw["MeasDateTime"]), format="%d/%m/%Y %H:%M:%S", errors="coerce"),
        "station_label": _blank_to_none(raw["Bench"]),
        "unit_id": _blank_to_none(raw["DUT"]),
        "instrument_id": _blank_to_none(raw["Inst"]),
        "operator_id": _blank_to_none(raw["Tech"]),
        "test_type": raw["Purpose"].map(TEST_TYPES),
        "trial": pd.to_numeric(raw["Trial"], errors="coerce").fillna(1).astype(int),
        "metric": metric.fillna(raw["Param"]),
        "eye": raw["Side"].map(LAB_SIDES),
        "value": pd.to_numeric(raw["Reading"], errors="coerce"),
        "parse_reason": np.where(metric.isna(), "unmapped_field", None),
    })
    return df[COLUMNS], issues


PARSERS = {"cm1_csv": parse_cm1, "cm2_jsonl": parse_cm2, "cm3_xlsx": parse_cm3, "lab_csv": parse_lab}
