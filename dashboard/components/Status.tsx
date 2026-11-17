// Status colours never carry meaning alone: each badge pairs the colour with an icon and a label.
const STATUS: Record<string, { color: string; icon: string; label: string }> = {
  acceptable: { color: "var(--good)", icon: "✓", label: "acceptable" },
  marginal: { color: "var(--warning)", icon: "!", label: "marginal" },
  unacceptable: { color: "var(--critical)", icon: "✕", label: "unacceptable" },
  valid: { color: "var(--good)", icon: "✓", label: "valid" },
  expiring_soon: { color: "var(--warning)", icon: "!", label: "expiring soon" },
  expired: { color: "var(--critical)", icon: "✕", label: "expired" },
  active: { color: "var(--critical)", icon: "!", label: "active" },
  act: { color: "var(--critical)", icon: "!", label: "act" },
  watch: { color: "var(--muted)", icon: "~", label: "watch" },
  cleared: { color: "var(--good)", icon: "✓", label: "cleared" },
  error: { color: "var(--critical)", icon: "✕", label: "error" },
  warning: { color: "var(--warning)", icon: "!", label: "warning" },
  info: { color: "var(--muted)", icon: "i", label: "info" },
};

export function Verdict({ v }: { v: string }) {
  const s = STATUS[v] ?? { color: "var(--muted)", icon: "·", label: v };
  return (
    <span className="badge">
      <span className="dot" style={{ background: s.color }} aria-hidden />
      <span aria-hidden style={{ fontWeight: 700, width: 10, textAlign: "center" }}>{s.icon}</span>
      {s.label}
    </span>
  );
}
