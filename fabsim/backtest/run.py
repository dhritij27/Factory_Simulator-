"""Score every component against the faults the simulator planted.

Nothing here feeds back into the detectors: parameters were fixed before this ran,
and the back-test only reads ground truth and the warehouse's output tables.
Writes results/backtest.json and results/backtest.md.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from fabsim import jsonsafe
from fabsim.analytics import gauge_rr
from fabsim.config import (BASELINE_DAYS, DRIFT_RAMP_DAYS, GROUND_TRUTH, LAKE, METRICS, RESULTS, SIM_START,
                           all_stations)
from fabsim.warehouse.build import connect

MAX_DELAY_DAYS = 45      # an alarm later than this after onset doesn't count as detecting the fault
PELT_TOLERANCE = 7       # a change point within +/- this many days of onset localises it


def _faults() -> pd.DataFrame:
    return pd.DataFrame(json.loads((GROUND_TRUTH / "faults.json").read_text()))


# --------------------------------------------------------------------------------------------- ingestion
def score_ingestion(con) -> dict:
    tests = pd.read_parquet(GROUND_TRUTH / "tests.parquet")
    recs = pd.read_parquet(GROUND_TRUTH / "records.parquet")
    truth = recs.merge(tests[["test_uid", "station_id", "station_label", "miss_instrument", "miss_timestamp",
                              "miss_station", "inst_camera", "inst_colorimeter", "inst_align_rig", "day"]],
                       on="test_uid").rename(columns={"station_id": "true_station"})
    fact = con.execute("""SELECT source_file, record_no, metric, station_id, instrument_id, instrument_imputed
                          FROM fact_measurement""").df()
    m = fact.merge(truth, on=["source_file", "record_no"], how="left")
    assert m["true_station"].notna().all(), "every loaded row must trace back to a simulated record"
    mapped_ok = int((m["station_id"] == m["true_station"]).sum())
    canonical = {s.station_id for s in all_stations()}
    variant_rows = m[~m["station_label"].isin(canonical)]

    true_inst = np.select([m["metric"].isin(["mtf50", "lum_uniformity"]), m["metric"] == "delta_uv"],
                          [m["inst_camera"], m["inst_colorimeter"]], m["inst_align_rig"])
    imp = m["instrument_imputed"]
    q = con.execute("SELECT source_file, record_no, metric, reason FROM quarantine").df()
    qm = q.merge(truth, on=["source_file", "record_no"], how="left")

    # Rows with a planted metadata problem: were they quarantined (timestamp/station) or imputed (instrument)?
    loaded_keys = set(zip(m["source_file"], m["record_no"]))
    miss_ts = truth[truth["miss_timestamp"]]
    miss_st = truth[truth["miss_station"] & ~truth["miss_timestamp"]]
    ts_leaked = sum((r.source_file, r.record_no) in loaded_keys for r in miss_ts.itertuples())
    st_leaked = sum((r.source_file, r.record_no) in loaded_keys for r in miss_st.itertuples())

    events = json.loads((GROUND_TRUTH / "schema_events.json").read_text())
    alerts = con.execute("SELECT site_id, kind, field, severity, first_seen_date FROM ingest_alerts").df()
    ev_rows = []
    for e in events:
        ev_date = pd.Timestamp(SIM_START) + pd.Timedelta(days=e["from_day"])
        a = alerts[(alerts["site_id"] == e["site_id"]) & (alerts["kind"] != "column_order_changed")]
        first = pd.to_datetime(a["first_seen_date"]).min() if len(a) else pd.NaT
        delay = (first.date() - ev_date.date()).days if pd.notna(first) else None
        ev_rows.append(dict(event_id=e["event_id"], site_id=e["site_id"], kind=e["kind"], detail=e["detail"],
                            event_date=str(ev_date.date()), first_alert=str(first.date()) if pd.notna(first) else None,
                            detection_delay_days=delay, detected=delay is not None and delay >= 0))
    # A unit change is only "handled" if the affected rows were kept out of the warehouse.
    uc = m[(m["source_file"].str.startswith("LAB-RD")) & (m["metric"] == "vert_misalign") & (m["day"] >= 120)]
    uc_q = qm[(qm["source_file"].str.startswith("LAB-RD")) & (qm["metric"] == "vert_misalign") & (qm["day"] >= 120)]
    # Quarantined rows that had nothing planted on them (the cost of the safety checks).
    planted = qm["miss_timestamp"] | qm["miss_station"] | ((qm["source_file"].str.startswith("LAB-RD"))
                                                            & (qm["metric"] == "vert_misalign") & (qm["day"] >= 120))
    spurious = qm[~planted]
    return dict(
        rows_loaded=int(len(m)),
        rows_quarantined=int(len(q)),
        station_mapping=dict(
            rows_checked=int(len(m)), correct=mapped_ok, wrong=int(len(m) - mapped_ok),
            accuracy=mapped_ok / len(m),
            variant_label_rows=int(len(variant_rows)),
            variant_label_correct=int((variant_rows["station_id"] == variant_rows["true_station"]).sum()),
            ambiguous_rows_quarantined=int((q["reason"] == "ambiguous_station").sum()),
        ),
        instrument_imputation=dict(
            rows_imputed=int(imp.sum()), correct=int((m.loc[imp, "instrument_id"] == true_inst[imp.to_numpy()]).sum()),
        ),
        missing_metadata=dict(
            missing_timestamp_rows=int(len(miss_ts)), missing_timestamp_leaked=int(ts_leaked),
            missing_station_rows=int(len(miss_st)), missing_station_leaked=int(st_leaked),
        ),
        schema_events=ev_rows,
        unit_change=dict(rows_affected=int(len(uc) + len(uc_q)), rows_quarantined=int(len(uc_q)),
                         rows_leaked_into_warehouse=int(len(uc))),
        spurious_quarantine=dict(rows=int(len(spurious)),
                                 by_reason=spurious["reason"].value_counts().to_dict(),
                                 fraction_of_clean_rows=len(spurious) / (len(m) + len(spurious))),
    )


# --------------------------------------------------------------------------------------------- detectors
def score_detectors(con, variant: str) -> dict:
    faults = _faults()
    moving = faults[faults["kind"].isin(["drift", "step"])].copy()
    eps = con.execute("SELECT station_id, metric, detector, start_day, end_day FROM drift_episodes WHERE variant = ?",
                      [variant]).df()
    cps = con.execute("SELECT station_id, metric, day FROM changepoints WHERE variant = ?", [variant]).df()
    series = con.execute("SELECT DISTINCT station_id, metric FROM drift_series WHERE variant = ?", [variant]).df()
    n_days = int(con.execute("SELECT n_days FROM analysis_runs").fetchone()[0])
    monitored_days = n_days - BASELINE_DAYS
    n_series = len(series)
    n_stations = series["station_id"].nunique()
    station_months = n_stations * monitored_days / 30.44
    fmap = {(f.station_id, f.metric): f for f in moving.itertuples()}

    out = {}
    per_fault_rows = []
    for det in ["ewma", "cusum", "pelt"]:
        tp_alarms = fa = 0
        detected = {}
        if det == "pelt":
            items = [(r.station_id, r.metric, int(r.day)) for r in cps.itertuples() if r.day >= BASELINE_DAYS]
        else:
            items = [(r.station_id, r.metric, int(r.start_day)) for r in eps[eps.detector == det].itertuples()]
        for sid, metric, day in items:
            f = fmap.get((sid, metric))
            if f is None:
                fa += 1
                continue
            if det == "pelt":
                end = f.onset_day + (DRIFT_RAMP_DAYS if f.kind == "drift" else 0) + PELT_TOLERANCE
                ok = f.onset_day - PELT_TOLERANCE <= day <= end
            else:
                ok = day >= f.onset_day
            if not ok:
                fa += 1
                continue
            tp_alarms += 1
            lag = day - f.onset_day
            lo = -PELT_TOLERANCE if det == "pelt" else 0
            if lo <= lag <= MAX_DELAY_DAYS:
                detected[f.fault_id] = min(detected.get(f.fault_id, 10 ** 6), lag, key=abs) if det == "pelt" \
                    else min(detected.get(f.fault_id, 10 ** 6), lag)
        delays = list(detected.values())
        n_alarms = tp_alarms + fa
        out[det] = dict(
            faults=int(len(moving)), detected=len(detected), recall=len(detected) / len(moving),
            alarms=n_alarms, true_alarms=tp_alarms, false_alarms=fa,
            precision=tp_alarms / n_alarms if n_alarms else None,
            false_alarms_per_station_month=fa / station_months,
            median_delay_days=float(np.median(delays)) if delays else None,
            delay_note="signed localisation error (offline, uses future data)" if det == "pelt" else "days after onset",
        )
        for f in moving.itertuples():
            per_fault_rows.append(dict(detector=det, fault_id=f.fault_id, kind=f.kind, station_id=f.station_id,
                                       metric=f.metric, onset_day=f.onset_day,
                                       size_sigma=abs(f.magnitude_sigma), detected=f.fault_id in detected,
                                       delay_days=detected.get(f.fault_id)))
    pf = pd.DataFrame(per_fault_rows)
    # Union of the two online detectors: what the agent actually acts on.
    on = pf[pf.detector.isin(["ewma", "cusum"])]
    union = on.groupby("fault_id").agg(detected=("detected", "any"),
                                       delay=("delay_days", lambda s: s.dropna().min() if s.notna().any() else None))
    out["ewma_or_cusum"] = dict(faults=int(len(moving)), detected=int(union["detected"].sum()),
                                recall=float(union["detected"].mean()),
                                median_delay_days=float(union["delay"].dropna().median()) if union["detected"].any() else None)
    # Recall by fault size
    pf["size_bin"] = pd.cut(pf["size_sigma"], [0, 1.0, 2.0, 10], labels=["<1 sigma", "1-2 sigma", ">2 sigma"])
    by_size = (pf.groupby(["detector", "size_bin"], observed=True)["detected"].agg(["sum", "count"]).reset_index())
    out["recall_by_size"] = [dict(detector=r.detector, size=str(r.size_bin), detected=int(r["sum"]), faults=int(r["count"]))
                             for _, r in by_size.iterrows()]
    out["exposure"] = dict(series=n_series, stations=n_stations, monitored_days=monitored_days,
                           station_months=round(station_months, 1))
    out["per_fault"] = pf.drop(columns=["size_bin"]).to_dict(orient="records")
    return out


# --------------------------------------------------------------------------------------------- correlation + GRR
def score_correlation(con) -> dict:
    faults = _faults()
    planted = {(f.station_id, f.metric) for f in faults[faults.kind == "bias"].itertuples()}
    corr = con.execute("SELECT station_id, metric, bias, flagged FROM correlation_results").df()
    flagged = {(r.station_id, r.metric) for r in corr[corr.flagged].itertuples()}
    tp = len(planted & flagged)
    return dict(planted=len(planted), flagged=len(flagged), true_positive=tp,
                recall=tp / len(planted) if planted else None, precision=tp / len(flagged) if flagged else None,
                series_checked=int(len(corr)))


def _configured_pct_grr(metric: str, mult: float) -> float:
    s = METRICS[metric]
    return float(gauge_rr.pct_grr_from_components((s.repeat_sd * mult) ** 2, s.operator_sd ** 2, 0.0, s.true_sd ** 2))


def score_grr(con, coverage_studies: int = 300, monte_carlo: bool = True) -> dict:
    faults = _faults()
    noisy = {(f.station_id, f.metric): f.noise_multiplier for f in faults[faults.kind == "noise"].itertuples()}
    g = con.execute("SELECT station_id, metric, pct_grr, pct_grr_ci_low, pct_grr_ci_high, verdict, n_parts FROM grr_results").df()
    g["configured"] = [_configured_pct_grr(r.metric, noisy.get((r.station_id, r.metric), 1.0)) for r in g.itertuples()]
    g["covered"] = (g["pct_grr_ci_low"] <= g["configured"]) & (g["configured"] <= g["pct_grr_ci_high"])
    g["planted_noisy"] = [(r.station_id, r.metric) in noisy for r in g.itertuples()]
    unacc = set(zip(g.loc[g.verdict == "unacceptable", "station_id"], g.loc[g.verdict == "unacceptable", "metric"]))
    # Monte Carlo: does the bootstrap CI reach its nominal 95% on fresh studies from known components?
    cov = []
    for metric in (METRICS if monte_carlo else []):
        s = METRICS[metric]
        p = 20 if s.per_eye else 10
        for label, mult in [("healthy", 1.0), ("noisy", 3.5)]:
            r = gauge_rr.coverage_study((s.repeat_sd * mult) ** 2, s.operator_sd ** 2, s.true_sd ** 2, p=p,
                                        n_studies=coverage_studies, n_boot=600, seed=hash((metric, label)) % 2 ** 32)
            cov.append(dict(metric=metric, station=label, parts=p, **r))
    return dict(
        studies=int(len(g)),
        planted_noisy=len(noisy),
        noisy_flagged_unacceptable=len(set(noisy) & unacc),
        healthy_flagged_unacceptable=len(unacc - set(noisy)),
        warehouse_ci_contains_configured=float(g["covered"].mean()),
        median_abs_error_pct_points=float((g["pct_grr"] - g["configured"]).abs().median()),
        coverage_monte_carlo=cov,
    )


# --------------------------------------------------------------------------------------------- report
def _md(r: dict) -> str:
    ing, det, cor, grr = r["ingestion"], r["detectors"], r["correlation"], r["gauge_rr"]
    sm = ing["station_mapping"]
    L = [f"# Back-test results", "",
         f"Generated {r['generated_at']} from simulator seed {r['seed']}. Every number below is computed by "
         f"`python -m fabsim backtest` against `data/ground_truth/`.", "",
         "## Ingestion", "",
         f"| Check | Result |", "|---|---|",
         f"| Rows loaded / quarantined | {ing['rows_loaded']:,} / {ing['rows_quarantined']:,} |",
         f"| Station mapping accuracy (loaded rows) | {sm['correct']:,} / {sm['rows_checked']:,} ({100*sm['accuracy']:.3f}%), {sm['wrong']} wrong |",
         f"| Rows with a non-canonical label mapped correctly | {sm['variant_label_correct']:,} / {sm['variant_label_rows']:,} |",
         f"| Ambiguous labels quarantined instead of guessed | {sm['ambiguous_rows_quarantined']:,} rows |",
         f"| Missing instrument imputed correctly | {ing['instrument_imputation']['correct']:,} / {ing['instrument_imputation']['rows_imputed']:,} |",
         f"| Missing-timestamp rows that leaked into the warehouse | {ing['missing_metadata']['missing_timestamp_leaked']} / {ing['missing_metadata']['missing_timestamp_rows']:,} |",
         f"| Missing-station rows that leaked into the warehouse | {ing['missing_metadata']['missing_station_leaked']} / {ing['missing_metadata']['missing_station_rows']:,} |",
         f"| Silent unit change: rows kept out of the warehouse | {ing['unit_change']['rows_quarantined']:,} / {ing['unit_change']['rows_affected']:,} |",
         f"| Clean rows quarantined anyway | {ing['spurious_quarantine']['rows']:,} ({100*ing['spurious_quarantine']['fraction_of_clean_rows']:.3f}%): {ing['spurious_quarantine']['by_reason']} |",
         "", "| Schema event | Planted | First alert | Delay (days) |", "|---|---|---|---|"]
    for e in ing["schema_events"]:
        L.append(f"| {e['site_id']}: {e['detail']} | {e['event_date']} | {e['first_alert']} | {e['detection_delay_days']} |")
    any_det = next(iter(det.values()))
    L += ["", "## Drift detectors", "",
          f"{any_det['ewma']['faults']} planted drift/step faults across {any_det['exposure']['series']} station x metric series "
          f"({any_det['exposure']['station_months']} station-months monitored after the {BASELINE_DAYS}-day baseline). "
          f"A fault counts as detected if an alarm lands within {MAX_DELAY_DAYS} days of onset. "
          "`raw` = daily mean golden residual; `operator_adjusted` = same, after subtracting each operator's "
          "baseline effect (pooled across the site).", ""]
    from fabsim.analytics.drift import CUSUM_H, CUSUM_K, EWMA_L, EWMA_LAMBDA
    names = {"ewma": f"EWMA (λ={EWMA_LAMBDA}, L={EWMA_L})", "cusum": f"CUSUM (k={CUSUM_K}σ, h={CUSUM_H:g}σ)",
             "pelt": "PELT change-point (offline)"}
    L += ["| Series | Detector | Recall | Precision | False alarms / station-month | Median delay (days) |",
          "|---|---|---|---|---|---|"]
    for variant, dv in det.items():
        for d in ["ewma", "cusum", "pelt"]:
            x = dv[d]
            delay = f"{x['median_delay_days']:.0f}" if x["median_delay_days"] is not None else "–"
            if d == "pelt":
                delay += " (localisation error)"
            prec = f"{100*x['precision']:.0f}%" if x["precision"] is not None else "–"
            L.append(f"| {variant} | {names[d]} | {x['detected']}/{x['faults']} ({100*x['recall']:.0f}%) | "
                     f"{prec} | {x['false_alarms_per_station_month']:.2f} | {delay} |")
        u = dv["ewma_or_cusum"]
        ud = f"{u['median_delay_days']:.0f}" if u["median_delay_days"] is not None else "–"
        L.append(f"| {variant} | EWMA or CUSUM | {u['detected']}/{u['faults']} ({100*u['recall']:.0f}%) | – | – | {ud} |")
    L += ["", "Recall by fault size (size = step height, or drift height 30 days after onset, in repeatability σ):", "",
          "| Series | Detector | <1σ | 1–2σ | >2σ |", "|---|---|---|---|---|"]
    for variant, dv in det.items():
        rs = pd.DataFrame(dv["recall_by_size"])
        for d in ["ewma", "cusum", "pelt"]:
            cells = []
            for bn in ["<1 sigma", "1-2 sigma", ">2 sigma"]:
                row = rs[(rs.detector == d) & (rs["size"] == bn)]
                cells.append(f"{int(row.detected.iloc[0])}/{int(row.faults.iloc[0])}" if len(row) else "–")
            L.append(f"| {variant} | {d} | " + " | ".join(cells) + " |")
    L += ["", "## Station correlation (golden units)", "",
          f"Planted biased series: {cor['planted']}. Flagged: {cor['flagged']}. "
          f"Recall {cor['true_positive']}/{cor['planted']}, precision {cor['true_positive']}/{cor['flagged']}, "
          f"out of {cor['series_checked']} station x metric series checked.", "",
          "## Gauge R&R", "",
          f"{grr['studies']} studies. Planted noisy stations rated unacceptable: {grr['noisy_flagged_unacceptable']}/{grr['planted_noisy']}. "
          f"Healthy stations rated unacceptable: {grr['healthy_flagged_unacceptable']}. "
          f"Median |estimate − configured| = {grr['median_abs_error_pct_points']:.1f} %GRR points; "
          f"the 95% CI contains the configured value in {100*grr['warehouse_ci_contains_configured']:.0f}% of studies.", "",
          "Bootstrap CI coverage, Monte Carlo over fresh simulated studies (3 operators × 3 trials):", "",
          "| Metric | Station | Parts | True %GRR | Median estimate | Coverage (nominal 95%) | Median CI width |",
          "|---|---|---|---|---|---|---|"]
    for c in grr["coverage_monte_carlo"]:
        L.append(f"| {c['metric']} | {c['station']} | {c['parts']} | {c['true_pct_grr']:.1f} | {c['median_estimate']:.1f} | "
                 f"{100*c['coverage']:.0f}% (n={c['n_studies']}) | {c['median_ci_width']:.1f} |")
    return "\n".join(L) + "\n"


def run_backtest(verbose: bool = True, monte_carlo: bool = True) -> dict:
    con = connect(read_only=True)
    meta = json.loads((GROUND_TRUTH / "sim_meta.json").read_text())
    r = dict(generated_at=str(date.today()), seed=meta["seed"], scale=meta["scale"],
             ingestion=score_ingestion(con),
             detectors={v: score_detectors(con, v) for v in ("raw", "operator_adjusted")},
             correlation=score_correlation(con), gauge_rr=score_grr(con, monte_carlo=monte_carlo))
    con.close()
    RESULTS.mkdir(exist_ok=True)
    md = _md(r)
    for stem in ("backtest", f"backtest_seed{r['seed']}"):
        (RESULTS / f"{stem}.json").write_text(jsonsafe.dumps(r, indent=2))
        (RESULTS / f"{stem}.md").write_text(md)
    if verbose:
        print(md)
    return r
