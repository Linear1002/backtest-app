import assert from "node:assert/strict";
import { test } from "node:test";

import { fixture } from "./testing.ts";
import {
  addMonths,
  calendarWindows,
  DEFAULT_WALKFORWARD_FORM,
  maxRuns,
  monthsText,
  runCounts,
  settingsErrors,
  validateWalkForward,
  type WalkForwardForm,
  windowVersus,
} from "./walkforward.ts";

type WindowCase = {
  name: string;
  start: string;
  end: string;
  in_sample_months: number;
  out_of_sample_months: number;
  windows: [string, string, string, string][];
};

// Python(tests/python/test_reference_walkforward.py)と同じ表
const WINDOWS = fixture<{ cases: WindowCase[] }>("walkforward_windows.json");

for (const c of WINDOWS.cases) {
  test(`区切り:${c.name}`, () => {
    const windows = calendarWindows(c.start, c.end, c.in_sample_months, c.out_of_sample_months);
    assert.deepEqual(
      windows.map((w) => [w.inSampleStart, w.inSampleEnd, w.outOfSampleStart, w.outOfSampleEnd]),
      c.windows,
    );
    assert.deepEqual(
      windows.map((w) => w.index),
      c.windows.map((_, i) => i + 1),
    );
  });
}

test("月を足す:その月にない日は月末にする(うるう年も)", () => {
  assert.equal(addMonths("2023-01-31", 1), "2023-02-28");
  assert.equal(addMonths("2024-01-31", 1), "2024-02-29");
  assert.equal(addMonths("2024-02-29", 12), "2025-02-28");
  assert.equal(addMonths("2023-11-30", 3), "2024-02-29");
  assert.equal(addMonths("2023-12-15", 1), "2024-01-15");
  assert.equal(addMonths("2023-05-31", 0), "2023-05-31");
});

test("区切りはすき間も重なりもなく続き、選ぶ期間は使う期間の前日に終わる", () => {
  const windows = calendarWindows("2020-03-31", "2026-12-31", 18, 3);
  assert.ok(windows.length > 10);
  const dayAfter = (iso: string) => new Date(Date.parse(`${iso}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
  for (const [i, w] of windows.entries()) {
    assert.equal(dayAfter(w.inSampleEnd), w.outOfSampleStart);
    const next = windows[i + 1];
    if (next) assert.equal(next.outOfSampleStart, dayAfter(w.outOfSampleEnd));
  }
});

type MessageCase = {
  name: string;
  walk: Partial<WalkForwardForm>;
  start: string;
  end: string;
  pairs: number;
  errors: Record<string, string>;
  windows: number | null;
};

// API(tests/python/test_param_contract.py)と同じ表
const MESSAGES = fixture<{ max_runs: number; cases: MessageCase[] }>("walkforward_messages.json");

test("計算の量の上限は、総当たりの組み合わせの上限の2倍", () => {
  assert.equal(maxRuns(2000), MESSAGES.max_runs);
});

for (const c of MESSAGES.cases) {
  test(`入力チェック:${c.name}`, () => {
    const form = { ...DEFAULT_WALKFORWARD_FORM, ...c.walk };
    const settings = settingsErrors(form);
    if (Object.keys(settings).length > 0) {
      assert.equal(c.windows, null);
      assert.deepEqual(settings, c.errors);
      return;
    }
    const { windows, errors } = validateWalkForward(form, { start_date: c.start, end_date: c.end }, c.pairs, MESSAGES.max_runs);
    assert.equal(windows.length, c.windows);
    assert.deepEqual(errors, c.errors);
  });
}

test("上限が分からない(エンジンの一覧がまだない)ときは、計算の量を確かめない", () => {
  const { errors } = validateWalkForward(DEFAULT_WALKFORWARD_FORM, { start_date: "2022-01-04", end_date: "2026-07-31" }, 100_000, null);
  assert.deepEqual(errors, {});
});

test("長さの読み方:12の倍数は年で書く", () => {
  assert.equal(monthsText(24), "2年");
  assert.equal(monthsText(6), "6か月");
  assert.equal(monthsText(18), "18か月");
});

test("区切りの買い持ちとの比較は丸めずに比べる(API の beats_benchmark と同じ)", () => {
  // どちらも表示は +1.23% だが、上回っている
  assert.equal(windowVersus(0.012341, 0.012339), "上回った");
  assert.equal(windowVersus(0.012339, 0.012341), "下回った");
  assert.equal(windowVersus(0.05, 0.05), "同じ");
  assert.equal(windowVersus(0.05, null), null);
});

test("計算の回数:上限と比べるのは選ぶ期間の計算だけ。使う期間の計算は区切りの数だけ足す", () => {
  assert.deepEqual(runCounts(105, 5), { inSample: 525, outOfSample: 5, total: 530 });
});
