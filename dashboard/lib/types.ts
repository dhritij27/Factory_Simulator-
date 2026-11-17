// Shape of public/dashboard.json, written by `python -m fabsim dashboard`.
export type Point = { date: string; residual: number | null; ewma: number; lcl: number; ucl: number };
export type Chart = {
  station_id: string;
  metric: string;
  unit: string;
  points: Point[];
  episodes: { detector: string; start_date: string; end_date: string }[];
};
export type Finding = {
  finding_id: string; station_id: string; metric: string; detectors: string;
  first_alarm_date: string; last_alarm_date: string; status: string;
  recent_shift_sigma: number; peak_shift_sigma: number; action_level: "act" | "watch"; direction: string; instrument_id: string;
};
export type Corr = {
  station_id: string; site_id: string; metric: string; bias: number; bias_ci_low: number; bias_ci_high: number;
  threshold: number; flagged: boolean; deming_slope: number; ba_loa_low: number; ba_loa_high: number;
};
export type Pair = { site_id: string; metric: string; station_a: string; station_b: string; diff_over_threshold: number };
export type Grr = {
  station_id: string; metric: string; pct_grr: number; pct_grr_ci_low: number; pct_grr_ci_high: number;
  ndc: number; verdict: "acceptable" | "marginal" | "unacceptable"; n_parts: number;
};
export type Cpk = { station_id: string; metric: string; eye: string; n: number; cpk: number; cpk_ci_low: number; cpk_ci_high: number; frac_out_of_spec: number };
export type Cert = { instrument_id: string; instrument_type: string; station_id: string; cert_id: string; expires_on: string; days_until_expiry: number; status: string };
export type Ticket = { ticket_id: string; instrument_id: string; station_id: string; status: string; priority: string; reason: string; created_on: string; created_by: string };
export type Alert = { alert_id: number; site_id: string; kind: string; field: string; severity: string; first_seen_date: string; last_seen_date: string; n_files: number; detail: string };
export type DetectorScore = { recall: number; detected: number; faults: number; precision: number | null; false_alarms_per_station_month: number; median_delay_days: number | null };

export type Dashboard = {
  generated_at: string; as_of: string; data_from: string;
  totals: { measurements: number; quarantined: number; files: number; stations: number; imputed_instrument: number };
  quarantine: { reason: string; rows: number }[];
  alerts: Alert[];
  charts: Chart[];
  findings: Finding[];
  correlation: Corr[];
  pairs: Pair[];
  grr: Grr[];
  cpk: Cpk[];
  certs: Cert[];
  tickets: Ticket[];
  metrics: Record<string, { unit: string; lsl: number | null; usl: number | null; bias_threshold: number }>;
  backtest: { detectors: Record<string, DetectorScore> | null; correlation: { planted: number; flagged: number; true_positive: number } } | null;
  agent_eval: { passed: number; scenarios: number; agent: string } | null;
  action_shift_sigma: number;
  escalation: { tau: number; escalated: number; faults: number; median_delay_days: number | null; false_escalations_per_station_month: number }[] | null;
  ground_truth: { note: string; faults: { fault_id: string; kind: string; station_id: string; metric: string; onset_day: number }[] };
};

export const METRIC_LABEL: Record<string, string> = {
  mtf50: "MTF50 (sharpness)",
  lum_uniformity: "Luminance uniformity",
  delta_uv: "Colour error Δu′v′",
  vert_misalign: "Vertical misalignment",
};
