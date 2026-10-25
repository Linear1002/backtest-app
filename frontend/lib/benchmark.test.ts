import assert from "node:assert/strict";
import { test } from "node:test";

import type { Benchmark, SegmentBenchmark } from "./api.ts";
import {
  beatsText,
  benchmarkUnavailable,
  benchmarkValue,
  returnGap,
  segmentBenchmarkUnavailable,
  versusBenchmark,
  versusText,
} from "./benchmark.ts";

const METRICS = { total_return: 0.2, annualized_return: 0.1, max_drawdown: 0.15, sharpe_ratio: null, return_count: 100, final_equity: 1_200_000 };

function benchmark(status: Benchmark["status"], skipped: Benchmark["skipped"] = null, signalDate: string | null = "2025-01-06"): Benchmark {
  return { label: "買い持ち", status, signal_date: signalDate, fill: null, skipped, events: [], metrics: METRICS, open_position_at_end: false };
}

function segment(status: SegmentBenchmark["status"] = "bought"): SegmentBenchmark {
  return { ...METRICS, status, open_position_at_end: true };
}

test("買い持ちを買えなかったときの説明(必要額は手数料込み。エンジンの株数の決め方と同じ)", () => {
  assert.equal(benchmarkUnavailable(benchmark("bought"), 100, 0.001), null);
  // 約定価格 10,000円・手数料0.1%:100株で 10,000 × 1.001 × 100 = 1,001,000円 > 100万円 なので買えない
  // (手数料を入れないと 1,000,000円で「足りている」ように見えてしまう)
  const skipped = { date: "2025-01-07", signal_date: "2025-01-06", open_price: 9_995, fill_price: 10_000, cash: 1_000_000 };
  assert.equal(
    benchmarkUnavailable(benchmark("insufficient_cash", skipped), 100, 0.001),
    "買い持ちは、初期資金が100株分(手数料込みで約1,001,000円)に足りないため買えませんでした",
  );
  assert.match(benchmarkUnavailable(benchmark("not_bought"), 100, 0.001) ?? "", /買える日がありませんでした/);
  assert.equal(
    benchmarkUnavailable(benchmark("not_bought", null, null), 100, 0.001),
    "期間に売買が成立した日が1日もないため、買い持ちは計算していません",
  );
  assert.equal(segmentBenchmarkUnavailable("bought"), null);
  assert.equal(segmentBenchmarkUnavailable("insufficient_cash"), "資金不足で買えず");
});

test("総リターンの差は、ポイントで上・下を書く", () => {
  assert.equal(returnGap(0.32, 0.2), "買い持ちより 12.0ポイント上");
  assert.equal(returnGap(-0.05, 0.2), "買い持ちより 25.0ポイント下");
  assert.equal(returnGap(0.2004, 0.2), "買い持ちとほぼ同じ"); // 0.04ポイントは小数1桁で 0.0
});

test("総当たりの期間の買い持ちの値:買えなかった期間とは比べない", () => {
  assert.equal(benchmarkValue(segment(), "total_return"), 0.2);
  assert.equal(benchmarkValue(segment(), "sharpe_ratio"), null); // 算出不可
  assert.equal(benchmarkValue(segment("insufficient_cash"), "total_return"), null);
  assert.equal(beatsText(12, 105), "105通り中 12通り");
  assert.equal(beatsText(null, 105), null);
});

test("買い持ちと比べた言い方(最大ドローダウンは小さいほど良い。画面の桁で同じなら「同じ」)", () => {
  assert.equal(versusBenchmark(0.83, 1.25, "sharpe_ratio"), "悪い");
  assert.equal(versusBenchmark(0.3, 0.2, "total_return"), "良い");
  assert.equal(versusBenchmark(0.1, 0.4, "max_drawdown"), "良い");
  assert.equal(versusBenchmark(0.5, 0.5, "sharpe_ratio"), "同じ");
  assert.equal(versusBenchmark(1.2501, 1.2499, "sharpe_ratio"), "同じ"); // どちらも「1.25」と出る
  assert.equal(versusBenchmark(null, 0.5, "sharpe_ratio"), null);
  assert.equal(versusText(0.83, 1.25, "sharpe_ratio", "1.25"), "同じ期間の買い持ち(1.25)より悪い");
  assert.equal(versusText(0, 0, "max_drawdown", "0.00%"), "同じ期間の買い持ち(0.00%)と同じ");
  assert.equal(versusText(0.83, null, "sharpe_ratio", "−"), null);
});
