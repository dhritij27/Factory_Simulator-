"""Fault planting. Every fault the simulator injects is described here and logged."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from fabsim.config import (
    DRIFT_RAMP_DAYS,
    FAULT_EARLIEST_DAY,
    FAULT_LATEST_DAY,
    INSTRUMENT_FOR_METRIC,
    METRICS,
    SimConfig,
    Station,
)


@dataclass
class Fault:
    fault_id: str
    kind: str                 # drift | step | bias | noise
    station_id: str
    metric: str
    onset_day: int            # 0 for bias/noise (present from the start)
    magnitude: float          # metric units: total step / bias, or drift rate per day
    magnitude_sigma: float    # in multiples of repeatability sigma; for drifts, the size 30 days after onset
    instrument_swap: bool = False   # step faults only: caused by a replaced instrument
    noise_multiplier: float = 1.0   # noise faults only

    def to_dict(self) -> dict:
        return asdict(self)

    def offset(self, day: np.ndarray) -> np.ndarray:
        """Additive offset this fault contributes on each day index."""
        if self.kind == "bias":
            return np.full(day.shape, self.magnitude, dtype=float)
        if self.kind == "step":
            return np.where(day >= self.onset_day, self.magnitude, 0.0)
        if self.kind == "drift":
            ramp = np.clip(day - self.onset_day, 0, DRIFT_RAMP_DAYS)
            return np.where(day >= self.onset_day, self.magnitude * ramp, 0.0)
        return np.zeros(day.shape)


def _sign(metric: str, rng: np.random.Generator) -> int:
    # Colour error is a distance and cannot go negative, so colorimeter faults only push it up.
    return 1 if METRICS[metric].abs_value else int(rng.choice([-1, 1]))


def plant_faults(cfg: SimConfig, stations: list[Station], rng: np.random.Generator) -> list[Fault]:
    # Every (station, metric) series gets at most one fault so scoring is unambiguous.
    # LAB-RD vert_misalign is excluded: its data is quarantined after the planted unit change,
    # so a fault there would measure the quarantine, not the detector.
    pairs = [
        (s.station_id, m)
        for s in stations
        for m in METRICS
        if not (s.site_id == "LAB-RD" and m == "vert_misalign")
    ]
    order = rng.permutation(len(pairs))
    pairs = [pairs[i] for i in order]
    faults: list[Fault] = []
    k = 0

    def take() -> tuple[str, str]:
        nonlocal k
        p = pairs[k]
        k += 1
        return p

    for i in range(cfg.n_drift_faults):
        sid, m = take()
        sd = METRICS[m].repeat_sd
        total_30d_sigma = rng.uniform(0.6, 3.0)        # size of the drift 30 days after onset
        rate = sd * total_30d_sigma / 30.0 * _sign(m, rng)
        onset = int(rng.integers(FAULT_EARLIEST_DAY, FAULT_LATEST_DAY))
        faults.append(Fault(f"F-DRIFT-{i+1:02d}", "drift", sid, m, onset, rate, rate * 30 / sd))

    for i in range(cfg.n_step_faults):
        sid, m = take()
        sd = METRICS[m].repeat_sd
        mag_sigma = rng.uniform(0.5, 2.5) * _sign(m, rng)
        onset = int(rng.integers(FAULT_EARLIEST_DAY, FAULT_LATEST_DAY))
        faults.append(Fault(f"F-STEP-{i+1:02d}", "step", sid, m, onset, mag_sigma * sd, mag_sigma,
                            instrument_swap=bool(i % 2 == 0)))

    for i in range(cfg.n_bias_faults):
        sid, m = take()
        thr = METRICS[m].bias_threshold
        mag = thr * rng.uniform(1.3, 3.0) * _sign(m, rng)
        faults.append(Fault(f"F-BIAS-{i+1:02d}", "bias", sid, m, 0, mag, mag / METRICS[m].repeat_sd))

    for i in range(cfg.n_noisy_stations):
        sid, m = take()
        faults.append(Fault(f"F-NOISE-{i+1:02d}", "noise", sid, m, 0, 0.0, 0.0, noise_multiplier=3.5))

    return faults


def instrument_type(metric: str) -> str:
    return INSTRUMENT_FOR_METRIC[metric]
