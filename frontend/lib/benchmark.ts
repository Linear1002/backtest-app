// 比較の基準:買い持ち(docs/benchmark.md)の見せ方。画面の部品から切り離した純粋な関数(lib/benchmark.test.ts)。
// 「売買ルールの結果」と「同じ期間・同じ費用でただ持ち続けた結果」を並べ、どちらが良かったかを数字で書く。
// 買い持ちを買えなかったとき(資金不足・買う日がない)は、比べない(値は初期資金のままで、現金と比べることになるため)。

import type { Benchmark, BenchmarkStatus, Objective, SegmentBenchmark } from "./api.ts";
import { formatNumber, formatPercent, formatYen } from "./format.ts";
import { LARGER_IS_BETTER } from "./sweep.ts";

/**
 * 買い持ちが買えなかったときの説明。買えたときは null。
 * 資金不足の必要額は、エンジンの株数の決め方(docs/mvp.md 2.7)と同じく手数料を含めた 約定価格 × (1 + 手数料率) × 売買単位。
 */
export function benchmarkUnavailable(benchmark: Benchmark, lotSize: number, feeRate: number): string | null {
  if (benchmark.status === "bought") return null;
  if (benchmark.status === "insufficient_cash" && benchmark.skipped) {
    const needed = benchmark.skipped.fill_price * (1 + feeRate) * lotSize;
    return `買い持ちは、初期資金が${lotSize}株分(手数料込みで約${formatYen(needed)})に足りないため買えませんでした`;
  }
  if (benchmark.signal_date === null) return "期間に売買が成立した日が1日もないため、買い持ちは計算していません";
  return "買い持ちは、期間の最後まで買える日がありませんでした(最初に売買が成立した日の翌日以降に、売買が成立した日がない)";
}

/** 総当たりの期間ごとの買い持ちを買えなかったときの短い説明。買えたときは null。 */
export function segmentBenchmarkUnavailable(status: BenchmarkStatus): string | null {
  if (status === "bought") return null;
  return status === "insufficient_cash" ? "資金不足で買えず" : "買う日がなく買えず";
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

/** 総当たりの期間の買い持ちの、並べる基準の値。買えなかった・算出不可なら null(比べない)。 */
export function benchmarkValue(benchmark: SegmentBenchmark, objective: Objective): number | null {
  if (benchmark.status !== "bought") return null;
  const value = benchmark[objective];
  return value === null || !Number.isFinite(value) ? null : value;
}

/** 画面に出す桁(シャープレシオは小数2桁、総リターン・最大ドローダウンは % の小数2桁)に丸めた値。 */
function shown(value: number, objective: Objective): string {
  return objective === "sharpe_ratio" ? formatNumber(value) : formatPercent(value);
}

/**
 * 値を買い持ちと比べた言い方(「良い」「悪い」「同じ」)。最大ドローダウンは小さいほど良い。
 * 画面に出す桁で同じなら「同じ」(表示が同じなのに「良い」と出さない)。どちらかが算出不可なら null。
 */
export function versusBenchmark(value: number | null, benchmark: number | null, objective: Objective): "良い" | "悪い" | "同じ" | null {
  if (value === null || benchmark === null) return null;
  if (shown(value, objective) === shown(benchmark, objective)) return "同じ";
  return (value > benchmark) === LARGER_IS_BETTER[objective] ? "良い" : "悪い";
}

/** 「同じ期間の買い持ち(1.25)より悪い」「…と同じ」。比べられないときは null。 */
export function versusText(value: number | null, benchmark: number | null, objective: Objective, label: string): string | null {
  const verdict = versusBenchmark(value, benchmark, objective);
  if (verdict === null || benchmark === null) return null;
  const head = `同じ期間の買い持ち(${label})`;
  return verdict === "同じ" ? `${head}と同じ` : `${head}より${verdict}`;
}

/** 総当たりの「買い持ちより良かった組み合わせ」の文。数えられないときは null。 */
export function beatsText(count: number | null, total: number): string | null {
  if (count === null) return null;
  const n = new Intl.NumberFormat("ja-JP");
  return `${n.format(total)}通り中 ${n.format(count)}通り`;
}
