// node --test で動かす(Node.js が TypeScript の型を取り除いて実行する)。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  describeYen,
  direction,
  formatDate,
  formatDateLong,
  formatNumber,
  formatPercent,
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
});

test("軸用の短い円表記", () => {
  assert.equal(formatYenCompact(1_500_000), "150万");
  assert.equal(formatYenCompact(123_456_789), "1.23億");
  assert.equal(formatYenCompact(4200), "4,200");
  assert.equal(formatYenCompact(10_000), "1万");
  assert.equal(describeYen(1_000_000), "100万円");
});

test("日付", () => {
  assert.equal(formatDate("2025-04-01"), "2025/04/01");
  assert.equal(formatDateLong("2025-04-01"), "2025年4月1日(火)");
  assert.equal(formatDate(null), "−");
});

test("損益の向き", () => {
  assert.equal(direction(10), "up");
  assert.equal(direction(-1), "down");
  assert.equal(direction(0), "flat");
  assert.equal(direction(null), "flat");
});
