// Typed client for the Zirak FastAPI backend.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

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
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

// ---- types -----------------------------------------------------------------------------------
export type Health = {
  ok: boolean;
  version: string;
  data_source: string;
  data: "synthetic" | "recorded" | "live";
  llm: string;
  live_trading: boolean;
  live_blockers: string[];
  kill_engaged: boolean;
};

export type MarketRow = {
  symbol: string;
  base: string;
  quote: string;
  name_fa: string;
  base_fa: string;
  quote_fa: string;
  price: string | null;
  change_24h_pct: number | null;
  candles: number;
  verified: boolean;
};

export type CandleRow = { ts: string; open: string; high: string; low: string; close: string; volume: string };

export type Facts = {
  symbol: string;
  name_fa: string;
  price: number;
  change_24h_pct: number;
  trend: "up" | "down" | "range";
  ema20: number | null;
  ema50: number | null;
  rsi14: number | null;
  volatility_pct: number | null;
  volatility: "low" | "medium" | "high";
  support: number;
  resistance: number;
  book_imbalance_pct: number | null;
  spread_pct: number | null;
  book_synthetic: boolean;
  mood_score: number;
  mood_fa: string;
};

export type Brief = { symbol: string; brief_fa: string; source: string; facts: Facts; as_of: string; data: string };

export type Condition = {
  kind: string;
  pct?: number | null;
  lookback?: number | null;
  value?: number | null;
  period?: number | null;
  fast?: number | null;
  slow?: number | null;
};

export type StrategySpec = {
  version: 1;
  name: string;
  symbol: string;
  resolution: "15m" | "1h" | "4h" | "1d";
  entry: Condition[];
  exit: Condition[];
  position_size_pct: number;
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  max_entries: number;
  cooldown_candles: number;
};

export type ParseResult = {
  spec: StrategySpec | null;
  description_fa: string[];
  warnings_fa: string[];
  source: string;
  error_fa: string | null;
};

export type CatalogItem = { key: string; title_fa: string; description_fa: string; params: Record<string, number> };

export type Decision = { approved: boolean; qty: string; code: string; notes_fa: string[] };

export type LogEntry = {
  id: number;
  ts: string;
  symbol: string;
  side: "buy" | "sell";
  reason: string;
  note_fa: string;
  indicators: Record<string, number>;
  decision: Decision;
  price: string;
  equity: string;
  order_id: string | null;
  order_status: string | null;
  filled_qty: string;
  avg_price: string | null;
  fee: string;
  fee_asset: string;
  pnl: string | null;
  pnl_pct: string | null;
  explanation_fa: string | null;
};

export type Metrics = {
  start_equity: number;
  end_equity: number;
  pnl: number;
  return_pct: number;
  max_drawdown_pct: number;
  sharpe: number;
  win_rate_pct: number;
  trades: number;
  orders: number;
  exposure_pct: number;
  fees_paid_quote: number;
  buy_hold_return_pct: number;
  buy_hold_max_drawdown_pct: number;
};

export type CurvePoint = { ts: string; equity: number; drawdown_pct: number; price: number; buy_hold: number };

export type Report = {
  id: string;
  created_at: string;
  symbol: string;
  quote: string;
  resolution: string;
  period: PeriodInfo;
  strategy: { key: string; title_fa: string; params: Record<string, unknown> };
  risk: Record<string, unknown>;
  costs: { fee_taker_pct: string; fee_maker_pct: string; slippage_bps: string; participation: string };
  initial_quote: string;
  metrics: Metrics;
  open_position_qty: string;
  equity_curve: CurvePoint[];
  trades: LogEntry[];
  meta: { data?: string; spec?: StrategySpec | null };
  score: Score;
  shield: Shield;
};

export type PeriodKey = "30d" | "90d" | "180d" | "365d" | "all" | "crash";
export type PeriodInfo = { key: PeriodKey; title_fa: string; note_fa: string; start: string; end: string; candles: number };

export type Score = {
  score: number;
  grade: "A" | "B" | "C" | "D" | "E";
  grade_fa: string;
  headline_fa: string;
  details_fa: string;
  components: { profit: number; protection: number; edge: number; consistency: number };
};

export type Shield = {
  saved_quote: number;
  drawdown_cut_pct: number;
  blocked_orders: number;
  risk_exits: number;
  message_fa: string;
  with_shield: { return_pct: number; max_drawdown_pct: number; end_equity: number };
  without_shield: { return_pct: number; max_drawdown_pct: number; end_equity: number };
  without_curve: { ts: string; equity: number }[];
};

export type DuelRow = {
  key: string;
  title_fa: string;
  mine: boolean;
  emotional: boolean;
  return_pct: number;
  max_drawdown_pct: number;
  trades: number;
  win_rate_pct: number;
  score: number;
  grade: string;
  rank: number;
};
export type Duel = { symbol: string; resolution: string; quote: string; period: PeriodInfo; rows: DuelRow[]; headline_fa: string };

export type PreflightCheck = { key: string; ok: boolean; title_fa: string; detail_fa: string; required: boolean };
export type Preflight = {
  ready: boolean;
  checks: PreflightCheck[];
  balances: Record<string, string>;
  fees: Record<string, { maker: string; taker: string }>;
  confirm_phrase: string;
  max_slippage_bps: string;
  order_ttl_s: number;
};

export type Order = {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  type: string;
  qty: string;
  price: string | null;
  status: string;
  filled_qty: string;
  avg_price: string | null;
};

export type BotSnapshot = {
  symbol: string;
  resolution: string;
  strategy: { key: string; title_fa: string; params: Record<string, unknown> };
  price: string;
  equity: string;
  start_equity: string;
  pnl: string;
  pnl_pct: string;
  realized_pnl: string;
  unrealized_pnl: string;
  position_qty: string;
  avg_entry: string | null;
  quote_free: string;
  halted: boolean;
  halt_reason: string;
  killed: boolean;
  stopped: boolean;
  open_orders: Order[];
  candles_seen: number;
};

export type BotStatus = {
  running: boolean;
  mode: string;
  kill_engaged: boolean;
  error: string | null;
  speed_s: number;
  progress: { done: number; total: number };
  live_trading: boolean;
  bot: BotSnapshot | null;
  log: LogEntry[];
  equity_curve: { ts: string; equity: number; price: number }[];
};

export type RunRequest = {
  symbol?: string;
  resolution?: string;
  strategy: string;
  params?: Record<string, unknown>;
  spec?: StrategySpec | null;
  risk?: Record<string, unknown>;
  speed_s?: number;
  period?: PeriodKey;
};

// ---- endpoints -------------------------------------------------------------------------------
export const api = {
  health: () => call<Health>("/api/health"),
  markets: () => call<MarketRow[]>("/api/markets"),
  candles: (symbol: string, resolution = "1h", limit = 200) =>
    call<CandleRow[]>(`/api/markets/${symbol}/candles?resolution=${resolution}&limit=${limit}`),
  brief: (symbol: string) => call<Brief>(`/api/markets/${symbol}/brief`),
  strategies: () => call<CatalogItem[]>("/api/strategies"),
  parse: (text: string, symbol?: string) => post<ParseResult>("/api/strategy/parse", { text, symbol }),
  backtest: (req: RunRequest) => post<Report>("/api/backtest", req),
  report: (id: string) => call<Report>(`/api/backtests/${id}`),
  explain: (entry: LogEntry) => post<{ explanation_fa: string }>("/api/explain", { entry }),
  botStart: (req: RunRequest) => post<BotStatus>("/api/bot/start", req),
  botStatus: () => call<BotStatus>("/api/bot/status"),
  botStop: () => post<BotStatus>("/api/bot/stop"),
  botExplain: (id: number) => call<{ id: number; explanation_fa: string }>(`/api/bot/log/${id}/explain`),
  kill: () => post<BotStatus & { killed: boolean; canceled_orders: string[] }>("/api/kill"),
  killReset: () => post<BotStatus>("/api/kill/reset"),
  duel: (req: RunRequest) => post<Duel>("/api/duel", req),
  preflight: () => call<Preflight>("/api/live/preflight"),
  liveStart: (req: RunRequest & { confirm: string }) => post<BotStatus>("/api/live/start", req),
};
