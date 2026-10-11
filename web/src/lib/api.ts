export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(path, {
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => (typeof d === "string" ? d : d.msg)).join("; ") : detail;
    throw new ApiError(res.status, msg ?? `HTTP ${res.status}`);
  }
  return data as T;
}

export const fmt = (n: number | null | undefined, digits = 2) =>
  n === null || n === undefined ? "–" : n.toLocaleString("ko-KR", { maximumFractionDigits: digits });

export type Health = {
  status: string;
  mode: string;
  location: string;
  live_enabled: boolean;
  password_configured: boolean;
};

export type RiskField = {
  field: string;
  label: string;
  unit: string;
  default: number;
  min: number;
  max: number;
  step: number;
  risk_direction: number;
};

export type RiskValues = Record<string, number | string>;

export type RiskSettingsRes = {
  version: number;
  values: RiskValues;
  change_kind: string;
  note: string;
  created_at: string;
  fields: RiskField[];
  hard_policy_version: string;
};

export type Metrics = {
  initial_equity: number;
  final_equity: number;
  net_pnl: number;
  return_pct: number;
  max_drawdown_pct: number;
  trades: number;
  win_rate_pct: number;
  profit_factor: number | null;
  gross_pnl: number;
  fees: number;
  funding: number;
  ambiguous_bars: number;
  sharpe_hourly_annualized: number;
};

export type Trade = {
  side: string;
  entry_time: string;
  entry_price: number;
  qty: number;
  stop: number;
  take_profit: number;
  exit_time: string;
  exit_price: number;
  exit_reason: string;
  fees: number;
  funding: number;
  net_pnl: number;
  bars_held: number;
  ambiguous_bar: boolean;
};

export type BacktestDetail = {
  id: number;
  metrics: Metrics;
  trades: Trade[];
  equity_curve: { time: string; equity: number; locked: boolean }[];
  skipped_signals: Record<string, number>;
};

export type BacktestSummary = {
  id: number;
  strategy: string;
  strategy_version: string;
  symbol: string;
  interval: string;
  metrics: Metrics;
  created_at: string;
};

export type Dataset = { symbol: string; interval: string; bars: number; start: string; end: string };
