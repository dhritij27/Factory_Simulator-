"""Write each site's tests the way that site's vendor software would export them.

Four deliberately different formats, plus planted schema events:

  CM1     daily long CSV               adds a column + reorders columns from day 60
  CM2     daily JSON lines (nested)    renames two measurement keys from day 95
  CM3     weekly wide Excel            renames the serial-number column from day 126
  LAB-*   daily semicolon CSV, D/M/Y   LAB-RD silently switches vert_misalign to degrees from day 120
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fabsim.config import INSTRUMENT_FOR_METRIC, SimConfig, Site

SCHEMA_EVENTS = [
    dict(event_id="SE-1", site_id="CM1", from_day=60, kind="additive",
         detail="column fw_version added and column order changed"),
    dict(event_id="SE-2", site_id="CM2", from_day=95, kind="rename",
         detail="measurement keys mtf50 -> MTF_50 and delta_uv -> dUV", renames={"mtf50": "MTF_50", "delta_uv": "dUV"}),
    dict(event_id="SE-3", site_id="CM3", from_day=126, kind="rename",
         detail="column SN -> Serial No.", renames={"SN": "Serial No."}),
    dict(event_id="SE-4", site_id="LAB-RD", from_day=120, kind="unit_change",
         detail="vert_misalign exported in degrees instead of arcmin, header unchanged"),
]

DECIMALS = {"mtf50": 5, "lum_uniformity": 3, "delta_uv": 6, "vert_misalign": 4}
TYPE_CODES = {
    "cm1_csv": {"production": "PROD", "golden": "GOLDEN", "msa": "MSA"},
    "cm2_jsonl": {"production": "prod", "golden": "golden", "msa": "grr"},
    "cm3_xlsx": {"production": "Production", "golden": "Golden", "msa": "GRR"},
    "lab_csv": {"production": "Eng", "golden": "Golden", "msa": "MSA"},
}
LAB_PARAM = {"mtf50": "MTF50", "lum_uniformity": "LumUniformity", "delta_uv": "dUV", "vert_misalign": "VertMisalign"}
LAB_SIDE = {"L": "Left", "R": "Right", "B": "Both"}


def _merged(tests: pd.DataFrame, meas: pd.DataFrame) -> pd.DataFrame:
    df = meas.merge(tests, on="test_uid", how="left")
    for m, dp in DECIMALS.items():
        sel = df["metric"] == m
        df.loc[sel, "value"] = df.loc[sel, "value"].round(dp)
    df["instrument"] = np.select(
        [df["metric"].map(INSTRUMENT_FOR_METRIC) == t for t in ["camera", "colorimeter", "align_rig"]],
        [df["inst_camera"], df["inst_colorimeter"], df["inst_align_rig"]],
    )
    df.loc[df["miss_instrument"], "instrument"] = ""
    df.loc[df["miss_station"], "station_label"] = ""
    return df


def _ts_str(ts: pd.Series, fmt: str, missing: pd.Series) -> pd.Series:
    s = ts.dt.strftime(fmt)
    return s.where(~missing, "")


def write_site(site: Site, tests: pd.DataFrame, meas: pd.DataFrame, raw_dir: Path, cfg: SimConfig) -> pd.DataFrame:
    out = raw_dir / site.site_id
    out.mkdir(parents=True, exist_ok=True)
    fn = {"cm1_csv": _cm1, "cm2_jsonl": _cm2, "cm3_xlsx": _cm3, "lab_csv": _lab}[site.vendor_format]
    return fn(site, tests, meas, out, cfg)


def _cm1(site, tests, meas, out, cfg):
    df = _merged(tests, meas)
    df["timestamp"] = _ts_str(df["ts"], "%Y-%m-%d %H:%M:%S", df["miss_timestamp"])
    df["test_type"] = df["test_type"].map(TYPE_CODES["cm1_csv"])
    df = df.rename(columns={"station_label": "station", "unit_id": "unit_sn", "operator_id": "operator"})
    recs = []
    v1 = ["timestamp", "station", "unit_sn", "instrument", "operator", "test_type", "eye", "metric", "value"]
    v2 = ["station", "timestamp", "unit_sn", "metric", "eye", "value", "instrument", "operator", "test_type", "fw_version"]
    for day, g in df.groupby("day", sort=True):
        date = (pd.Timestamp(cfg.start) + pd.Timedelta(days=int(day))).strftime("%Y-%m-%d")
        path = out / f"cm1_results_{date}.csv"
        g = g.sort_values(["ts", "test_uid", "metric", "eye"])
        if day >= 60:
            g = g.assign(fw_version="4.2.1")
            g[v2].to_csv(path, index=False)
        else:
            g[v1].to_csv(path, index=False)
        recs.append(pd.DataFrame({"source_file": f"{site.site_id}/{path.name}", "record_no": np.arange(len(g)),
                                  "test_uid": g["test_uid"].to_numpy()}))
    return pd.concat(recs, ignore_index=True)


def _cm2(site, tests, meas, out, cfg):
    wide = meas.pivot_table(index="test_uid", columns=["eye", "metric"], values="value", aggfunc="first")
    tests = tests.set_index("test_uid")
    recs = []
    for day, g in tests.groupby("day", sort=True):
        date = (pd.Timestamp(cfg.start) + pd.Timedelta(days=int(day))).strftime("%Y-%m-%d")
        path = out / f"cm2_{date}.jsonl"
        renamed = day >= 95
        k_mtf = "MTF_50" if renamed else "mtf50"
        k_duv = "dUV" if renamed else "delta_uv"
        lines = []
        g = g.sort_values("ts")
        for tid, t in g.iterrows():
            w = wide.loc[tid]
            rec = {
                "ts": None if t.miss_timestamp else t.ts.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                "station_name": None if t.miss_station else t.station_label,
                "serial": t.unit_id,
                "op": t.operator_id,
                "kind": TYPE_CODES["cm2_jsonl"][t.test_type],
                "trial": int(t.trial),
                "instruments": None if t.miss_instrument else {
                    "camera": t.inst_camera, "colorimeter": t.inst_colorimeter, "align": t.inst_align_rig},
                "results": {
                    eye: {k_mtf: round(float(w[(eye, "mtf50")]), 5),
                          "lum_uniformity": round(float(w[(eye, "lum_uniformity")]), 3),
                          k_duv: round(float(w[(eye, "delta_uv")]), 6)}
                    for eye in ("L", "R")
                } | {"binocular": {"vert_misalign": round(float(w[("B", "vert_misalign")]), 4)}},
            }
            lines.append(json.dumps(rec))
        path.write_text("\n".join(lines) + "\n")
        recs.append(pd.DataFrame({"source_file": f"{site.site_id}/{path.name}", "record_no": np.arange(len(g)),
                                  "test_uid": g.index.to_numpy()}))
    return pd.concat(recs, ignore_index=True)


def _cm3(site, tests, meas, out, cfg):
    from openpyxl import Workbook

    wide = meas.pivot_table(index="test_uid", columns=["metric", "eye"], values="value", aggfunc="first")
    cols = {("mtf50", "L"): "MTF50_L", ("mtf50", "R"): "MTF50_R", ("lum_uniformity", "L"): "LumUnif_L",
            ("lum_uniformity", "R"): "LumUnif_R", ("delta_uv", "L"): "dUV_L", ("delta_uv", "R"): "dUV_R",
            ("vert_misalign", "B"): "VertMisalign"}
    tests = tests.assign(week=tests["day"] // 7).set_index("test_uid")
    recs = []
    for week, g in tests.groupby("week", sort=True):
        start_day = int(week) * 7
        date = (pd.Timestamp(cfg.start) + pd.Timedelta(days=start_day)).strftime("%Y-%m-%d")
        path = out / f"CM3_week_{date}.xlsx"
        sn_col = "Serial No." if start_day >= 126 else "SN"
        header = ["Date", "Time", "Station", sn_col, "Type", "Operator", "Trial", "Cam_ID", "Clr_ID", "Aln_ID",
                  *cols.values()]
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Results")
        ws.append([f"CM3 optical test export  |  week of {date}"])     # junk banner row, as real exports have
        ws.append(header)
        g = g.sort_values("ts")
        w = wide.loc[g.index]
        for (tid, t), vals in zip(g.iterrows(), w.itertuples(index=False)):
            v = dict(zip(w.columns, vals))
            ws.append([
                None if t.miss_timestamp else t.ts.date(),
                None if t.miss_timestamp else t.ts.strftime("%H:%M:%S"),
                None if t.miss_station else t.station_label,
                t.unit_id, TYPE_CODES["cm3_xlsx"][t.test_type], t.operator_id, int(t.trial),
                None if t.miss_instrument else t.inst_camera,
                None if t.miss_instrument else t.inst_colorimeter,
                None if t.miss_instrument else t.inst_align_rig,
                *[round(float(v[k]), {"mtf50": 5, "lum_uniformity": 3, "delta_uv": 6, "vert_misalign": 4}[k[0]])
                  for k in cols],
            ])
        wb.save(path)
        recs.append(pd.DataFrame({"source_file": f"{site.site_id}/{path.name}", "record_no": np.arange(len(g)),
                                  "test_uid": g.index.to_numpy()}))
    return pd.concat(recs, ignore_index=True)


def _lab(site, tests, meas, out, cfg):
    df = _merged(tests, meas)
    if site.site_id == "LAB-RD":
        sel = (df["metric"] == "vert_misalign") & (df["day"] >= 120)
        df.loc[sel, "value"] = (df.loc[sel, "value"] / 60.0).round(6)
    df["MeasDateTime"] = _ts_str(df["ts"], "%d/%m/%Y %H:%M:%S", df["miss_timestamp"])
    df["Purpose"] = df["test_type"].map(TYPE_CODES["lab_csv"])
    df["Param"] = df["metric"].map(LAB_PARAM)
    df["Side"] = df["eye"].map(LAB_SIDE)
    df = df.rename(columns={"station_label": "Bench", "unit_id": "DUT", "instrument": "Inst",
                            "operator_id": "Tech", "value": "Reading", "trial": "Trial"})
    cols = ["MeasDateTime", "Bench", "DUT", "Inst", "Tech", "Purpose", "Trial", "Param", "Side", "Reading"]
    prefix = site.site_id.replace("-", "").lower()
    recs = []
    for day, g in df.groupby("day", sort=True):
        date = (pd.Timestamp(cfg.start) + pd.Timedelta(days=int(day))).strftime("%Y-%m-%d")
        path = out / f"{prefix}_bench_{date}.csv"
        g = g.sort_values(["ts", "test_uid", "Param", "Side"])
        g[cols].to_csv(path, index=False, sep=";")
        recs.append(pd.DataFrame({"source_file": f"{site.site_id}/{path.name}", "record_no": np.arange(len(g)),
                                  "test_uid": g["test_uid"].to_numpy()}))
    return pd.concat(recs, ignore_index=True)
