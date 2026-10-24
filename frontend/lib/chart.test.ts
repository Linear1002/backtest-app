import assert from "node:assert/strict";
import { test } from "node:test";

import { areaPath, dateTicks, linearScale, linePath, nearestIndex, niceScale, paddedExtent } from "./chart.ts";

/** 平日だけの日付の並び(祝日は考えない)。 */
function weekdays(fromIso: string, count: number): string[] {
  const days: string[] = [];
  const [y, m, d] = fromIso.split("-").map(Number);
  for (let t = Date.UTC(y, m - 1, d); days.length < count; t += 86_400_000) {
    const day = new Date(t);
    if (day.getUTCDay() !== 0 && day.getUTCDay() !== 6) days.push(day.toISOString().slice(0, 10));
  }
  return days;
}

test("線形スケールと逆変換", () => {
  const s = linearScale([0, 100], [0, 500]);
  assert.equal(s(50), 250);
  assert.equal(s.invert(250), 50);
  assert.equal(nearestIndex(s, 251, 101), 50);
  assert.equal(nearestIndex(s, -40, 101), 0);
  assert.equal(nearestIndex(s, 9999, 101), 100);
});

const ticks = (min: number, max: number, count?: number) => niceScale(min, max, count).ticks;

test("きりのいい目盛り", () => {
  assert.deepEqual(ticks(0, 100, 5), [0, 20, 40, 60, 80, 100]);
  assert.deepEqual(ticks(3400, 12100, 4), [5000, 7500, 10000]);
  assert.deepEqual(ticks(0.95, 1.85, 4), [1, 1.25, 1.5, 1.75]);
  assert.ok(ticks(5, 5).length > 0);
  assert.deepEqual(ticks(100, 0, 5), [0, 20, 40, 60, 80, 100]); // 大小が逆でもよい
  assert.deepEqual(niceScale(940_000, 1_060_000, 5), { ticks: [950_000, 975_000, 1_000_000, 1_025_000, 1_050_000], step: 25_000 });
  assert.deepEqual(niceScale(Number.NaN, 1), { ticks: [], step: 0 });
});

test("ほぼ同じ2つの値(1 ulp 違い)でも、目盛りの計算が終わり、数が限られる", () => {
  for (const [min, max] of [
    [1000, 1000 + 2 ** -43],
    [0.1, 0.1 + Number.EPSILON / 8],
    [-5, -5 + 1e-15],
    [1e9, 1e9 + 1e-6],
  ]) {
    const { ticks: t, step } = niceScale(min, max, 5);
    assert.ok(t.length > 0 && t.length <= 50, `${min}〜${max}: ${t.length}本`);
    assert.ok(step > 0 && min + step !== min, `${min}〜${max}: 間隔 ${step}`);
  }
  const [lo, hi] = paddedExtent([1000, 1000 + 2 ** -43]);
  assert.ok(hi - lo > 1, `${lo}〜${hi}`);
});

test("余白つきの範囲", () => {
  const [lo, hi] = paddedExtent([10, 20, Number.NaN]);
  assert.ok(lo < 10 && hi > 20);
  assert.deepEqual(paddedExtent([]), [0, 1]);
  // 全部同じ値でも幅のある範囲になる(0 で割らない)
  const [a, b] = paddedExtent([1_000_000, 1_000_000]);
  assert.ok(a < 1_000_000 && b > 1_000_000);
  const [z0, z1] = paddedExtent([0, 0]);
  assert.ok(z0 < 0 && z1 > 0);
});

test("null で線を切る", () => {
  assert.equal(linePath([[0, 0], [1, 1], null, [3, 3], [4, 4]]), "M0,0L1,1M3,3L4,4");
  assert.equal(areaPath([[0, 5], [10, 2]], 8), "M0,5L10,2L10,8L0,8Z");
});

test("前後が null の1点は、長さ0の線(点)として残す", () => {
  assert.equal(linePath([null, [1, 1], null]), "M1,1h0");
  assert.equal(linePath([[0, 0], null, [2, 2], null, [4, 4], [5, 5]]), "M0,0h0M2,2h0M4,4L5,5");
  assert.equal(linePath([null, null]), "");
  assert.equal(linePath([]), "");
});

test("日付の目盛り:長い期間は年、短い期間は月", () => {
  const days: string[] = [];
  const start = Date.UTC(2022, 0, 4);
  for (let i = 0; i < 1600; i += 1) {
    const d = new Date(start + i * 86_400_000);
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) days.push(d.toISOString().slice(0, 10));
  }
  const long = dateTicks(days, 6);
  assert.ok(long.every((t) => t.label.endsWith("年")));
  const short = dateTicks(days.slice(0, 120), 8);
  assert.ok(short.some((t) => t.label === "2月"));
});

test("日付の目盛り:1か月ほどの短い期間でも目盛りが出る", () => {
  const month = weekdays("2025-04-01", 20); // 4/1〜4/28
  const ticks = dateTicks(month, 8);
  assert.ok(ticks.length >= 2, JSON.stringify(ticks));
  assert.ok(ticks.every((t) => /^\d+\/\d+$/.test(t.label)));
  assert.ok(ticks.every((t) => t.index > 0 && t.index < month.length - 1));
  // 月をまたいでも月の始まりが1つだけなら、日付の目盛りにする
  assert.ok(dateTicks(weekdays("2025-04-21", 15), 8).every((t) => t.label.includes("/")));
  assert.deepEqual(dateTicks(["2025-04-01"], 8), []);
});

test("日付の目盛り:年の数が多すぎるときは何年かおき", () => {
  const long = weekdays("2001-01-02", 260 * 20); // 約20年
  const ticks = dateTicks(long, 6);
  assert.ok(ticks.length > 0 && ticks.length <= 6, JSON.stringify(ticks));
  assert.ok(ticks.every((t) => t.label.endsWith("年") && t.major));
});
