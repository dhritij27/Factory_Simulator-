"use client";
import { useState } from "react";
import type { Pair } from "@/lib/types";

const CLAMP = 3; // colour saturates at +/- 3x the practical bias threshold

function cellColor(v: number) {
  const t = Math.min(1, Math.abs(v) / CLAMP);
  const pole = v >= 0 ? "var(--div-pos)" : "var(--div-neg)";
  return `color-mix(in oklab, ${pole} ${Math.round(t * 100)}%, var(--div-mid))`;
}

/** Station-vs-station bias difference within one site, in units of the bias threshold. */
export default function Heatmap({ pairs }: { pairs: Pair[] }) {
  const stations = Array.from(new Set(pairs.map((p) => p.station_a))).sort();
  const val = (a: string, b: string) => pairs.find((p) => p.station_a === a && p.station_b === b)?.diff_over_threshold ?? 0;
  const [tip, setTip] = useState<{ a: string; b: string; v: number; x: number; y: number } | null>(null);
  const cell = 52, lab = 104;
  const w = lab + cell * stations.length, h = 22 + cell * stations.length;
  return (
    <div className="chartwrap scroll">
      <svg width={w} height={h} role="img" aria-label="Station-to-station bias difference heatmap">
        {stations.map((s, j) => (
          <text key={"c" + s} x={lab + j * cell + cell / 2} y={14} textAnchor="middle">{s.split("-").slice(-2).join("-")}</text>
        ))}
        {stations.map((a, i) => (
          <g key={a}>
            <text x={lab - 8} y={22 + i * cell + cell / 2 + 4} textAnchor="end">{a}</text>
            {stations.map((b, j) => {
              const v = val(a, b);
              const strong = Math.abs(v) / CLAMP > 0.55;
              return (
                <g key={b} tabIndex={0}
                   onPointerMove={() => setTip({ a, b, v, x: lab + j * cell, y: 22 + i * cell })}
                   onFocus={() => setTip({ a, b, v, x: lab + j * cell, y: 22 + i * cell })}
                   onPointerLeave={() => setTip(null)} onBlur={() => setTip(null)}>
                  <rect x={lab + j * cell + 1} y={22 + i * cell + 1} width={cell - 2} height={cell - 2} rx={4}
                        fill={cellColor(v)} stroke={tip?.a === a && tip?.b === b ? "var(--ink)" : "none"} />
                  <text x={lab + j * cell + cell / 2} y={22 + i * cell + cell / 2 + 4} textAnchor="middle"
                        style={{ fill: strong ? "#ffffff" : "var(--ink)" }}>{a === b ? "" : v.toFixed(1)}</text>
                </g>
              );
            })}
          </g>
        ))}
      </svg>
      {tip && tip.a !== tip.b && (
        <div className="tip" style={{ left: Math.min(tip.x + 56, w - 220), top: tip.y }}>
          <b>{tip.v.toFixed(2)}×</b> threshold
          <div style={{ color: "var(--ink-2)" }}>{tip.a} reads {tip.v >= 0 ? "higher" : "lower"} than {tip.b}</div>
        </div>
      )}
      <div className="legend">
        <span><span className="key-box" style={{ background: cellColor(-CLAMP) }} />row reads lower</span>
        <span><span className="key-box" style={{ background: "var(--div-mid)" }} />agree</span>
        <span><span className="key-box" style={{ background: cellColor(CLAMP) }} />row reads higher</span>
        <span>Cell = (row bias − column bias) ÷ practical bias threshold; saturates at ±{CLAMP}</span>
      </div>
    </div>
  );
}
