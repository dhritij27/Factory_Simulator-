"use client";
import { useEffect, useMemo, useState } from "react";
import type { Dashboard } from "@/lib/types";
import { METRIC_LABEL } from "@/lib/types";
import ControlChart from "@/components/ControlChart";
import Heatmap from "@/components/Heatmap";
import GrrChart from "@/components/GrrChart";
import BarList from "@/components/BarList";
import { Verdict } from "@/components/Status";
import { fmt } from "@/components/useWidth";

const METRICS = ["mtf50", "lum_uniformity", "delta_uv", "vert_misalign"];

function addDays(iso: string, d: number) {
  const t = new Date(iso.slice(0, 10) + "T00:00:00Z");
  t.setUTCDate(t.getUTCDate() + d);
  return t.toISOString().slice(0, 10);
}

export default function Page() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [station, setStation] = useState<string>("");
  const [metric, setMetric] = useState<string>("delta_uv");
  const [site, setSite] = useState<string>("CM1");
  const [heatMetric, setHeatMetric] = useState<string>("delta_uv");
  const [grrMetric, setGrrMetric] = useState<string>("mtf50");
  const [showTruth, setShowTruth] = useState(false);
  const [theme, setTheme] = useState<"auto" | "light" | "dark">("auto");

  useEffect(() => {
    fetch("dashboard.json").then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((d: Dashboard) => {
        setData(d);
        const active = d.findings.find((f) => f.status === "active") ?? d.findings[0];
        if (active) { setStation(active.station_id); setMetric(active.metric); }
        else setStation(d.charts[0]?.station_id ?? "");
      })
      .catch((e) => setErr(String(e)));
  }, []);
  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const stations = useMemo(() => Array.from(new Set(data?.charts.map((c) => c.station_id) ?? [])).sort(), [data]);
  const sites = useMemo(() => Array.from(new Set(data?.pairs.map((p) => p.site_id) ?? [])).sort(), [data]);
  if (err) return <main><h1>Optical test health</h1><p className="sub">Couldn't load dashboard.json ({err}). Run <code>python -m fabsim all</code>.</p></main>;
  if (!data) return <main><p className="sub">Loading…</p></main>;

  const chart = data.charts.find((c) => c.station_id === station && c.metric === metric);
  const fault = data.ground_truth.faults.find((f) => f.station_id === station && f.metric === metric && (f.kind === "drift" || f.kind === "step"));
  const active = data.findings.filter((f) => f.status === "active");
  const unacceptable = data.grr.filter((g) => g.verdict === "unacceptable").length;
  const certDue = data.certs.filter((c) => c.status !== "valid");
  const det = data.backtest?.detectors;
  const esc = data.escalation?.find((e) => e.tau === data.action_shift_sigma);
  const planted = (sid: string, m: string) => {
    const p = data.ground_truth.faults.find((g) => g.station_id === sid && g.metric === m);
    if (!p) return "no (false alarm)";
    return p.kind === "drift" || p.kind === "step" ? `yes: ${p.kind}` : `no (${p.kind} fault, not a drift)`;
  };
  const activeReal = active.filter((f) => planted(f.station_id, f.metric).startsWith("yes")).length;

  return (
    <main>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "start" }}>
        <div>
          <h1>Optical test health</h1>
          <p className="sub">Simulated factory · data {data.data_from.slice(0, 10)} to {data.as_of} · {data.totals.stations} stations · all numbers from <code>dashboard.json</code></p>
        </div>
        <div className="filters" role="group" aria-label="Theme">
          {(["auto", "light", "dark"] as const).map((t) => (
            <button key={t} aria-pressed={theme === t} onClick={() => setTheme(t)}>{t}</button>
          ))}
        </div>
      </div>

      <section className="kpis" aria-label="Summary">
        <div className="kpi"><div className="v">{data.totals.measurements.toLocaleString()}</div><div className="l">measurements loaded from {data.totals.files} files</div></div>
        <div className="kpi"><div className="v">{data.totals.quarantined.toLocaleString()}</div><div className="l">rows quarantined ({((100 * data.totals.quarantined) / (data.totals.measurements + data.totals.quarantined)).toFixed(2)}%)</div></div>
        <div className="kpi"><div className="v">{active.filter((f) => f.action_level === "act").length}</div><div className="l">drift findings to act on, {active.filter((f) => f.action_level === "watch").length} more on watch{showTruth && ` (${activeReal} of ${active.length} match a planted fault)`}</div></div>
        <div className="kpi"><div className="v">{unacceptable}</div><div className="l">gauge studies rated unacceptable</div></div>
        <div className="kpi"><div className="v">{certDue.length}</div><div className="l">certificates expired or due in 30 days</div></div>
      </section>

      <section className="card">
        <h2>Drift: golden-unit control chart</h2>
        <p className="sub">Daily mean of (measured − certified reference) over that day's golden units. Golden units don't change, so movement here is the instrument moving.</p>
        <div className="filters">
          <select aria-label="Station" value={station} onChange={(e) => setStation(e.target.value)}>
            {stations.map((s) => <option key={s}>{s}</option>)}
          </select>
          <select aria-label="Metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {METRICS.map((m) => <option key={m} value={m}>{METRIC_LABEL[m]}</option>)}
          </select>
          <label className="chk"><input type="checkbox" checked={showTruth} onChange={(e) => setShowTruth(e.target.checked)} />show planted fault (ground truth)</label>
        </div>
        {chart ? <ControlChart chart={chart} plantedOnset={showTruth && fault ? addDays(data.data_from, fault.onset_day) : null} />
               : <p className="sub">No series for this station and metric.</p>}
        {showTruth && <p className="note">{fault ? `${fault.fault_id}: planted ${fault.kind}.` : "Nothing planted on this series."} {data.ground_truth.note}</p>}
        {chart && (
          <details>
            <summary>Table view</summary>
            <div className="scroll" style={{ maxHeight: 260 }}>
              <table><thead><tr><th>Date</th><th className="num">Residual</th><th className="num">EWMA</th><th className="num">LCL</th><th className="num">UCL</th></tr></thead>
                <tbody>{chart.points.map((p) => <tr key={p.date}><td>{p.date.slice(0, 10)}</td><td className="num">{fmt(p.residual, 4)}</td><td className="num">{fmt(p.ewma, 4)}</td><td className="num">{fmt(p.lcl, 4)}</td><td className="num">{fmt(p.ucl, 4)}</td></tr>)}</tbody></table>
            </div>
          </details>
        )}
      </section>

      <section className="card">
        <h2>Active drift findings</h2>
        <p className="sub">What the calibration agent reads. "Act" means the trailing 7-day shift reached {data.action_shift_sigma} repeatability σ during this alarm, large enough to service; "watch" alarms are real but have stayed too small to ticket. Select a row to open its chart.
          {showTruth && " The last column compares each finding with the simulation's ground truth."}</p>
        <div className="scroll">
          <table>
            <thead><tr><th>Finding</th><th>Station</th><th>Metric</th><th>Instrument</th><th>Detectors</th><th>First alarm</th><th className="num">Recent shift (σ)</th><th className="num">Peak (σ)</th><th>Action</th>{showTruth && <th>Planted?</th>}</tr></thead>
            <tbody>
              {[...active].sort((a, b) => (a.action_level === b.action_level ? a.finding_id.localeCompare(b.finding_id) : a.action_level === "act" ? -1 : 1)).map((f) => (
                <tr key={f.finding_id} style={{ cursor: "pointer" }} onClick={() => { setStation(f.station_id); setMetric(f.metric); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                  <td>{f.finding_id}</td><td>{f.station_id}</td><td>{METRIC_LABEL[f.metric]}</td><td>{f.instrument_id}</td>
                  <td>{f.detectors}</td><td className="nw">{f.first_alarm_date.slice(0, 10)}</td><td className="num">{f.recent_shift_sigma.toFixed(2)}</td><td className="num">{f.peak_shift_sigma.toFixed(2)}</td><td><Verdict v={f.action_level} /></td>
                  {showTruth && <td className="nw">{planted(f.station_id, f.metric)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid2">
        <section className="card">
          <h2>Station-to-station agreement</h2>
          <p className="sub">Golden-unit bias over the 30-day baseline, compared pairwise within a site.</p>
          <div className="filters">
            <select aria-label="Site" value={site} onChange={(e) => setSite(e.target.value)}>{sites.map((s) => <option key={s}>{s}</option>)}</select>
            <select aria-label="Metric" value={heatMetric} onChange={(e) => setHeatMetric(e.target.value)}>
              {METRICS.map((m) => <option key={m} value={m}>{METRIC_LABEL[m]}</option>)}
            </select>
          </div>
          <Heatmap pairs={data.pairs.filter((p) => p.site_id === site && p.metric === heatMetric)} />
          <p className="note">Flagged for bias: {data.correlation.filter((c) => c.flagged).map((c) => `${c.station_id} (${c.metric})`).join(", ") || "none"}.</p>
        </section>

        <section className="card">
          <h2>Gauge R&R by station</h2>
          <p className="sub">ANOVA method, 3 operators × 3 trials on golden units; interval is a parametric bootstrap.</p>
          <div className="filters">
            <select aria-label="Metric" value={grrMetric} onChange={(e) => setGrrMetric(e.target.value)}>
              {METRICS.map((m) => <option key={m} value={m}>{METRIC_LABEL[m]}</option>)}
            </select>
          </div>
          <GrrChart rows={data.grr.filter((g) => g.metric === grrMetric)} />
        </section>
      </div>

      <div className="grid2">
        <section className="card">
          <h2>Instrument certificates due</h2>
          <p className="sub">From the system of record, as of {data.as_of}.</p>
          <div className="scroll" style={{ maxHeight: 340 }}>
            <table>
              <thead><tr><th>Instrument</th><th>Station</th><th>Expires</th><th className="num">Days</th><th>Status</th></tr></thead>
              <tbody>{certDue.map((c) => (
                <tr key={c.instrument_id}><td className="nw">{c.instrument_id}</td><td className="nw">{c.station_id}</td><td className="nw">{c.expires_on}</td>
                  <td className="num">{c.days_until_expiry}</td><td><Verdict v={c.status} /></td></tr>))}
              </tbody>
            </table>
          </div>
          <p className="note">{data.tickets.length} open or draft service tickets.</p>
        </section>

        <section className="card">
          <h2>Ingestion health</h2>
          <p className="sub">Rows quarantined, by reason</p>
          <BarList rows={data.quarantine.map((q) => ({ label: q.reason, value: q.rows }))} total={data.totals.measurements + data.totals.quarantined} />
          <h2 style={{ marginTop: 16 }}>Schema and scale alerts</h2>
          <div className="scroll">
            <table>
              <thead><tr><th>First seen</th><th>Site</th><th>Alert</th><th className="num">Files</th><th>Severity</th></tr></thead>
              <tbody>{data.alerts.map((a) => (
                <tr key={a.alert_id}><td className="nw">{String(a.first_seen_date).slice(0, 10)}</td><td className="nw">{a.site_id}</td>
                  <td>{a.detail}</td><td className="num">{a.n_files}</td><td><Verdict v={a.severity} /></td></tr>))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <div className="grid2">
        <section className="card">
          <h2>Lowest capability (last 30 days)</h2>
          <div className="scroll">
            <table>
              <thead><tr><th>Station</th><th>Metric</th><th>Eye</th><th className="num">Cpk</th><th className="num">95% CI</th><th className="num">n</th></tr></thead>
              <tbody>{data.cpk.slice(0, 10).map((c) => (
                <tr key={c.station_id + c.metric + c.eye}><td>{c.station_id}</td><td>{METRIC_LABEL[c.metric]}</td><td>{c.eye}</td>
                  <td className="num">{c.cpk.toFixed(2)}</td><td className="num">{c.cpk_ci_low.toFixed(2)}–{c.cpk_ci_high.toFixed(2)}</td><td className="num">{c.n}</td></tr>))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="card">
          <h2>How far to trust this</h2>
          <p className="sub">Back-test against the faults the simulator planted (seed run shown).</p>
          {det ? (
            <table>
              <thead><tr><th>Detector</th><th className="num">Recall</th><th className="num">False alarms / station-month</th><th className="num">Median delay</th></tr></thead>
              <tbody>{(["ewma", "cusum", "pelt"] as const).map((k) => det[k] && (
                <tr key={k}><td>{k.toUpperCase()}{k === "pelt" ? " (offline)" : ""}</td><td className="num">{det[k].detected}/{det[k].faults}</td>
                  <td className="num">{det[k].false_alarms_per_station_month.toFixed(2)}</td><td className="num">{det[k].median_delay_days ?? "–"} d</td></tr>))}
                {esc && (
                  <tr><td>Tickets: shift ≥ {data.action_shift_sigma}σ</td><td className="num">{esc.escalated}/{esc.faults}</td>
                    <td className="num">{esc.false_escalations_per_station_month.toFixed(2)}</td><td className="num">{esc.median_delay_days ?? "–"} d</td></tr>
                )}
              </tbody>
            </table>
          ) : <p className="sub">Run the back-test to fill this in.</p>}
          <p className="note">Detector rows count alarms; the last row counts alarms that became tickets.</p>
          {data.backtest && <p className="note">Bias flags: {data.backtest.correlation.true_positive}/{data.backtest.correlation.planted} planted found, {data.backtest.correlation.flagged - data.backtest.correlation.true_positive} false.</p>}
        </section>
      </div>
      <p className="note">Data is simulated. Generated {data.generated_at}.</p>
    </main>
  );
}
