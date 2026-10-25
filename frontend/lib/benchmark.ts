// 比較の基準:買い持ち(docs/benchmark.md)の見せ方。画面の部品から切り離した純粋な関数(lib/benchmark.test.ts)。
// 「売買ルールの結果」と「同じ期間・同じ費用でただ持ち続けた結果」を並べ、どちらが良かったかを数字で書く。

import type { Benchmark, BenchmarkMetrics, Objective } from "./api.ts";
import { formatYen } from "./format.ts";
import { LARGER_IS_BETTER } from "./sweep.ts";

/** 買い持ちが買えなかったときの説明。買えたときは null。 */
export function benchmarkUnavailable(benchmark: Benchmark, lotSize: number): string | null {
  if (benchmark.status === "bought") return null;
  if (benchmark.status === "insufficient_cash" && benchmark.skipped) {
    const needed = benchmark.skipped.fill_price * lotSize;
    return `買い持ちは、初期資金が${lotSize}株分(約${formatYen(needed)})に足りないため買えませんでした`;
  }
  return "買い持ちは、期間の最後まで買える日がありませんでした(最初に売買が成立した日の翌日以降に、売買が成立した日がない)";
}

/**
 * 総リターンの差(ポイント)の言い方。strategy − benchmark を100倍した値を、小数1桁で書く。
 * 例:「買い持ちより 12.3ポイント上」「買い持ちより 4.0ポイント下」「買い持ちとほぼ同じ」
 */
export function returnGap(strategyReturn: number, benchmarkReturn: number): string {
  const points = (strategyReturn - benchmarkReturn) * 100;
  const text = Math.abs(points).toFixed(1);
  if (Number(text) === 0) return "買い持ちとほぼ同じ";
  return `買い持ちより ${text}ポイント${points > 0 ? "上" : "下"}`;
}

/** 買い持ちの、並べる基準の値(算出不可なら null)。 */
export function benchmarkValue(metrics: BenchmarkMetrics, objective: Objective): number | null {
  const value = metrics[objective];
  return value === null || !Number.isFinite(value) ? null : value;
}

/**
 * 値を買い持ちと比べた言い方(「良い」「悪い」「同じ」)。最大ドローダウンは小さいほど良い。
 * どちらかが算出不可なら null。
 */
export function versusBenchmark(value: number | null, benchmark: number | null, objective: Objective): "良い" | "悪い" | "同じ" | null {
  if (value === null || benchmark === null) return null;
  if (value === benchmark) return "同じ";
  return (value > benchmark) === LARGER_IS_BETTER[objective] ? "良い" : "悪い";
}

/** 総当たりの「買い持ちより良かった組み合わせ」の文。数えられないときは null。 */
export function beatsText(count: number | null, total: number): string | null {
  if (count === null) return null;
  const n = new Intl.NumberFormat("ja-JP");
  return `${n.format(total)}通り中 ${n.format(count)}通り`;
}
