"""Static configuration for the simulated factory.

Everything the simulator needs to know about sites, stations, metrics, specs and
noise lives here so that the "true" values the back-test scores against are in
one place.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# FABSIM_DATA lets a second seed run side by side without overwriting the first.
DATA = Path(os.environ["FABSIM_DATA"]).resolve() if os.environ.get("FABSIM_DATA") else ROOT / "data"
RAW = DATA / "raw"
GROUND_TRUTH = DATA / "ground_truth"
LAKE = DATA / "lake"
WAREHOUSE_DB = DATA / "warehouse" / "fab.duckdb"
SOR_DB = DATA / "sor.db"
RESULTS = ROOT / "results" / DATA.name if os.environ.get("FABSIM_DATA") else ROOT / "results"
SCHEMA_MAPPINGS = ROOT / "config" / "schema_mappings.json"

SIM_START = date(2026, 1, 5)
SIM_DAYS = 182
BASELINE_DAYS = 30          # no faults are planted before day 45; detectors baseline on days 0-29
FAULT_EARLIEST_DAY = 45
FAULT_LATEST_DAY = 150
DRIFT_RAMP_DAYS = 60        # drifts ramp for this long, then level off
# Watch vs. act: an active drift finding becomes actionable (worth a ticket) only once its trailing
# 7-day mean shift reaches this many repeatability sigmas. Chosen on seed 7, confirmed on seed 11
# (results/escalation.md, results/data_seed11/escalation.md).
ACTION_SHIFT_SIGMA = 0.75


@dataclass(frozen=True)
class Metric:
    name: str
    unit: str
    per_eye: bool            # False => one binocular value per test (eye = "B")
    true_mean: float
    true_sd: float           # unit-to-unit (part) variation
    repeat_sd: float         # instrument repeatability sigma (EV)
    operator_sd: float       # operator-to-operator sigma (AV)
    lsl: float | None
    usl: float | None
    plausible: tuple[float, float]   # hard physical range used by ingest validation
    bias_threshold: float    # smallest station bias we consider practically important
    abs_value: bool = False  # sample |N(mean, sd)| (colour error can't be negative)


METRICS: dict[str, Metric] = {
    m.name: m
    for m in [
        # name, unit, per_eye, true_mean, true_sd(part), repeat_sd(EV), operator_sd(AV), lsl, usl, plausible, bias_threshold
        # Healthy stations come out near 12 %GRR; the planted noisy stations near 35 %GRR.
        Metric("mtf50", "cycles/pixel", True, 0.320, 0.018, 0.0019, 0.0009, 0.26, None, (0.05, 0.60), 0.0020),
        Metric("lum_uniformity", "%", True, 85.0, 2.8, 0.30, 0.15, 75.0, None, (30.0, 100.0), 0.30),
        Metric("delta_uv", "unitless", True, 0.0040, 0.0014, 0.00015, 0.00007, None, 0.010, (0.0, 0.05), 0.00015, abs_value=True),
        Metric("vert_misalign", "arcmin", False, 0.0, 1.8, 0.19, 0.10, -6.0, 6.0, (-30.0, 30.0), 0.20),
    ]
}

# Which instrument type measures each metric.
INSTRUMENT_FOR_METRIC = {
    "mtf50": "camera",
    "lum_uniformity": "camera",
    "delta_uv": "colorimeter",
    "vert_misalign": "align_rig",
}
INSTRUMENT_TYPES = ["camera", "colorimeter", "align_rig"]
INSTRUMENT_PREFIX = {"camera": "CAM", "colorimeter": "CLR", "align_rig": "ALN"}


@dataclass(frozen=True)
class Site:
    site_id: str
    kind: str                # "cm" or "lab"
    vendor_format: str       # cm1_csv | cm2_jsonl | cm3_xlsx | lab_csv
    lines: dict[int, int]    # line number -> number of stations
    units_per_day: int       # production units per station per day at scale=1
    operators: int = 3


SITES: list[Site] = [
    Site("CM1", "cm", "cm1_csv", {1: 3, 2: 2}, 40),
    Site("CM2", "cm", "cm2_jsonl", {1: 2, 2: 1, 3: 2}, 40),
    Site("CM3", "cm", "cm3_xlsx", {1: 3, 2: 2}, 40),
    Site("LAB-SV", "lab", "lab_csv", {0: 2}, 6),
    Site("LAB-RD", "lab", "lab_csv", {0: 2}, 6),
]

GOLDEN_UNITS_PER_SITE = 10
MSA_TRIALS = 3
MSA_DAY = 2                  # day index on which each station runs its Gauge R&R study
CERT_SD_FRACTION = 0.25      # golden reference uncertainty, as a fraction of repeat_sd


@dataclass(frozen=True)
class Station:
    station_id: str          # canonical, e.g. CM2-L3-ST02 or LAB-SV-B01
    site_id: str
    line: int
    number: int

    @property
    def is_lab(self) -> bool:
        return self.site_id.startswith("LAB")


def all_stations() -> list[Station]:
    out = []
    for s in SITES:
        for line, n in s.lines.items():
            for k in range(1, n + 1):
                if s.kind == "lab":
                    sid = f"{s.site_id}-B{k:02d}"
                else:
                    sid = f"{s.site_id}-L{line}-ST{k:02d}"
                out.append(Station(sid, s.site_id, line, k))
    return out


def site_by_id(site_id: str) -> Site:
    return next(s for s in SITES if s.site_id == site_id)


@dataclass
class SimConfig:
    seed: int = 7
    scale: float = 1.0       # multiplies production units/day
    days: int = SIM_DAYS
    start: date = SIM_START
    n_drift_faults: int = 12
    n_step_faults: int = 8
    n_bias_faults: int = 4
    n_noisy_stations: int = 2
    missing_instrument_rate: float = 0.005
    missing_timestamp_rate: float = 0.003
    missing_station_rate: float = 0.002
    alias_variant_rate: float = 0.15
    out_dir: Path = field(default_factory=lambda: DATA)
