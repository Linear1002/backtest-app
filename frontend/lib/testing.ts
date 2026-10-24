// テスト用の小さなデータ(画面のテストだけで使う。アプリからは import しない)。

import { readFileSync } from "node:fs";

import type { BacktestResult, Meta, ParamSpec, Strategy, SymbolDetail, SymbolSummary } from "./api.ts";

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
    corporate_actions: [],
    data_info: { source_id: "demo", source_label: "架空データ", license_note: "", fetched_at: null, warning: null },
    elapsed_ms: 1,
  };
}
