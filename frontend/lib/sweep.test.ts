import assert from "node:assert/strict";
import { test } from "node:test";

import type { SweepCombo, SweepGrid, SweepMetrics, SweepRanking } from "./api.ts";
import {
  competitionRank,
  correlationReading,
  dayBefore,
  DEFAULT_SWEEP_FORM,
  exceedsScale,
  gridPairs,
  gridValues,
  heatColor,
  heatScaleMax,
  heatTone,
  holdoutStart,
  isCalendarDate,
  longestWindow,
  MIN_CORRELATION_PAIRS,
  pairCount,
  parseSweepGrid,
  segmentValues,
  sharpeStandardError,
  uniqueBest,
  validateHoldout,
  type SweepErrors,
  type SweepForm,
} from "./sweep.ts";
import { fixture } from "./testing.ts";

type SweepCase = {
  grid: Partial<Record<keyof SweepGrid, string>>;
  errors: SweepErrors;
  pairs: number | null;
  frontend_only: boolean;
};

// 格子の入力 → メッセージ・組み合わせの数 の表。API のテスト(tests/python/test_param_contract.py)も同じ表を読む
const SWEEPS = fixture<{ max_pairs: number; cases: SweepCase[] }>("sweep_messages.json");

test("格子のメッセージと組み合わせの数:API と同じ表で確かめる", () => {
  assert.ok(SWEEPS.cases.length >= 15);
  for (const c of SWEEPS.cases) {
    const form: SweepForm = { ...DEFAULT_SWEEP_FORM, ...c.grid };
    const { errors, pairs, grid } = parseSweepGrid(form, SWEEPS.max_pairs);
    const label = JSON.stringify(c.grid);
    assert.deepEqual(errors, c.errors, label);
    if (Object.keys(c.errors).length === 0) {
      assert.equal(pairs, c.pairs, label);
      assert.ok(grid, label);
      assert.equal(gridPairs(grid).length, c.pairs, label);
    } else {
      assert.equal(grid, null, label);
    }
  }
});

test("組み合わせは短期 < 長期 だけ、短期の小さい順 → 長期の小さい順(docs/sweep.md 2章)", () => {
  const grid = { short_min: 5, short_max: 20, short_step: 5, long_min: 10, long_max: 40, long_step: 10 };
  assert.deepEqual(gridValues(2, 7, 2), [2, 4, 6]);
  assert.deepEqual(gridPairs(grid), [
    [5, 10], [5, 20], [5, 30], [5, 40],
    [10, 20], [10, 30], [10, 40],
    [15, 20], [15, 30], [15, 40],
    [20, 30], [20, 40],
  ]); // prettier-ignore
  assert.equal(pairCount(grid), 12);
  // 上限を確かめないとき(エンジンの一覧がまだない)は、多くても誤りにしない
  const big = { ...DEFAULT_SWEEP_FORM, short_min: "1", short_max: "100", short_step: "1", long_min: "2", long_max: "200", long_step: "1" };
  assert.deepEqual(parseSweepGrid(big, null).errors, {});
  assert.equal(parseSweepGrid(big, null).pairs, 14_950);
});

test("組み合わせの数は、一覧を作って数えた数と同じ(式で数える)", () => {
  for (const [smin, smax, sstep, lmin, lmax, lstep] of [
    [1, 30, 1, 2, 60, 1],
    [3, 30, 3, 20, 120, 10],
    [5, 50, 7, 1, 40, 3],
    [10, 20, 5, 5, 10, 5],
    [1, 1000, 1, 1, 1000, 1],
    [7, 7, 1, 7, 7, 1],
    [2, 9, 4, 3, 11, 2],
  ]) {
    const grid = { short_min: smin, short_max: smax, short_step: sstep, long_min: lmin, long_max: lmax, long_step: lstep };
    assert.equal(pairCount(grid), gridPairs(grid).length, JSON.stringify(grid));
  }
  // いちばん長い長期日数(選ぶ期間の始まりをそろえる日数):刻みに乗る最大
  assert.equal(longestWindow({ short_min: 3, short_max: 30, short_step: 3, long_min: 20, long_max: 125, long_step: 10 }), 120);
});

test("検証期間の開始日の決め方", () => {
  const period = { start_date: "2022-01-04", end_date: "2026-07-31" };
  assert.equal(holdoutStart(period, "none", ""), null);
  assert.equal(holdoutStart(period, "custom", "2025-08-01"), "2025-08-01");
  assert.equal(holdoutStart(period, "last1y", ""), "2025-08-01");
  // 1,669日の最後の3割:開始日から round(1669 × 0.7) = 1168 日後。最後の2割:round(1669 × 0.8) = 1335 日後
  assert.equal(holdoutStart(period, "last30", ""), "2025-03-17");
  assert.equal(holdoutStart(period, "last20", ""), "2025-08-31");
  // うるう日の1年前は、その月の末日にそろえてから1日足す
  assert.equal(holdoutStart({ start_date: "2020-01-06", end_date: "2024-02-29" }, "last1y", ""), "2023-03-01");
  // 期間の日付がまだ正しくないときは決めない(期間の欄のほうで誤りを出す)
  assert.equal(holdoutStart({ start_date: "", end_date: "2026-07-31" }, "last30", ""), null);
  assert.equal(dayBefore("2025-03-01"), "2025-02-28");
});

test("検証期間の開始日のチェック(営業日の数は API だけが確かめる)", () => {
  const period = { start_date: "2022-01-04", end_date: "2026-07-31" };
  assert.equal(validateHoldout(period, null), null);
  assert.equal(validateHoldout(period, "2025-08-01"), null);
  assert.equal(validateHoldout(period, "2026-07-31"), null); // 終了日そのものはよい
  for (const bad of ["2022-01-04", "2021-12-31", "2026-08-01"]) {
    assert.equal(validateHoldout(period, bad), "検証期間の開始日は、期間の開始日より後、終了日以前の日付にしてください", bad);
  }
  assert.equal(validateHoldout(period, ""), "日付は YYYY-MM-DD の形で入力してください");
});

type HoldoutCase = { holdout: string; message: string | null; only: "api" | "frontend" | null };

// 検証期間の開始日 → メッセージ の表。API のテスト(tests/python/test_api_sweeps.py)も同じ表を読む
const HOLDOUTS = fixture<{ period: { start_date: string; end_date: string }; cases: HoldoutCase[] }>("holdout_messages.json");

test("検証期間の開始日のメッセージ:API と同じ表で確かめる(営業日の数は API だけ)", () => {
  assert.ok(HOLDOUTS.cases.length >= 10);
  for (const c of HOLDOUTS.cases) {
    if (c.only === "api") continue;
    assert.equal(validateHoldout(HOLDOUTS.period, c.holdout), c.message, c.holdout || "(空欄)");
  }
  assert.ok(isCalendarDate("2024-02-29"));
  assert.ok(!isCalendarDate("2025-02-29"));
  assert.ok(!isCalendarDate("2025-2-1"));
});

function metrics(sharpe: number | null, total = 0, drawdown = 0.1): SweepMetrics {
  return {
    total_return: total,
    annualized_return: null,
    max_drawdown: drawdown,
    sharpe_ratio: sharpe,
    win_rate: null,
    trade_count: 0,
    winning_trades: 0,
    return_count: 10,
    insufficient_cash_count: 0,
    final_equity: 1,
    holding_days: 5,
  };
}

function combo(is: SweepMetrics, oos: SweepMetrics | null): SweepCombo {
  return { short_window: 1, long_window: 2, in_sample: is, out_of_sample: oos };
}

test("ヒートマップの色:0 を中心に、プラスは朱・マイナスは藍。物差しは選ぶ期間の値だけで決める", () => {
  const combos = [combo(metrics(0.5), metrics(-2)), combo(metrics(-1), metrics(null))];
  // 物差しは選ぶ期間の絶対値の最大(1)。検証期間の -2 は物差しに入れない(検証期間の情報を選ぶ画面に入れないため)
  assert.equal(heatScaleMax(combos, "sharpe_ratio"), 1);
  assert.ok(exceedsScale(combos, "sharpe_ratio", 1)); // 検証期間の -2 は端の色にそろえる
  assert.ok(!exceedsScale(combos, "sharpe_ratio", 2));
  assert.deepEqual(heatTone(1, "sharpe_ratio", 2), { kind: "up", strength: 0.5 });
  assert.deepEqual(heatTone(-2, "sharpe_ratio", 2), { kind: "down", strength: 1 });
  assert.deepEqual(heatTone(-5, "sharpe_ratio", 2), { kind: "down", strength: 1 }); // はみ出しは最大にそろえる
  assert.deepEqual(heatTone(0, "sharpe_ratio", 2), { kind: "up", strength: 0 });
  assert.deepEqual(heatTone(null, "sharpe_ratio", 2), { kind: "none" });
  // 最大ドローダウンは、大きいほど濃い藍(片側だけの物差し)
  assert.deepEqual(heatTone(0.05, "max_drawdown", 0.1), { kind: "down", strength: 0.5 });
  // 値がない・すべて0のときの物差しは1(0で割らない)
  assert.equal(heatScaleMax([combo(metrics(null), null)], "sharpe_ratio"), 1);

  assert.equal(heatColor({ kind: "none" }), "var(--surface)");
  assert.equal(heatColor({ kind: "up", strength: 0 }), "color-mix(in oklab, var(--shu) 0%, var(--heat-mid))");
  assert.equal(heatColor({ kind: "up", strength: 1 }), "color-mix(in oklab, var(--shu) 100%, var(--heat-mid))");
  // 弱い値でも、中立のグレーと見分けられるように少し底上げする
  assert.equal(heatColor({ kind: "down", strength: 0.01 }), "color-mix(in oklab, var(--ai) 13%, var(--heat-mid))");
});

test("順位相関の読み方(目安):組み合わせが少ないときは目安を出さない", () => {
  const n = MIN_CORRELATION_PAIRS;
  assert.match(correlationReading(0.8, n), /^目安:ある程度そろっています/);
  assert.match(correlationReading(0.3, n), /弱い関係/);
  assert.match(correlationReading(0.05, 105), /ほとんど関係がありません/);
  assert.match(correlationReading(-0.4, 105), /逆の関係/);
  assert.match(correlationReading(0.9, n - 1), /少ないため、読み方の目安は出しません/);
  assert.match(correlationReading(null, 2), /3つ未満/);
  assert.match(correlationReading(null, 50), /すべての組み合わせが同じ値/);
});

test("シャープレシオの偶然の幅の目安(API の注記と同じ式)と、同率1位", () => {
  assert.equal(sharpeStandardError(246, 245), 1); // 1年分(日次リターン245個)なら ±1
  assert.ok(Math.abs(sharpeStandardError(148, 245) - Math.sqrt(245 / 147)) < 1e-12);
  const ranking: SweepRanking = {
    objective: "sharpe_ratio",
    order: [2, 0, 1],
    best_index: 2,
    best_tie_count: 1,
    best_out_of_sample_rank: null,
    in_sample_ranked: 3,
    out_of_sample_ranked: 3,
    rank_correlation: null,
    correlation_pairs: 3,
    neighbors_mean: null,
    neighbors_count: 0,
  };
  assert.equal(uniqueBest(ranking), 2);
  assert.equal(uniqueBest({ ...ranking, best_tie_count: 2 }), null); // 同率1位は1つに決めない
});

test("期間ごとの値と順位(同じ値は同じ順位。値がなければ順位なし)", () => {
  const combos = [combo(metrics(0.5), metrics(0.1)), combo(metrics(1), metrics(null)), combo(metrics(0.5), metrics(0.3))];
  assert.deepEqual(segmentValues(combos, "in_sample", "sharpe_ratio"), [0.5, 1, 0.5]);
  assert.deepEqual(segmentValues(combos, "out_of_sample", "sharpe_ratio"), [0.1, null, 0.3]);
  const is = segmentValues(combos, "in_sample", "sharpe_ratio");
  assert.deepEqual([0, 1, 2].map((i) => competitionRank(is, i, "sharpe_ratio")), [2, 1, 2]);
  const oos = segmentValues(combos, "out_of_sample", "sharpe_ratio");
  assert.deepEqual([0, 1, 2].map((i) => competitionRank(oos, i, "sharpe_ratio")), [2, null, 1]);
  // 最大ドローダウンは小さいほどよい
  const dd = [0.3, 0.1, 0.2];
  assert.deepEqual([0, 1, 2].map((i) => competitionRank(dd, i, "max_drawdown")), [3, 1, 2]);
});
