// API(backend/api/schemas.py)とやり取りする型と関数。
// 画面からは /api/... を呼び、next.config.ts の rewrites で FastAPI(既定は http://localhost:8000)に転送する。

export type ErrorItem = { field: string | null; message: string };

export type DataInfo = {
  source_id: string;
  source_label: string;
  license_note: string;
  /** データを取得した日時(UTC。架空データは null) */
  fetched_at: string | null;
  /** 最新のデータを取得できず、保存済みの古いデータを使ったときの説明 */
  warning: string | null;
};

export type DataSource = {
  id: string;
  label: string;
  markets: string[];
  license_note: string;
  can_fetch: boolean;
};

export type EngineInfo = { id: string; label: string; available: boolean; note: string };

/** 総当たりに使うエンジン(docs/sweep.md)。max_pairs は計算できる組み合わせの数の上限 */
export type SweepEngineInfo = EngineInfo & { max_pairs: number };

export type Meta = {
  data_sources: DataSource[];
  engines: EngineInfo[];
  sweep_engines: SweepEngineInfo[];
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

export type CorporateAction = {
  date: string;
  ex_rt: number | null;
  label: string;
  adj_factor: number;
  /** 持ち株数が変わる日か(分割・併合で、調整係数が1でない日。docs/mvp.md 2.8) */
  changes_shares: boolean;
};

export type SymbolDetail = {
  symbol: SymbolSummary;
  market: { code: string; name: string; currency: string; lot_size: number; trading_days_per_year: number };
  range: { first_date: string; last_date: string; business_days: number; trading_days: number };
  corporate_actions: CorporateAction[];
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
  | "data_license"
  | "stale_data"
  | "trials"
  | "selection_bias"
  | "no_holdout"
  | "aligned_start"
  | "sampling_error";

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
    trading_days_per_year: number;
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
  /** 期間内の権利落ち(株を持っていない日も含む)。チャートの線を切る位置などに使う */
  corporate_actions: CorporateAction[];
  data_info: DataInfo;
  elapsed_ms: number;
};

// --- 総当たり(docs/sweep.md。backend/api/schemas.py の Sweep*) ----------------------------

export type SweepGridKey = "short_min" | "short_max" | "short_step" | "long_min" | "long_max" | "long_step";
export type SweepGrid = Record<SweepGridKey, number>;
export type CostKey = "fee_rate_pct" | "slippage_rate_pct" | "initial_cash";

export type SweepRequest = {
  symbol_id: string;
  strategy_id: string;
  engine: string;
  start_date: string;
  end_date: string;
  /** 検証期間(アウトオブサンプル)の開始日。null は検証期間なし */
  holdout_start_date: string | null;
  grid: SweepGrid;
  params: Record<CostKey, number>;
};

export type SegmentName = "in_sample" | "out_of_sample";

export type SweepSegment = {
  name: SegmentName;
  /** 計算した期間の開始日(選ぶ期間は、始まりをそろえたあとの日。docs/sweep.md 3章) */
  start_date: string;
  end_date: string;
  /** 指定した開始日。選ぶ期間の始まりをそろえたときだけ start_date と違う */
  requested_start_date: string;
  /** そろえるためにウォームアップにだけ使った営業日の数 */
  skipped_business_days: number;
  first_business_day: string;
  last_business_day: string;
  business_days: number;
};

export type SweepMetrics = {
  total_return: number;
  annualized_return: number | null;
  max_drawdown: number;
  sharpe_ratio: number | null;
  win_rate: number | null;
  trade_count: number;
  winning_trades: number;
  return_count: number;
  insufficient_cash_count: number;
  final_equity: number;
  /** 株を持っていた営業日の数 */
  holding_days: number;
};

export type SweepCombo = {
  short_window: number;
  long_window: number;
  in_sample: SweepMetrics;
  out_of_sample: SweepMetrics | null;
};

export type Objective = "sharpe_ratio" | "total_return" | "max_drawdown";

/** 1つの基準で並べた結果(docs/sweep.md 7章)。位置は combos の中の位置 */
export type SweepRanking = {
  objective: Objective;
  order: number[];
  best_index: number | null;
  /** 1位と同じ値の組み合わせの数。2以上なら1位は1つに決まらない(order の先頭からこの数) */
  best_tie_count: number;
  /** 1位の検証期間での順位(同率1位のときは null) */
  best_out_of_sample_rank: number | null;
  in_sample_ranked: number;
  out_of_sample_ranked: number;
  rank_correlation: number | null;
  correlation_pairs: number;
  neighbors_mean: number | null;
  neighbors_count: number;
};

export type SweepResult = {
  symbol: SymbolSummary;
  strategy_id: string;
  engine: SweepEngineInfo;
  segments: SweepSegment[];
  grid: SweepGrid & { short_values: number[]; long_values: number[] };
  params: {
    fee_rate_pct: number;
    slippage_rate_pct: number;
    fee_rate: number;
    slippage_rate: number;
    initial_cash: number;
    lot_size: number;
    trading_days_per_year: number;
  };
  count: number;
  combos: SweepCombo[];
  rankings: SweepRanking[];
  notes: { kind: NoteKind; message: string }[];
  data_info: DataInfo;
};

export type SweepStatus = {
  id: string;
  status: "running" | "done" | "failed" | "cancelled";
  done: number;
  total: number;
  elapsed_ms: number | null;
  result: SweepResult | null;
  error: { detail: string; errors: ErrorItem[] } | null;
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

export const UNREACHABLE =
  "API サーバーに接続できません。ターミナルで make dev-api を実行してから、もう一度試してください";
const UNREADABLE = "サーバーの応答を読み取れませんでした。ページを再読み込みしても直らないときは、API サーバーのターミナルを確認してください";

/** 応答の本文が JSON でないとき、状態コードから起きたことを推測して日本語にする。 */
function nonJsonMessage(status: number): string {
  // FastAPI は、想定外の例外も含めて必ず JSON で返す(backend/api/errors.py)。
  // JSON でない 500 / 502 / 503 / 504 は、Next.js の中継(rewrites)が API サーバーにつながらなかったとき。
  // Next.js は転送先につながらないと、本文が「Internal Server Error」の 500 を返す。
  if (status >= 500) return UNREACHABLE;
  if (status >= 200 && status < 300) return UNREADABLE;
  return `エラーが発生しました(HTTP ${status})。ページを再読み込みしても直らないときは、API サーバーのターミナルを確認してください`;
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/**
 * API の呼び出し口を作る。テストでは fetch を差し替える(lib/api.test.ts)。
 * 失敗はすべて ApiError(日本語のメッセージ付き)にして投げる。
 */
export function createApi(fetchImpl: Fetch = (input, init) => fetch(input, init)) {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetchImpl(path, {
        ...init,
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      });
    } catch {
      // ネットワークの失敗(画面の開発サーバーも止まっている、など)
      throw new ApiError(0, UNREACHABLE);
    }
    const text = await response.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      throw new ApiError(response.status, nonJsonMessage(response.status));
    }
    if (!response.ok) {
      const b = (body ?? {}) as { detail?: unknown; errors?: unknown };
      const detail =
        typeof b.detail === "string"
          ? b.detail
          : `エラーが発生しました(HTTP ${response.status})。API サーバーのターミナルを確認してください`;
      const errors = Array.isArray(b.errors) ? (b.errors as ErrorItem[]) : [];
      throw new ApiError(response.status, detail, errors);
    }
    return body as T;
  }

  return {
    meta: () => request<Meta>("/api/meta"),
    strategies: () => request<{ items: Strategy[] }>("/api/strategies").then((r) => r.items),
    searchSymbols: (q: string, limit = 20) =>
      request<{ items: SymbolSummary[] }>(`/api/symbols?q=${encodeURIComponent(q)}&limit=${limit}`).then(
        (r) => r.items,
      ),
    symbol: (id: string) => request<SymbolDetail>(`/api/symbols/${encodeURIComponent(id)}`),
    runBacktest: (body: BacktestRequest) =>
      request<BacktestResult>("/api/backtests", { method: "POST", body: JSON.stringify(body) }),
    startSweep: (body: SweepRequest) =>
      request<SweepStatus>("/api/sweeps", { method: "POST", body: JSON.stringify(body) }),
    sweepStatus: (id: string) => request<SweepStatus>(`/api/sweeps/${encodeURIComponent(id)}`),
    cancelSweep: (id: string) =>
      request<SweepStatus>(`/api/sweeps/${encodeURIComponent(id)}`, { method: "DELETE" }),
  };
}

export const api = createApi();

/** エラーを画面に出す文にする(ApiError 以外は、次にすることを添えた予備の文)。 */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  return `${fallback}。ページを再読み込みして、もう一度試してください`;
}
