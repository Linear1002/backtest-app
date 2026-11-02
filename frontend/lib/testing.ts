// テスト用の小さなデータ(画面のテストだけで使う。アプリからは import しない)。

import { readFileSync } from "node:fs";

import type {
  BacktestResult,
  Meta,
  ParamSpec,
  Strategy,
  SweepCombo,
  SweepMetrics,
  SweepResult,
  SymbolDetail,
  SymbolSummary,
  WalkForwardResult,
} from "./api.ts";

/** リポジトリの tests/fixtures/ にある JSON(API のテストと共有している)を読む。 */
export function fixture<T>(name: string): T {
  return JSON.parse(readFileSync(new URL(`../../tests/fixtures/${name}`, import.meta.url), "utf-8")) as T;
}

/**
 * 移動平均クロスのパラメータの定義。API が返すもの(GET /api/strategies)をそのまま保存したファイルを読む。
 * API 側のテスト(tests/python/test_param_contract.py)が、このファイルと API の定義が同じことを確かめている。
 */
export const SPECS: ParamSpec[] = fixture<ParamSpec[]>("ma_cross_params.json");

export const STRATEGIES: Strategy[] = [
  { id: "ma_cross", name: "移動平均クロス", summary: "", description: "", available: true, params: SPECS },
  { id: "rsi_reversal", name: "RSI 逆張り", summary: "", description: "", available: false, params: [] },
];

export const META: Meta = {
  data_sources: [{ id: "demo", label: "架空データ", markets: ["DEMO"], license_note: "", can_fetch: true }],
  engines: [{ id: "python", label: "Python", available: true, note: "" }],
  sweep_engines: [
    { id: "python", label: "Python", available: true, note: "", max_pairs: 2000 },
    { id: "cuda", label: "CUDA", available: false, note: "まだありません", max_pairs: 20000 },
  ],
  trading_days_per_year: 245,
};

export function symbol(id: string, name = `銘柄 ${id}`): SymbolSummary {
  const [market, code] = id.split(":");
  return { id, market, code, name, name_en: null, segment: null, sector: null, source_id: "demo", description: null };
}

export function detail(id: string, first_date = "2024-01-04", last_date = "2025-12-30"): SymbolDetail {
  return {
    symbol: symbol(id),
    market: { code: "DEMO", name: "架空", currency: "JPY", lot_size: 100, trading_days_per_year: 245 },
    range: { first_date, last_date, business_days: 490, trading_days: 490 },
    corporate_actions: [],
    halted_days: 0,
    data_info: { source_id: "demo", source_label: "架空データ", license_note: "", fetched_at: null, warning: null },
  };
}

/** 中身はほとんど空の結果(画面の状態遷移のテスト用)。 */
export function result(symbolId: string): BacktestResult {
  return {
    symbol: symbol(symbolId),
    strategy_id: "ma_cross",
    engine: { id: "python", label: "Python", available: true, note: "" },
    period: {
      start_date: "2024-01-04",
      end_date: "2025-12-30",
      first_business_day: "2024-01-04",
      last_business_day: "2025-12-30",
      business_days: 490,
      return_count: 489,
    },
    params: {
      short_window: 5,
      long_window: 25,
      fee_rate_pct: 0.1,
      slippage_rate_pct: 0.05,
      fee_rate: 0.001,
      slippage_rate: 0.0005,
      initial_cash: 1_000_000,
      lot_size: 100,
      trading_days_per_year: 245,
    },
    metrics: {
      total_return: 0,
      annualized_return: 0,
      max_drawdown: 0,
      sharpe_ratio: null,
      win_rate: null,
      trade_count: 0,
      winning_trades: 0,
      final_equity: 1_000_000,
      profit: 0,
    },
    warmup: { first_date: null, last_date: null, valid_days: 0, sufficient: false, signals_unavailable_until: null, label: "" },
    insufficient_cash_count: 0,
    notes: [],
    daily: [],
    signals: [],
    fills: [],
    skipped_orders: [],
    events: [],
    trades: [],
    benchmark: {
      label: "買い持ち",
      status: "not_bought",
      signal_date: null,
      fill: null,
      skipped: null,
      events: [],
      metrics: BENCHMARK_FLAT,
      open_position_at_end: false,
    },
    corporate_actions: [],
    data_info: { source_id: "demo", source_label: "架空データ", license_note: "", fetched_at: null, warning: null },
    elapsed_ms: 1,
  };
}

/** 買い持ちが何もしなかったときの成績(初期資金100万円のまま) */
const BENCHMARK_FLAT = {
  total_return: 0,
  annualized_return: 0,
  max_drawdown: 0,
  sharpe_ratio: null,
  return_count: 489,
  final_equity: 1_000_000,
};

function sweepMetrics(sharpe: number | null, total: number, drawdown: number): SweepMetrics {
  return {
    total_return: total,
    annualized_return: null,
    max_drawdown: drawdown,
    sharpe_ratio: sharpe,
    win_rate: null,
    trade_count: 3,
    winning_trades: 1,
    return_count: 100,
    insufficient_cash_count: 0,
    final_equity: 1_000_000 * (1 + total),
    holding_days: 60,
  };
}

/**
 * 総当たりの小さな結果(短期 3・6 × 長期 10・20 の4通り、検証期間あり)。
 * 選ぶ期間のシャープレシオは (6,20) が1位。
 */
export function sweepResult(symbolId: string): SweepResult {
  const combos: SweepCombo[] = [
    { short_window: 3, long_window: 10, in_sample: sweepMetrics(0.2, 0.05, 0.2), out_of_sample: sweepMetrics(0.4, 0.03, 0.1) },
    { short_window: 3, long_window: 20, in_sample: sweepMetrics(0.6, 0.12, 0.15), out_of_sample: sweepMetrics(-0.3, -0.04, 0.12) },
    { short_window: 6, long_window: 10, in_sample: sweepMetrics(null, 0, 0), out_of_sample: sweepMetrics(0.1, 0.01, 0.05) },
    { short_window: 6, long_window: 20, in_sample: sweepMetrics(1.1, 0.3, 0.1), out_of_sample: sweepMetrics(0.2, 0.02, 0.08) },
  ];
  return {
    symbol: symbol(symbolId),
    strategy_id: "ma_cross",
    engine: { id: "python", label: "Python", available: true, note: "", max_pairs: 2000 },
    segments: [
      // 選ぶ期間は、長期20日のウォームアップのために 2024-01-04 から 2024-02-01 に遅らせた(docs/sweep.md 3章)
      { name: "in_sample", start_date: "2024-02-01", end_date: "2025-06-30", requested_start_date: "2024-01-04", skipped_trading_days: 20, first_business_day: "2024-02-01", last_business_day: "2025-06-30", business_days: 340, benchmark: { ...BENCHMARK_FLAT, total_return: 0.25, sharpe_ratio: 0.7, max_drawdown: 0.18, final_equity: 1_250_000, status: "bought" } },
      { name: "out_of_sample", start_date: "2025-07-01", end_date: "2025-12-30", requested_start_date: "2025-07-01", skipped_trading_days: 0, first_business_day: "2025-07-01", last_business_day: "2025-12-30", business_days: 130, benchmark: { ...BENCHMARK_FLAT, total_return: 0.02, sharpe_ratio: 0.15, max_drawdown: 0.09, final_equity: 1_020_000, status: "bought" } },
    ],
    grid: { short_min: 3, short_max: 6, short_step: 3, long_min: 10, long_max: 20, long_step: 10, short_values: [3, 6], long_values: [10, 20] },
    params: { fee_rate_pct: 0.1, slippage_rate_pct: 0.05, fee_rate: 0.001, slippage_rate: 0.0005, initial_cash: 1_000_000, lot_size: 100, trading_days_per_year: 245 },
    count: 4,
    combos,
    rankings: [
      { objective: "sharpe_ratio", order: [3, 1, 0, 2], best_index: 3, best_tie_count: 1, best_out_of_sample_rank: 2, in_sample_ranked: 3, out_of_sample_ranked: 4, rank_correlation: -0.2, correlation_pairs: 3, neighbors_mean: 0.4, neighbors_count: 2, in_sample_beats_benchmark: 1, out_of_sample_beats_benchmark: 2 },
      { objective: "total_return", order: [3, 1, 0, 2], best_index: 3, best_tie_count: 1, best_out_of_sample_rank: 2, in_sample_ranked: 4, out_of_sample_ranked: 4, rank_correlation: 0.2, correlation_pairs: 4, neighbors_mean: 0.06, neighbors_count: 3, in_sample_beats_benchmark: 1, out_of_sample_beats_benchmark: 2 },
      { objective: "max_drawdown", order: [2, 3, 1, 0], best_index: 2, best_tie_count: 1, best_out_of_sample_rank: 1, in_sample_ranked: 4, out_of_sample_ranked: 4, rank_correlation: 0.4, correlation_pairs: 4, neighbors_mean: 0.15, neighbors_count: 3, in_sample_beats_benchmark: 4, out_of_sample_beats_benchmark: 2 },
    ],
    notes: [{ kind: "trials", message: "4通りの組み合わせを試した結果です" }],
    data_info: { source_id: "demo", source_label: "架空データ", license_note: "", fetched_at: null, warning: null },
  };
}

/**
 * ウォークフォワード分析の小さな結果(選ぶ期間12か月・使う期間3か月の区切り2回)。
 * 区切り1は (6,20) を選んで買い持ちを上回り、区切り2は同率2通りの最初 (3,20) を選んで下回った。
 */
export function walkForwardResult(symbolId: string): WalkForwardResult {
  const period = (start: string, end: string, days: number) => ({
    start_date: start,
    end_date: end,
    first_business_day: start,
    last_business_day: end,
    business_days: days,
  });
  const base = sweepResult(symbolId);
  return {
    symbol: base.symbol,
    strategy_id: "ma_cross",
    engine: base.engine,
    grid: base.grid,
    params: base.params,
    objective: "sharpe_ratio",
    in_sample_months: 12,
    out_of_sample_months: 3,
    count: 4,
    runs: 10,
    windows: [
      {
        index: 1,
        requested_in_sample_start: "2024-01-04",
        in_sample: period("2024-02-01", "2025-01-03", 230),
        out_of_sample: period("2025-01-06", "2025-04-03", 60),
        chosen: { short_window: 6, long_window: 20 },
        in_sample_value: 1.1,
        tie_count: 1,
        starting_cash: 1_000_000,
        out_of_sample_metrics: sweepMetrics(0.9, 0.05, 0.04),
        ended_with_shares: true,
        final_equity: 1_050_000,
        liquidated_equity: 1_048_400,
        benchmark_total_return: 0.02,
      },
      {
        index: 2,
        requested_in_sample_start: "2024-04-04",
        in_sample: period("2024-04-04", "2025-04-03", 245),
        out_of_sample: period("2025-04-04", "2025-07-03", 61),
        chosen: { short_window: 3, long_window: 20 },
        in_sample_value: 0.6,
        tie_count: 2,
        starting_cash: 1_048_400,
        out_of_sample_metrics: sweepMetrics(-0.2, -0.01, 0.03),
        ended_with_shares: false,
        final_equity: 1_037_916,
        liquidated_equity: 1_037_916,
        benchmark_total_return: 0.03,
      },
    ],
    daily: [
      { date: "2025-01-06", equity: 1_000_000, benchmark_equity: 1_000_000 },
      { date: "2025-04-03", equity: 1_048_400, benchmark_equity: 1_020_000 },
      { date: "2025-04-04", equity: 1_048_400, benchmark_equity: 1_021_000 },
      { date: "2025-07-03", equity: 1_037_916, benchmark_equity: 1_050_000 },
    ],
    metrics: {
      total_return: 0.037916,
      annualized_return: null,
      max_drawdown: 0.03,
      sharpe_ratio: 0.5,
      return_count: 3,
      final_equity: 1_037_916,
      liquidated_equity: 1_037_916,
    },
    benchmark: {
      label: "買い持ち",
      status: "bought",
      signal_date: "2025-01-06",
      fill: null,
      skipped: null,
      events: [],
      metrics: { ...BENCHMARK_FLAT, total_return: 0.05, sharpe_ratio: 0.8, max_drawdown: 0.05, return_count: 3, final_equity: 1_050_000 },
      open_position_at_end: true,
    },
    choice_changes: 1,
    compared_windows: 2,
    beats_benchmark: 1,
    unused: { start_date: "2025-07-04", end_date: "2025-12-30", business_days: 120 },
    notes: [{ kind: "walkforward_trials", message: "区切りごとに4通りの組み合わせを試して選んでいます" }],
    data_info: base.data_info,
  };
}
