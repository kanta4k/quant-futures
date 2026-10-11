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
  time_in_market_pct?: number;
  sharpe_hourly_annualized: number;
  start?: string;
  end?: string;
  segments?: Partial<Record<SegmentName, Metrics>>;
};

export type SegmentName = "train" | "validation" | "test";

export type SymbolStats = { trades: number; net_pnl: number; fees: number; win_rate_pct: number };

export type Segment = {
  start: string;
  end: string;
  metrics: Metrics;
  by_symbol: Record<string, SymbolStats>;
  skipped_signals: Record<string, number>;
};

export type Trade = {
  symbol: string;
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
  request?: { symbols?: string[]; params?: Record<string, unknown>; universe?: { mode: string; top_k: number } };
  metrics: Metrics;
  trades: Trade[];
  equity_curve: { time: string; equity: number; locked: boolean; gross_exposure?: number; positions?: number }[];
  skipped_signals: Record<string, number>;
  by_symbol?: Record<string, SymbolStats>;
  segments: Partial<Record<SegmentName, Segment>>;
  period?: { start: string; end: string };
  universe_mode?: string;
};

export type OptimizeRow = {
  params: Record<string, unknown>;
  train: Metrics;
  validation: Metrics;
  score: number;
};

export type OptimizeJob = {
  id: string;
  status: "running" | "done" | "error";
  total: number;
  done: number;
  error: string | null;
  elapsed_sec: number;
  objective: string;
  ranked: OptimizeRow[];
  excluded: OptimizeRow[];
};

export const SKIP_LABELS: Record<string, string> = {
  risk_locked: "손실 한도 잠금",
  not_in_universe: "유니버스 밖",
  cooldown: "재진입 대기",
  max_positions: "최대 동시 포지션",
  below_min_notional: "최소 주문금액 미달",
  total_risk: "전체 위험 한도",
  corr_group_risk: "상관 그룹 위험 한도",
  corr_group_exposure: "상관 그룹 익스포저",
  symbol_exposure: "종목 익스포저",
  gross_exposure: "총 익스포저",
  net_exposure: "순 익스포저",
  margin: "증거금",
  invalid_stop: "손절 계산 불가",
};

export const SEGMENT_LABELS: Record<SegmentName, string> = {
  train: "학습",
  validation: "검증",
  test: "최종 평가",
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
