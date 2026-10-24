// node --test で動かす(Node.js が TypeScript の型を取り除いて実行する)。
import assert from "node:assert/strict";
import { test } from "node:test";

import { niceScale } from "./chart.ts";
import {
  axisLabels,
  describeYen,
  direction,
  formatDate,
  formatDateLong,
  formatDateTimeJst,
  formatDecimal,
  formatNumber,
  formatPercent,
  formatPrice,
  formatRatePct,
  formatShares,
  formatSignedYen,
  formatYen,
  formatYenCompact,
} from "./format.ts";

test("円の表示", () => {
  assert.equal(formatYen(1790750.434), "1,790,750円");
  assert.equal(formatSignedYen(790750.4), "+790,750円");
  assert.equal(formatSignedYen(-1234.5), "−1,235円");
  assert.equal(formatSignedYen(0.2), "±0円");
});

test("パーセントと算出不可", () => {
  assert.equal(formatPercent(0.790750434, { signed: true }), "+79.08%");
  assert.equal(formatPercent(-0.0123, { signed: true }), "−1.23%");
  assert.equal(formatPercent(0.222211), "22.22%");
  assert.equal(formatPercent(null), "算出不可");
  assert.equal(formatPercent(null, { nullLabel: "−" }), "−");
  assert.equal(formatNumber(-0.4812), "−0.48");
  assert.equal(formatNumber(null), "算出不可");
  // 丸めると0になる負の値に「−」を付けない
  assert.equal(formatPercent(-0.00001), "0.00%");
  assert.equal(formatNumber(-0.001), "0.00");
});

test("株価・株数・率・係数", () => {
  assert.equal(formatPrice(1234.5), "1,234.5");
  assert.equal(formatPrice(97.125), "97.13");
  assert.equal(formatPrice(null), "−");
  assert.equal(formatShares(1200), "1,200株");
  assert.equal(formatRatePct(0.1), "0.1%");
  assert.equal(formatRatePct(0.0000001), "0.0000001%"); // 指数表記(1e-7)にしない
  assert.equal(formatDecimal(0.333333333333), "0.33333333");
  assert.equal(formatDecimal(10), "10");
});

test("軸用の短い円表記", () => {
  assert.equal(formatYenCompact(1_500_000), "150万");
  assert.equal(formatYenCompact(123_456_789), "1.23億");
  assert.equal(formatYenCompact(4200), "4,200");
  assert.equal(formatYenCompact(10_000), "1万");
  assert.equal(describeYen(1_000_000), "100万円");
  // ちょうどでないときは「約」を付ける
  assert.equal(describeYen(1_234_567), "約123万円");
  assert.equal(describeYen(150_000_000), "1.5億円");
  assert.equal(describeYen(9_999), "9,999円");
  assert.equal(describeYen(0), "");
});

test("目盛りの数字は、目盛りの間隔から桁数を決めてそろえる", () => {
  // 取引0回で資産額が100万円のまま:間隔2.5万 → 102.5万を「103万」と書かない
  assert.deepEqual(
    axisLabels([950_000, 975_000, 1_000_000, 1_025_000, 1_050_000], 25_000, "yen"),
    ["95.0万", "97.5万", "100.0万", "102.5万", "105.0万"],
  );
  // 1万円未満の株価:97.5 を「98」と書かない
  assert.deepEqual(axisLabels([95, 97.5, 100, 102.5], 2.5, "yen"), ["95.0", "97.5", "100.0", "102.5"]);
  // 1万をまたぐ株価は「万」にしない(0.75万 より 7,500 のほうが読みやすい)
  assert.deepEqual(axisLabels([5000, 7500, 10000], 2500, "yen"), ["5,000", "7,500", "10,000"]);
  assert.deepEqual(axisLabels([100_000_000, 150_000_000, 200_000_000], 50_000_000, "yen"), ["1.0億", "1.5億", "2.0億"]);
  // ドローダウン:2.5% の線を「−3%」と書かない
  assert.deepEqual(axisLabels([0, 0.025, 0.05], 0.025, "percent"), ["0%", "−2.5%", "−5.0%"]);
  assert.deepEqual(axisLabels([0, 0.1, 0.2], 0.1, "percent"), ["0%", "−10%", "−20%"]);
});

test("niceScale と axisLabels を組み合わせても、目盛りの数字が重ならない", () => {
  for (const [min, max] of [
    [940_000, 1_060_000],
    [96.2, 103.4],
    [0.37, 0.41],
    [3_400, 12_100],
  ]) {
    const { ticks, step } = niceScale(min, max, 5);
    const labels = axisLabels(ticks, step, "yen");
    assert.equal(new Set(labels).size, labels.length, labels.join(" "));
  }
});

test("日付", () => {
  assert.equal(formatDate("2025-04-01"), "2025/04/01");
  assert.equal(formatDateLong("2025-04-01"), "2025年4月1日(火)");
  assert.equal(formatDateLong("2024-02-29"), "2024年2月29日(木)");
  assert.equal(formatDate(null), "−");
});

test("取得日時は日本時間で書く(API は UTC で返す)", () => {
  // UTC の 23時台は、日本時間では次の日
  assert.equal(formatDateTimeJst("2026-10-23T22:30:00Z"), "2026/10/24 07:30");
  assert.equal(formatDateTimeJst("2026-10-23T22:30:00+00:00"), "2026/10/24 07:30");
  assert.equal(formatDateTimeJst("2026-12-31T15:00:00Z"), "2027/01/01 00:00");
  assert.equal(formatDateTimeJst(null), "−");
  assert.equal(formatDateTimeJst("not a date"), "−");
});

test("損益の向き", () => {
  assert.equal(direction(10), "up");
  assert.equal(direction(-1), "down");
  assert.equal(direction(0), "flat");
  assert.equal(direction(null), "flat");
});
