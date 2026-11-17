"use client";
import { useState } from "react";

/** Horizontal bars for a single series (no legend needed: the title names it). */
export default function BarList({ rows, total }: { rows: { label: string; value: number }[]; total?: number }) {
  const [hover, setHover] = useState<string | null>(null);
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div role="list">
      {rows.map((r) => (
        <div key={r.label} role="listitem" tabIndex={0} onPointerEnter={() => setHover(r.label)} onPointerLeave={() => setHover(null)}
             style={{ display: "grid", gridTemplateColumns: "150px 1fr 90px", gap: 8, alignItems: "center", padding: "3px 0" }}>
          <span style={{ color: "var(--ink-2)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis" }}>{r.label.replace(/_/g, " ")}</span>
          <span style={{ height: 14, display: "block" }}>
            <span style={{ display: "block", height: "100%", width: `${(r.value / max) * 100}%`, minWidth: 2,
                           background: "var(--series-1)", borderRadius: "0 4px 4px 0", opacity: hover && hover !== r.label ? 0.6 : 1 }} />
          </span>
          <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 12 }}>
            {r.value.toLocaleString()}{total ? <span style={{ color: "var(--muted)" }}> · {((100 * r.value) / total).toFixed(2)}%</span> : null}
          </span>
        </div>
      ))}
    </div>
  );
}
