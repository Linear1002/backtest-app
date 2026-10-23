import assert from "node:assert/strict";
import { test } from "node:test";

import { parseParams, presetPeriod, validatePeriod, type FormState } from "./form.ts";

const range = { first_date: "2022-01-04", last_date: "2026-07-31" };

function form(params: Partial<FormState["params"]> = {}, period: Partial<FormState> = {}): FormState {
  return {
    start_date: "2022-01-04",
    end_date: "2026-07-31",
    params: {
      short_window: "5",
      long_window: "25",
      fee_rate_pct: "0.1",
      slippage_rate_pct: "0.05",
      initial_cash: "1000000",
      ...params,
    },
    ...period,
  };
}

test("正しい入力は数値になる(全角・カンマも可)", () => {
  const { params, errors } = parseParams(form({ initial_cash: "１,０００,０００" }));
  assert.deepEqual(errors, {});
  assert.equal(params?.initial_cash, 1_000_000);
});

test("仕様(4.3)と同じメッセージ", () => {
  assert.equal(parseParams(form({ short_window: "25", long_window: "5" })).errors.short_window, "短期の日数は長期の日数より小さくしてください");
  assert.equal(parseParams(form({ short_window: "2.5" })).errors.short_window, "日数は1以上の整数で入力してください");
  assert.equal(parseParams(form({ fee_rate_pct: "-1" })).errors.fee_rate_pct, "手数料率とスリッページ率は0以上で入力してください");
  assert.equal(parseParams(form({ slippage_rate_pct: "10" })).errors.slippage_rate_pct, "手数料率とスリッページ率は10%未満で入力してください");
  assert.equal(parseParams(form({ initial_cash: "0" })).errors.initial_cash, "初期資金は1円以上で入力してください");
  assert.equal(parseParams(form({ initial_cash: "0.5" })).errors.initial_cash, "初期資金は1円以上で入力してください");
  assert.equal(parseParams(form({ initial_cash: "abc" })).errors.initial_cash, "数値で入力してください");
});

test("期間のチェック", () => {
  assert.deepEqual(validatePeriod(form(), range), {});
  assert.equal(validatePeriod(form({}, { start_date: "2025-06-30", end_date: "2025-01-01" }), range).start_date, "開始日は終了日より前の日付にしてください");
  assert.match(validatePeriod(form({}, { start_date: "2021-01-01" }), range).start_date ?? "", /取得可能:2022-01-04〜2026-07-31/);
});

test("期間のよく使う指定", () => {
  assert.deepEqual(presetPeriod(range, 1), { start_date: "2025-08-01", end_date: "2026-07-31" });
  assert.deepEqual(presetPeriod(range, 10), { start_date: "2022-01-04", end_date: "2026-07-31" });
  assert.deepEqual(presetPeriod(range, null), { start_date: "2022-01-04", end_date: "2026-07-31" });
});
