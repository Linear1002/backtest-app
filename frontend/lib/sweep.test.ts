import assert from "node:assert/strict";
import { test } from "node:test";

import type { SweepCombo, SweepGrid, SweepMetrics } from "./api.ts";
import {
  competitionRank,
  correlationReading,
  dayBefore,
  DEFAULT_SWEEP_FORM,
  gridPairs,
  gridValues,
  heatColor,
  heatScaleMax,
  heatTone,
  holdoutStart,
  pairCount,
  parseSweepGrid,
  segmentValues,
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
  };
}

function combo(is: SweepMetrics, oos: SweepMetrics | null): SweepCombo {
  return { short_window: 1, long_window: 2, in_sample: is, out_of_sample: oos };
}

test("ヒートマップの色:0 を中心に、プラスは朱・マイナスは藍。同じ物差しを選ぶ期間と検証期間で使う", () => {
  const combos = [combo(metrics(0.5), metrics(-2)), combo(metrics(1), metrics(null))];
  // 物差しは両方の期間の絶対値の最大(2)
  assert.equal(heatScaleMax(combos, "sharpe_ratio"), 2);
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

test("順位相関の読み方(目安)", () => {
  assert.match(correlationReading(0.8), /ある程度そろっています/);
  assert.match(correlationReading(0.3), /弱い関係/);
  assert.match(correlationReading(0.05), /ほとんど関係がありません/);
  assert.match(correlationReading(-0.4), /逆の関係/);
  assert.match(correlationReading(null), /足りない/);
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
