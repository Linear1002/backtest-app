import assert from "node:assert/strict";
import { test } from "node:test";

import type { Benchmark } from "./api.ts";
import { beatsText, benchmarkUnavailable, benchmarkValue, returnGap, versusBenchmark } from "./benchmark.ts";

const METRICS = { total_return: 0.2, annualized_return: 0.1, max_drawdown: 0.15, sharpe_ratio: null, return_count: 100, final_equity: 1_200_000 };

function benchmark(status: Benchmark["status"], skipped: Benchmark["skipped"] = null): Benchmark {
  return { label: "買い持ち", status, signal_date: null, fill: null, skipped, events: [], metrics: METRICS, open_position_at_end: false };
}

test("買い持ちを買えなかったときの説明", () => {
  assert.equal(benchmarkUnavailable(benchmark("bought"), 100), null);
  const skipped = { date: "2025-01-07", signal_date: "2025-01-06", open_price: 10_650, fill_price: 10_655.325, cash: 1_000_000 };
  assert.equal(
    benchmarkUnavailable(benchmark("insufficient_cash", skipped), 100),
    "買い持ちは、初期資金が100株分(約1,065,533円)に足りないため買えませんでした",
  );
  assert.match(benchmarkUnavailable(benchmark("not_bought"), 100) ?? "", /買える日がありませんでした/);
});

test("総リターンの差は、ポイントで上・下を書く", () => {
  assert.equal(returnGap(0.32, 0.2), "買い持ちより 12.0ポイント上");
  assert.equal(returnGap(-0.05, 0.2), "買い持ちより 25.0ポイント下");
  assert.equal(returnGap(0.2004, 0.2), "買い持ちとほぼ同じ"); // 0.04ポイントは小数1桁で 0.0
});

test("並べる基準の値と、買い持ちより良かった数", () => {
  assert.equal(benchmarkValue(METRICS, "total_return"), 0.2);
  assert.equal(benchmarkValue(METRICS, "sharpe_ratio"), null);
  assert.equal(beatsText(12, 105), "105通り中 12通り");
  assert.equal(beatsText(null, 105), null);
});

test("買い持ちと比べた言い方(最大ドローダウンは小さいほど良い)", () => {
  assert.equal(versusBenchmark(0.83, 1.25, "sharpe_ratio"), "悪い");
  assert.equal(versusBenchmark(0.3, 0.2, "total_return"), "良い");
  assert.equal(versusBenchmark(0.1, 0.4, "max_drawdown"), "良い");
  assert.equal(versusBenchmark(0.5, 0.5, "sharpe_ratio"), "同じ");
  assert.equal(versusBenchmark(null, 0.5, "sharpe_ratio"), null);
});
