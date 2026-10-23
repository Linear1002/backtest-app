import assert from "node:assert/strict";
import { test } from "node:test";

import { areaPath, dateTicks, linearScale, linePath, nearestIndex, niceTicks, paddedExtent } from "./chart.ts";

test("線形スケールと逆変換", () => {
  const s = linearScale([0, 100], [0, 500]);
  assert.equal(s(50), 250);
  assert.equal(s.invert(250), 50);
  assert.equal(nearestIndex(s, 251, 101), 50);
  assert.equal(nearestIndex(s, -40, 101), 0);
  assert.equal(nearestIndex(s, 9999, 101), 100);
});

test("きりのいい目盛り", () => {
  assert.deepEqual(niceTicks(0, 100, 5), [0, 20, 40, 60, 80, 100]);
  assert.deepEqual(niceTicks(3400, 12100, 4), [5000, 7500, 10000]);
  assert.deepEqual(niceTicks(0.95, 1.85, 4), [1, 1.25, 1.5, 1.75]);
  assert.ok(niceTicks(5, 5).length > 0);
});

test("余白つきの範囲", () => {
  const [lo, hi] = paddedExtent([10, 20, Number.NaN]);
  assert.ok(lo < 10 && hi > 20);
  assert.deepEqual(paddedExtent([]), [0, 1]);
});

test("null で線を切る", () => {
  assert.equal(linePath([[0, 0], [1, 1], null, [3, 3]]), "M0,0L1,1M3,3");
  assert.equal(areaPath([[0, 5], [10, 2]], 8), "M0,5L10,2L10,8L0,8Z");
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
