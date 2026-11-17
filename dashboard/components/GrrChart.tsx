"use client";
import { useState } from "react";
import type { Grr } from "@/lib/types";
import { useWidth } from "./useWidth";
import { Verdict } from "./Status";

/** %GRR point estimate with its 95% bootstrap interval, one row per station. */
export default function GrrChart({ rows }: { rows: Grr[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<number | null>(null);
  const sorted = [...rows].sort((a, b) => b.pct_grr - a.pct_grr);
  const L = 116, R = 132, rowH = 22, top = 20;
  const max = Math.max(40, ...sorted.map((r) => r.pct_grr_ci_high)) * 1.05;
  const iw = width - L - R;
  const x = (v: number) => L + (v / max) * iw;
  const h = top + rowH * sorted.length + 8;
  return (
    <div ref={ref} className="chartwrap">
      <svg width={width} height={h} role="img" aria-label="Gauge R&R percent with 95% confidence intervals by station">
        {[0, 10, 30].map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top - 4} y2={h - 8} stroke={t ? "var(--axis)" : "var(--grid)"} strokeDasharray={t ? "4 3" : undefined} />
            <text x={x(t)} y={12} textAnchor="middle">{t}%</text>
          </g>
        ))}
        {sorted.map((r, i) => {
          const cy = top + i * rowH + rowH / 2;
          return (
            <g key={r.station_id} tabIndex={0} onPointerMove={() => setTip(i)} onPointerLeave={() => setTip(null)}
               onFocus={() => setTip(i)} onBlur={() => setTip(null)}>
              <rect x={0} y={cy - rowH / 2} width={width} height={rowH} fill={tip === i ? "var(--grid)" : "transparent"} opacity={0.5} />
              <text x={L - 8} y={cy + 4} textAnchor="end" style={{ fill: "var(--ink-2)" }}>{r.station_id}</text>
              <line x1={x(r.pct_grr_ci_low)} x2={x(r.pct_grr_ci_high)} y1={cy} y2={cy} stroke="var(--series-1)" strokeWidth={2} strokeLinecap="round" />
              <circle cx={x(r.pct_grr)} cy={cy} r={4.5} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
              <foreignObject x={width - R + 8} y={cy - 9} width={R - 8} height={18}>
                <Verdict v={r.verdict} />
              </foreignObject>
            </g>
          );
        })}
      </svg>
      {tip !== null && (
        <div className="tip" style={{ left: Math.min(x(sorted[tip].pct_grr) + 12, width - 200), top: top + tip * rowH - 4 }}>
          <b>{sorted[tip].pct_grr.toFixed(1)}%</b> GRR <span style={{ color: "var(--ink-2)" }}>({sorted[tip].pct_grr_ci_low.toFixed(1)}–{sorted[tip].pct_grr_ci_high.toFixed(1)}, 95% CI)</span>
          <div style={{ color: "var(--ink-2)" }}>{sorted[tip].n_parts} parts · ndc {sorted[tip].ndc.toFixed(1)}</div>
        </div>
      )}
      <div className="legend">
        <span><span className="key-line" style={{ background: "var(--series-1)" }} />%GRR with 95% bootstrap CI</span>
        <span><span className="key-dash" />10% / 30% acceptance lines (AIAG)</span>
      </div>
    </div>
  );
}
