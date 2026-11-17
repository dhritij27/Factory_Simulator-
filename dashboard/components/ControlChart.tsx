"use client";
import { useMemo, useState } from "react";
import type { Chart } from "@/lib/types";
import { fmt, niceTicks, useWidth } from "./useWidth";

const H = 260;
const M = { t: 12, r: 16, b: 28, l: 64 };

export default function ControlChart({ chart, plantedOnset }: { chart: Chart; plantedOnset?: string | null }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const pts = chart.points;
  const iw = width - M.l - M.r;
  const ih = H - M.t - M.b;

  const { y0, y1 } = useMemo(() => {
    const vals = pts.flatMap((p) => [p.residual, p.ewma, p.lcl, p.ucl]).filter((v): v is number => v !== null && Number.isFinite(v));
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.06 || 1e-6;
    return { y0: lo - pad, y1: hi + pad };
  }, [pts]);

  const x = (i: number) => M.l + (i / Math.max(1, pts.length - 1)) * iw;
  const y = (v: number) => M.t + (1 - (v - y0) / (y1 - y0)) * ih;
  const idx = (d: string) => pts.findIndex((p) => p.date.slice(0, 10) === d.slice(0, 10));
  const path = (k: "ewma" | "lcl" | "ucl") =>
    pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`).join("");
  const ticks = niceTicks(y0, y1, 4);
  const months = pts.map((p, i) => [p.date.slice(0, 10), i] as const).filter(([d]) => d.endsWith("-01"));
  const onsetI = plantedOnset ? idx(plantedOnset) : -1;
  // EWMA and CUSUM episodes overlap; shade their union once so overlaps don't stack darker.
  const bands = useMemo(() => {
    const iv = chart.episodes.map((e) => [idx(e.start_date), idx(e.end_date)] as [number, number])
      .filter(([a, b]) => a >= 0 && b >= 0).sort((p, q) => p[0] - q[0]);
    const out: [number, number][] = [];
    for (const [a, b] of iv) {
      const last = out[out.length - 1];
      if (last && a <= last[1] + 1) last[1] = Math.max(last[1], b);
      else out.push([a, b]);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chart]);

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1));
    setHover(Math.max(0, Math.min(pts.length - 1, i)));
  }
  const hp = hover !== null ? pts[hover] : null;

  return (
    <div ref={ref} className="chartwrap">
      <svg width={width} height={H} role="img"
           aria-label={`Control chart for ${chart.station_id} ${chart.metric}: daily golden-unit residual with EWMA and control limits`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={M.l - 8} y={y(t) + 4} textAnchor="end">{fmt(t, 2)}</text>
          </g>
        ))}
        {months.map(([d, i]) => (
          <text key={d} x={x(i)} y={H - 8} textAnchor="middle">
            {new Date(d + "T00:00").toLocaleString("en", { month: "short" })}
          </text>
        ))}
        {bands.map(([a, b], k) => (
          <rect key={k} x={x(a) - 2} width={Math.max(4, x(b) - x(a) + 4)} y={M.t} height={ih} fill="var(--band)" />
        ))}
        <path d={path("ucl")} fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeDasharray="5 4" />
        <path d={path("lcl")} fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeDasharray="5 4" />
        {pts.map((p, i) => p.residual === null ? null : (
          <circle key={i} cx={x(i)} cy={y(p.residual)} r={2} fill="var(--ink-2)" opacity={0.55} />
        ))}
        <path d={path("ewma")} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" />
        {onsetI >= 0 && (
          <g>
            <line x1={x(onsetI)} x2={x(onsetI)} y1={M.t} y2={M.t + ih} stroke="var(--series-2)" strokeWidth={2} />
            <text x={x(onsetI) + 4} y={M.t + 12} style={{ fill: "var(--ink-2)" }}>planted fault onset</text>
          </g>
        )}
        {hp && hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={M.t + ih} stroke="var(--axis)" strokeWidth={1} />
            <circle cx={x(hover)} cy={y(hp.ewma)} r={4} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
          </g>
        )}
        <line x1={M.l} x2={width - M.r} y1={M.t + ih} y2={M.t + ih} stroke="var(--axis)" />
        <rect x={M.l} y={M.t} width={iw} height={ih} fill="transparent"
              onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
      {hp && hover !== null && (
        <div className="tip" style={{ left: Math.min(x(hover) + 12, width - 190), top: 8 }}>
          <div style={{ color: "var(--ink-2)", marginBottom: 4 }}>{hp.date.slice(0, 10)}</div>
          <div className="row"><span className="key-line" style={{ background: "var(--series-1)" }} /><b>{fmt(hp.ewma, 3)}</b> EWMA</div>
          <div className="row"><span className="key-dot" style={{ background: "var(--ink-2)" }} /><b>{fmt(hp.residual, 3)}</b> daily residual</div>
          <div className="row"><span className="key-dash" /><b>{fmt(hp.lcl, 3)} to {fmt(hp.ucl, 3)}</b> limits</div>
        </div>
      )}
      <div className="legend">
        <span><span className="key-line" style={{ background: "var(--series-1)" }} />EWMA</span>
        <span><span className="key-dot" style={{ background: "var(--ink-2)", opacity: 0.6 }} />Daily golden residual ({chart.unit})</span>
        <span><span className="key-dash" />Control limits</span>
        <span><span className="key-box" style={{ background: "var(--band)" }} />Alarm episode</span>
        {onsetI >= 0 && <span><span className="key-line" style={{ background: "var(--series-2)" }} />Planted fault (ground truth)</span>}
      </div>
    </div>
  );
}
