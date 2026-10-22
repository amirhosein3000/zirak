// Client for the optional backend modules (/api/m/<name>). Each module can be switched off with the
// MODULES env flag on the backend; the tools page only shows what /api/modules reports as enabled.

import { API_URL, ApiError } from "./api";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "اتصال به سرور برقرار نشد. آیا بک‌اند روشن است؟");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : "درخواست نامعتبر است";
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}
const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export type Regime = {
  symbol: string;
  regime: "trending_up" | "trending_down" | "ranging" | "volatile";
  efficiency: number;
  slope_pct: number;
  atr_pct: number;
  atr_ratio: number;
  label_fa: string;
  advice_fa: string;
  suits: string[];
};
export type MetricsLite = { return_pct: number; max_drawdown_pct: number; trades: number; buy_hold_return_pct: number };
export type GatedResult = { plain: MetricsLite; gated: MetricsLite; allowed: string[] };

export type Wall = { side: "bid" | "ask"; price: number; qty: number; distance_pct: number; size_x_median: number };
export type BookStats = {
  symbol: string;
  mid: number;
  spread_pct: number;
  bid_depth_1pct: number;
  ask_depth_1pct: number;
  imbalance_pct: number;
  walls: Wall[];
  synthetic: boolean;
  summary_fa: string;
};
export type FairUsdt = { market_mid: number | null; implied: Record<string, number>; fair: number | null; premium_pct: number | null; summary_fa: string };

export type NewsItem = { title: string; source: string; url: string | null; published: string | null; score: number; assets: string[] };
export type News = {
  score: number;
  label_fa: string;
  positive: number;
  negative: number;
  neutral: number;
  size_factor: number;
  summary_fa: string;
  items: NewsItem[];
  source: string;
  news_risk_enabled: boolean;
};

export type PortfolioResult = {
  targets: Record<string, string>;
  rebalanced: { return_pct: number; max_drawdown_pct: number };
  hold: { return_pct: number; max_drawdown_pct: number };
  rebalances: { ts: string; note_fa: string; trades: { asset: string; side: string; qty: string }[] }[];
  fees_tmn: string;
  period: { start: string; end: string; candles: number };
  curve: { ts: string; rebalanced: number; hold: number }[];
};

export type AlertRow = { id: string; symbol: string; kind: string; value: number; once: boolean; active: boolean; last_fired: string | null };
export type AlertEvent = { alert_id: string; ts: string; message_fa: string; channels: string[] };
export type Alerts = { alerts: AlertRow[]; events: AlertEvent[]; channels: { telegram: boolean; bale: boolean }; kinds_fa: Record<string, string> };

export type Finding = { code: string; severity: "high" | "medium" | "low" | "good"; title_fa: string; detail_fa: string; suggestion_fa: string };
export type Coach = { score: number; trades: number; summary_fa: string; findings: Finding[]; symbol: string; source: string };

export type CompEntry = {
  name: string;
  symbol: string;
  strategy: string;
  quote: string;
  equity: string;
  start_equity: string;
  pnl_pct: string;
  max_drawdown_pct: string;
  trades: number;
  wins: number;
  running: boolean;
  killed: boolean;
};
export type Competition = {
  running: boolean;
  name?: string;
  mode?: string;
  stopped_reason?: string | null;
  kill_engaged?: boolean;
  total_equity_tmn?: string;
  start_equity_tmn?: string;
  pnl_pct?: string;
  drawdown_from_peak_pct?: string;
  limits?: { max_drawdown_pct: string; daily_loss_pct: string };
  entries: CompEntry[];
};

export const modulesApi = {
  list: () => call<{ enabled: string[]; available: Record<string, string> }>("/api/modules"),
  regime: (symbol: string) => call<Regime>(`/api/m/regime/${symbol}`),
  regimeBacktest: (symbol: string, strategy: string, allowed: string[]) =>
    post<GatedResult>("/api/m/regime/backtest", { symbol, strategy, allowed }),
  book: (symbol: string) => call<BookStats>(`/api/m/orderbook/${symbol}`),
  fairUsdt: () => call<FairUsdt>("/api/m/orderbook/fair-usdt"),
  news: (asset?: string) => call<News>(`/api/m/news${asset ? `?asset=${asset}` : ""}`),
  portfolio: (targets: Record<string, number>, threshold_pct: number) =>
    post<PortfolioResult>("/api/m/portfolio/backtest", { targets, threshold_pct }),
  alerts: () => call<Alerts>("/api/m/alerts"),
  addAlert: (a: { symbol: string; kind: string; value: number; once: boolean }) => post<AlertRow>("/api/m/alerts", a),
  deleteAlert: (id: string) => call<{ deleted: boolean }>(`/api/m/alerts/${id}`, { method: "DELETE" }),
  checkAlerts: () => post<{ fired: AlertEvent[] }>("/api/m/alerts/check"),
  coach: (source: "bot" | "emotional", symbol: string) => post<Coach>("/api/m/coach", { source, symbol }),
  compDefault: () => call<Record<string, unknown>>("/api/m/competition/default-config"),
  compStart: (cfg: Record<string, unknown>) => post<Competition>("/api/m/competition/start", cfg),
  compStatus: () => call<Competition>("/api/m/competition/status"),
  compStop: () => post<Competition>("/api/m/competition/stop"),
  compKill: () => post<Competition>("/api/m/competition/kill"),
};
