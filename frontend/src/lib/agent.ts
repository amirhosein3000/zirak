// Read-only client for the trading agent's runs (/api/agent/*): the challenge monitoring page.

import { API_URL, ApiError } from "./api";

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(0, "اتصال به سرور برقرار نشد. آیا بک‌اند روشن است؟");
  }
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "پیدا نشد" : res.statusText);
  return (await res.json()) as T;
}

export type RunRow = { run: string; mode: "live" | "shadow" | "backtest"; start: string | null; commit: string | null };

export type AgentReport = {
  mode: string;
  period: { start: string | null; end: string | null; bars: number };
  start_equity_tmn: number;
  end_equity_tmn: number;
  return_pct: number;
  realized_return_pct: number;
  realized_pnl_tmn: number;
  max_drawdown_pct: number;
  trades: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  volume_tmn: number;
  avg_trade_volume_tmn: number | null;
  trades_per_day: Record<string, number>;
  exits: Record<string, number>;
  by_setup: Record<string, { trades: number; pnl_tmn: number; win_rate_pct: number }>;
  ai: { candidates: number; taken: number; skipped_by_model: number; skipped_by_posture: number; posture_sources: Record<string, number> };
  speed: { order_ack_ms_p50: number | null; order_ack_ms_p95: number | null; bar_decision_latency_ms_p50: number | null };
  stability: { errors: number; orders: number };
  open_positions_at_end: number;
  killed: boolean;
};

export type Decision = {
  id: string;
  ts: string;
  kind: "candidate" | "entry_filled" | "exit" | "guard" | "kill" | "reconcile";
  symbol?: string;
  setup?: string;
  action?: "buy" | "skip";
  exit?: string;
  status?: string;
  reason_fa?: string;
  signal_fa?: string;
  tp_pct?: number;
  sl_pct?: number;
  pnl_tmn?: string;
  pnl_pct?: string;
  indicators?: Record<string, number>;
  model?: { id: string; source: string; prob: number; ev_pct: number; kelly: number; size_mult: number; why: string };
  posture?: { stance: string; mult: number; source: string; reason_fa: string } | null;
  risk?: { equity_tmn: string; risk_tmn: string; bound_by: string; value_tmn: string; qty: string };
};

export type MarketPosture = { stance: "normal" | "cautious" | "avoid"; risk_multiplier: number; allowed_setups: string[]; reason_fa: string };
export type PostureRec = { ts: string; source: string; markets: Record<string, MarketPosture>; summary_fa: string; tool_calls: { name: string; args: Record<string, unknown> }[] };

export type Position = { symbol: string; setup: string; entry_price: string; stop: string; take_profit: string; qty: string; bars: number; max_bars: number };

export type RunSummary = {
  run: string;
  mode: RunRow["mode"];
  commit: string | null;
  config: { markets: string[]; resolution: string; setups: string[]; risk: Record<string, number> };
  report: AgentReport;
  equity: { ts: string; equity: number; drawdown: number }[];
  positions: Position[];
  guard: { last_status: string; killed: boolean; kill_reason: string; peak: string } | null;
  posture: PostureRec | null;
  decisions: Decision[];
};

export const agentApi = {
  runs: () => get<RunRow[]>("/api/agent/runs"),
  run: (name: string) => get<RunSummary>(`/api/agent/runs/${encodeURIComponent(name)}`),
  decision: (name: string, id: string) =>
    get<{ decision: Decision & Record<string, unknown>; follow_ups: Decision[] }>(
      `/api/agent/runs/${encodeURIComponent(name)}/decisions/${encodeURIComponent(id)}`,
    ),
};
