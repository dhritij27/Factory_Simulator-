"""Generate the simulated factory: tests, measurements, planted faults and ground truth.

Measurement model, for unit u on station s with operator o on day d:

    y = true(u, metric, eye) + station_bias(s) + operator_bias(o) + fault_offset(s, d)
        + noise * noise_multiplier(s)

All the terms except ``true`` and ``noise`` are logged to data/ground_truth so the
back-test can check what each detector should have found.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from fabsim.config import (
    CERT_SD_FRACTION,
    GOLDEN_UNITS_PER_SITE,
    INSTRUMENT_FOR_METRIC,
    INSTRUMENT_PREFIX,
    INSTRUMENT_TYPES,
    METRICS,
    MSA_DAY,
    MSA_TRIALS,
    SITES,
    SimConfig,
    all_stations,
)
from fabsim.sim import export
from fabsim.sim.aliases import primary_alias, variant_aliases
from fabsim.sim.faults import Fault, plant_faults
from fabsim.sim import sor

MEAS_KEYS = [(m, e) for m, spec in METRICS.items() for e in (["L", "R"] if spec.per_eye else ["B"])]


def _draw_true(rng: np.random.Generator, metric: str, n: int) -> np.ndarray:
    spec = METRICS[metric]
    if spec.abs_value:   # strictly positive quantity (colour error): gamma with the configured mean / sd
        k = (spec.true_mean / spec.true_sd) ** 2
        return rng.gamma(k, spec.true_sd ** 2 / spec.true_mean, n)
    return rng.normal(spec.true_mean, spec.true_sd, n)


def simulate(cfg: SimConfig | None = None, write: bool = True, verbose: bool = True) -> dict:
    cfg = cfg or SimConfig()
    rng = np.random.default_rng(cfg.seed)
    stations = all_stations()
    st_by_id = {s.station_id: s for s in stations}
    faults = plant_faults(cfg, stations, rng)

    # ---- instruments (with swaps caused by some step faults) -------------------------------
    inst_rows = []
    serial = 100
    current: dict[tuple[str, str], str] = {}
    for s in stations:
        for t in INSTRUMENT_TYPES:
            serial += 1
            iid = f"{INSTRUMENT_PREFIX[t]}-{s.site_id}-{serial:04d}"
            current[(s.station_id, t)] = iid
            inst_rows.append(dict(instrument_id=iid, instrument_type=t, station_id=s.station_id,
                                  valid_from_day=0, valid_to_day=None))
    swaps: dict[tuple[str, str], tuple[int, str]] = {}
    for f in faults:
        if f.kind == "step" and f.instrument_swap:
            t = INSTRUMENT_FOR_METRIC[f.metric]
            serial += 1
            new_id = f"{INSTRUMENT_PREFIX[t]}-{st_by_id[f.station_id].site_id}-{serial:04d}"
            old = next(r for r in inst_rows if r["instrument_id"] == current[(f.station_id, t)])
            old["valid_to_day"] = f.onset_day - 1
            inst_rows.append(dict(instrument_id=new_id, instrument_type=t, station_id=f.station_id,
                                  valid_from_day=f.onset_day, valid_to_day=None))
            swaps[(f.station_id, t)] = (f.onset_day, new_id)
    initial_inst = {(r["station_id"], r["instrument_type"]): r["instrument_id"]
                    for r in inst_rows if r["valid_from_day"] == 0}

    # ---- station / operator effects ---------------------------------------------------------
    station_bias = {(s.station_id, m): rng.normal(0, 0.15 * METRICS[m].bias_threshold)
                    for s in stations for m in METRICS}
    noise_mult = {(s.station_id, m): 1.0 for s in stations for m in METRICS}
    for f in faults:
        if f.kind == "noise":
            noise_mult[(f.station_id, f.metric)] = f.noise_multiplier
    operators = {site.site_id: [f"OP-{site.site_id}-{k+1:02d}" for k in range(site.operators)] for site in SITES}
    operator_bias = {(op, m): rng.normal(0, METRICS[m].operator_sd)
                     for ops in operators.values() for op in ops for m in METRICS}

    # ---- golden units -----------------------------------------------------------------------
    golden_true: dict[tuple[str, str, str], float] = {}
    golden_ref_rows = []
    golden_ids = {}
    for site in SITES:
        ids = [f"GU-{site.site_id}-{k+1:02d}" for k in range(GOLDEN_UNITS_PER_SITE)]
        golden_ids[site.site_id] = ids
        for m, e in MEAS_KEYS:
            vals = _draw_true(rng, m, len(ids))
            for gid, v in zip(ids, vals):
                golden_true[(gid, m, e)] = float(v)
                ref = v + rng.normal(0, CERT_SD_FRACTION * METRICS[m].repeat_sd)
                golden_ref_rows.append(dict(unit_id=gid, metric=m, eye=e, reference_value=float(ref),
                                            certified_by="LAB-SV", cert_uncertainty_1s=CERT_SD_FRACTION * METRICS[m].repeat_sd))

    faults_by_series: dict[tuple[str, str], list[Fault]] = {}
    for f in faults:
        faults_by_series.setdefault((f.station_id, f.metric), []).append(f)

    schema_events = export.SCHEMA_EVENTS
    all_tests, all_records = [], []
    unit_seq = 0
    total_rows = 0
    raw_dir = cfg.out_dir / "raw"
    for site in SITES:
        site_stations = [s for s in stations if s.site_id == site.site_id]
        # ---------- build test table ----------
        rows = []
        n_prod = max(1, int(round(site.units_per_day * cfg.scale)))
        for s in site_stations:
            for d in range(cfg.days):
                k = int(rng.poisson(n_prod))
                for _ in range(k):
                    unit_seq += 1
                    uid = (f"HS{unit_seq:08d}" if site.kind == "cm" else f"ES{unit_seq:07d}")
                    rows.append((s.station_id, d, uid, "production", rng.choice(operators[site.site_id]), 1))
                op = rng.choice(operators[site.site_id])
                for gid in golden_ids[site.site_id]:
                    rows.append((s.station_id, d, gid, "golden", op, 1))
                if d == MSA_DAY:
                    for op in operators[site.site_id]:
                        for trial in range(1, MSA_TRIALS + 1):
                            for gid in rng.permutation(golden_ids[site.site_id]):
                                rows.append((s.station_id, d, gid, "msa", op, trial))
        tests = pd.DataFrame(rows, columns=["station_id", "day", "unit_id", "test_type", "operator_id", "trial"])
        n = len(tests)
        secs = rng.uniform(6 * 3600, 22 * 3600, n)
        base = pd.Timestamp(cfg.start)
        tests["ts"] = base + pd.to_timedelta(tests["day"], unit="D") + pd.to_timedelta(secs.round(), unit="s")
        tests = tests.sort_values(["day", "ts"]).reset_index(drop=True)
        tests["site_id"] = site.site_id
        tests["test_uid"] = [f"T-{site.site_id}-{i:08d}" for i in range(n)]
        for t in INSTRUMENT_TYPES:
            col = tests["station_id"].map(lambda sid, t=t: initial_inst[(sid, t)])
            for (sid, tt), (onset, new_id) in swaps.items():
                if tt != t:
                    continue
                mask = (tests["station_id"] == sid) & (tests["day"] >= onset)
                col = col.where(~mask, new_id)
            tests[f"inst_{t}"] = col.values
        # aliases and missing metadata
        prim = {s.station_id: primary_alias(s, site.vendor_format) for s in site_stations}
        var = {s.station_id: [a for a in variant_aliases(s) if a != prim[s.station_id]] for s in site_stations}
        use_variant = rng.random(n) < cfg.alias_variant_rate
        pick = rng.integers(0, 10_000, n)
        sids = tests["station_id"].to_numpy()
        tests["station_label"] = [
            var[sid][p % len(var[sid])] if uv else prim[sid] for sid, uv, p in zip(sids, use_variant, pick)
        ]
        tests["miss_instrument"] = rng.random(n) < cfg.missing_instrument_rate
        tests["miss_timestamp"] = rng.random(n) < cfg.missing_timestamp_rate
        tests["miss_station"] = rng.random(n) < cfg.missing_station_rate

        # ---------- expand to measurements ----------
        meas = []
        for m, e in MEAS_KEYS:
            df = tests[["test_uid", "station_id", "day", "unit_id", "test_type", "operator_id"]].copy()
            df["metric"], df["eye"] = m, e
            is_g = df["test_type"] != "production"
            true = np.empty(n)
            true[~is_g.to_numpy()] = _draw_true(rng, m, int((~is_g).sum()))
            true[is_g.to_numpy()] = [golden_true[(u, m, e)] for u in df.loc[is_g, "unit_id"]]
            sb = df["station_id"].map(lambda sid: station_bias[(sid, m)]).to_numpy()
            ob = df["operator_id"].map(lambda op: operator_bias[(op, m)]).to_numpy()
            nm = df["station_id"].map(lambda sid: noise_mult[(sid, m)]).to_numpy()
            off = np.zeros(n)
            day = df["day"].to_numpy()
            for (sid, mm), fl in faults_by_series.items():
                if mm != m:
                    continue
                mask = sids == sid
                for f in fl:
                    off[mask] += f.offset(day[mask])
            noise = rng.normal(0, METRICS[m].repeat_sd, n) * nm
            df["value"] = true + sb + ob + off + noise
            meas.append(df[["test_uid", "metric", "eye", "value"]])
        meas = pd.concat(meas, ignore_index=True)
        total_rows += len(meas)

        if write:
            recs = export.write_site(site, tests, meas, raw_dir, cfg)
            all_records.append(recs)
        all_tests.append(tests)
        if verbose:
            print(f"  {site.site_id}: {n:,} tests, {len(meas):,} measurement rows")

    tests_all = pd.concat(all_tests, ignore_index=True)
    out = dict(cfg=cfg, stations=stations, faults=faults, instruments=inst_rows, tests=tests_all,
               golden_true=golden_true, golden_ref=pd.DataFrame(golden_ref_rows),
               station_bias=station_bias, operator_bias=operator_bias, noise_mult=noise_mult,
               operators=operators, total_rows=total_rows)

    if write:
        gt = cfg.out_dir / "ground_truth"
        gt.mkdir(parents=True, exist_ok=True)
        (gt / "faults.json").write_text(json.dumps([f.to_dict() for f in faults], indent=2))
        (gt / "schema_events.json").write_text(json.dumps(schema_events, indent=2))
        (gt / "stations.json").write_text(json.dumps([
            dict(station_id=s.station_id, site_id=s.site_id, line=s.line, number=s.number,
                 primary_alias=primary_alias(s, next(x for x in SITES if x.site_id == s.site_id).vendor_format),
                 variants=variant_aliases(s)) for s in stations], indent=2))
        pd.DataFrame(inst_rows).to_json(gt / "instruments.json", orient="records", indent=2)
        tests_all.to_parquet(gt / "tests.parquet", index=False)
        pd.concat(all_records, ignore_index=True).to_parquet(gt / "records.parquet", index=False)
        truth_rows = [dict(unit_id=u, metric=m, eye=e, true_value=v) for (u, m, e), v in golden_true.items()]
        pd.DataFrame(truth_rows).to_csv(gt / "golden_true.csv", index=False)
        effects = dict(
            station_bias={f"{k[0]}|{k[1]}": v for k, v in station_bias.items()},
            operator_bias={f"{k[0]}|{k[1]}": v for k, v in operator_bias.items()},
            noise_multiplier={f"{k[0]}|{k[1]}": v for k, v in noise_mult.items() if v != 1.0},
        )
        (gt / "effects.json").write_text(json.dumps(effects, indent=2))
        meta = dict(seed=cfg.seed, scale=cfg.scale, days=cfg.days, start=str(cfg.start),
                    total_measurement_rows=total_rows, n_tests=len(tests_all),
                    generated_at=datetime.now().isoformat(timespec="seconds"))
        (gt / "sim_meta.json").write_text(json.dumps(meta, indent=2))
        # golden reference certificates are a real input to the pipeline, not ground truth
        cert_dir = raw_dir / "LAB-SV"
        cert_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(golden_ref_rows).to_csv(cert_dir / "golden_reference_certificates.csv", index=False)
        sor.build_sor(cfg, stations, inst_rows, faults, rng, cfg.out_dir / "sor.db")
    return out
