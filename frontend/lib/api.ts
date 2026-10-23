// API(backend/api/schemas.py)とやり取りする型と関数。
// 画面からは /api/... を呼び、next.config.ts の rewrites で FastAPI(既定は http://localhost:8000)に転送する。

export type ErrorItem = { field: string | null; message: string };

export type DataInfo = {
  source_id: string;
  source_label: string;
  license_note: string;
  fetched_at: string | null;
};

export type DataSource = {
  id: string;
  label: string;
  markets: string[];
  license_note: string;
  can_fetch: boolean;
};

export type EngineInfo = { id: string; label: string; available: boolean; note: string };

export type Meta = {
  data_sources: DataSource[];
  engines: EngineInfo[];
  trading_days_per_year: number;
};

export type SymbolSummary = {
  id: string;
  market: string;
  code: string;
  name: string;
  name_en: string | null;
  segment: string | null;
  sector: string | null;
  source_id: string;
  description: string | null;
};

export type SymbolDetail = {
  symbol: SymbolSummary;
  market: { code: string; name: string; currency: string; lot_size: number };
  range: { first_date: string; last_date: string; business_days: number; trading_days: number };
  corporate_actions: { date: string; ex_rt: number | null; label: string; adj_factor: number }[];
  halted_days: number;
  data_info: DataInfo;
};

export type ParamSpec = {
  key: ParamKey;
  label: string;
  kind: "integer" | "percent" | "yen";
  default: number;
  minimum: number;
  maximum: number | null;
  exclusive_maximum: boolean;
  step: number;
  help: string;
};

export type Strategy = {
  id: string;
  name: string;
  summary: string;
  description: string;
  available: boolean;
  params: ParamSpec[];
};

export type ParamKey =
  | "short_window"
  | "long_window"
  | "fee_rate_pct"
  | "slippage_rate_pct"
  | "initial_cash";

export type Params = Record<ParamKey, number>;

export type BacktestRequest = {
  symbol_id: string;
  strategy_id: string;
  engine: string;
  start_date: string | null;
  end_date: string | null;
  params: Params;
};

export type Daily = {
  date: string;
  close: number | null;
  short_ma: number | null;
  long_ma: number | null;
  cash: number;
  shares: number;
  valuation_price: number | null;
  equity: number;
  drawdown: number;
};

export type Fill = {
  date: string;
  signal_date: string;
  side: "buy" | "sell";
  open_price: number;
  fill_price: number;
  shares: number;
  notional: number;
  fee: number;
  cash_after: number;
};

export type Trade = {
  entry_date: string;
  entry_price: number;
  entry_shares: number;
  buy_cost: number;
  exit_date: string | null;
  exit_price: number | null;
  exit_shares: number | null;
  sell_proceeds: number | null;
  fraction_cash: number;
  pnl: number | null;
  return_pct: number | null;
  closed_by: "sell" | "merger" | null;
};

export type CorporateActionEvent = {
  date: string;
  ex_rt: number;
  label: string;
  adj_factor: number;
  ratio: string;
  shares_before: number;
  shares_after: number;
  fraction_shares: number;
  fraction_cash: number;
  closed_position: boolean;
};

export type NoteKind =
  | "liquidation"
  | "annualized_reference"
  | "survivorship"
  | "demo_data"
  | "warmup_shortage"
  | "insufficient_cash"
  | "execution_assumption"
  | "data_license";

export type BacktestResult = {
  symbol: SymbolSummary;
  strategy_id: string;
  engine: EngineInfo;
  period: {
    start_date: string;
    end_date: string;
    first_business_day: string;
    last_business_day: string;
    business_days: number;
    return_count: number;
  };
  params: {
    short_window: number;
    long_window: number;
    fee_rate_pct: number;
    slippage_rate_pct: number;
    fee_rate: number;
    slippage_rate: number;
    initial_cash: number;
    lot_size: number;
  };
  metrics: {
    total_return: number;
    annualized_return: number | null;
    max_drawdown: number;
    sharpe_ratio: number | null;
    win_rate: number | null;
    trade_count: number;
    winning_trades: number;
    final_equity: number;
    profit: number;
  };
  warmup: {
    first_date: string | null;
    last_date: string | null;
    valid_days: number;
    sufficient: boolean;
    signals_unavailable_until: string | null;
    label: string;
  };
  insufficient_cash_count: number;
  notes: { kind: NoteKind; message: string }[];
  daily: Daily[];
  signals: { date: string; side: "buy" | "sell"; action: "order" | "ignored" }[];
  fills: Fill[];
  skipped_orders: {
    date: string;
    signal_date: string;
    open_price: number;
    fill_price: number;
    cash: number;
  }[];
  events: CorporateActionEvent[];
  trades: Trade[];
  data_info: DataInfo;
  elapsed_ms: number;
};

export class ApiError extends Error {
  readonly status: number;
  readonly errors: ErrorItem[];

  constructor(status: number, detail: string, errors: ErrorItem[] = []) {
    super(detail);
    this.status = status;
    this.errors = errors;
  }

  fieldErrors(): Partial<Record<string, string>> {
    const map: Partial<Record<string, string>> = {};
    for (const e of this.errors) {
      if (e.field && !map[e.field]) map[e.field] = e.message;
    }
    return map;
  }
}

const UNREACHABLE =
  "API サーバーに接続できません。ターミナルで make dev-api を実行してから、もう一度試してください";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  if (response.status === 502 || response.status === 504) {
    // rewrites 先(FastAPI)が起動していないとき
    throw new ApiError(response.status, UNREACHABLE);
  }
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    throw new ApiError(response.status, response.ok ? "応答を読み取れませんでした" : UNREACHABLE);
  }
  if (!response.ok) {
    const b = (body ?? {}) as { detail?: unknown; errors?: ErrorItem[] };
    const detail = typeof b.detail === "string" ? b.detail : `エラーが発生しました(HTTP ${response.status})`;
    throw new ApiError(response.status, detail, Array.isArray(b.errors) ? b.errors : []);
  }
  return body as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  strategies: () => request<{ items: Strategy[] }>("/api/strategies").then((r) => r.items),
  searchSymbols: (q: string, limit = 20) =>
    request<{ items: SymbolSummary[] }>(
      `/api/symbols?q=${encodeURIComponent(q)}&limit=${limit}`,
    ).then((r) => r.items),
  symbol: (id: string) => request<SymbolDetail>(`/api/symbols/${encodeURIComponent(id)}`),
  runBacktest: (body: BacktestRequest) =>
    request<BacktestResult>("/api/backtests", { method: "POST", body: JSON.stringify(body) }),
};
