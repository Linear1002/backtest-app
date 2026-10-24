import assert from "node:assert/strict";
import { test } from "node:test";

import { defaultForm, numberText, parseParams, presetPeriod, toNumber, validatePeriod, type FormState } from "./form.ts";
import { SPECS } from "./testing.ts";

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

const errorOf = (key: keyof FormState["params"], text: string) => parseParams(form({ [key]: text }), SPECS).errors[key];

test("既定値の入力欄(ParamSpec の default と、データの範囲)", () => {
  assert.deepEqual(defaultForm(SPECS, range), form());
});

test("受け付ける数値の形", () => {
  assert.equal(toNumber("1000000"), 1_000_000);
  assert.equal(toNumber("１,０００,０００"), 1_000_000); // 全角数字・全角カンマ
  assert.equal(toNumber("  12.5 "), 12.5);
  assert.equal(toNumber("1e6"), 1_000_000); // 指数表記は受け付ける(補助表示とも一致する)
  assert.equal(toNumber("−5"), -5); // 画面の表示に使う U+2212
  assert.equal(toNumber("－5"), -5); // 全角のハイフンマイナス
  assert.equal(toNumber(".5"), 0.5);
  for (const bad of ["", "   ", "0x10", "Infinity", "-Infinity", "NaN", "1e400", "100万", "1.2.3", "abc"]) {
    assert.equal(toNumber(bad), null, bad);
  }
});

test("カンマは3桁区切りの位置だけ受け付ける(「0,1」を黙って 1 にしない)", () => {
  assert.equal(toNumber("1,000,000"), 1_000_000);
  assert.equal(toNumber("１，０００"), 1000); // 全角のカンマも3桁区切りなら可
  assert.equal(toNumber("-1,234.5"), -1234.5);
  for (const bad of ["0,1", "1,5", "1,00", "1,0000", ",100", "100,", "1,,000"]) {
    assert.equal(toNumber(bad), null, bad);
  }
  assert.equal(errorOf("fee_rate_pct", "0,1"), "数値で入力してください");
});

test("正しい入力は数値になる", () => {
  const { params, errors } = parseParams(form({ initial_cash: "１,０００,０００" }), SPECS);
  assert.deepEqual(errors, {});
  assert.deepEqual(params, { short_window: 5, long_window: 25, fee_rate_pct: 0.1, slippage_rate_pct: 0.05, initial_cash: 1_000_000 });
});

test("仕様(4.3)・API と同じメッセージ", () => {
  assert.equal(
    parseParams(form({ short_window: "25", long_window: "5" }), SPECS).errors.short_window,
    "短期の日数は長期の日数より小さくしてください",
  );
  assert.equal(
    parseParams(form({ short_window: "25", long_window: "25" }), SPECS).errors.short_window,
    "短期の日数は長期の日数より小さくしてください",
  );
  assert.equal(errorOf("short_window", "2.5"), "日数は1以上の整数で入力してください");
  assert.equal(errorOf("short_window", "0"), "日数は1以上の整数で入力してください");
  assert.equal(errorOf("long_window", "1001"), "日数は1000以下で入力してください");
  assert.equal(errorOf("fee_rate_pct", "-1"), "手数料率とスリッページ率は0以上で入力してください");
  assert.equal(errorOf("slippage_rate_pct", "10"), "手数料率とスリッページ率は10%未満で入力してください");
  assert.equal(errorOf("initial_cash", "0"), "初期資金は1円以上で入力してください");
  assert.equal(errorOf("initial_cash", "0.5"), "初期資金は1円以上で入力してください");
  assert.equal(errorOf("initial_cash", "1000000001"), "初期資金は10億円以下で入力してください");
  for (const bad of ["abc", "", "   ", "0x10", "Infinity"]) {
    assert.equal(errorOf("initial_cash", bad), "数値で入力してください", bad);
  }
});

test("境界の値は通る", () => {
  for (const [key, text] of [
    ["fee_rate_pct", "0"],
    ["fee_rate_pct", "9.99"],
    ["slippage_rate_pct", "0"],
    ["initial_cash", "1"],
    ["initial_cash", "1000000000"],
    ["long_window", "1000"],
  ] as const) {
    assert.equal(errorOf(key, text), undefined, `${key}=${text}`);
  }
  // 1つでも誤りがあれば params は null(誤りのない項目のエラーは出さない)
  const both = parseParams(form({ fee_rate_pct: "-1", initial_cash: "abc" }), SPECS);
  assert.equal(both.params, null);
  assert.deepEqual(Object.keys(both.errors).sort(), ["fee_rate_pct", "initial_cash"]);
});

test("メッセージの数値の書き方は API と同じ", () => {
  assert.equal(numberText(1_000_000_000), "10億");
  assert.equal(numberText(1000), "1000");
  assert.equal(numberText(0.5), "0.5");
});

test("期間のチェック", () => {
  assert.deepEqual(validatePeriod(form(), range), {});
  assert.equal(
    validatePeriod(form({}, { start_date: "2025-06-30", end_date: "2025-01-01" }), range).start_date,
    "開始日は終了日より前の日付にしてください",
  );
  assert.match(validatePeriod(form({}, { start_date: "2021-01-01" }), range).start_date ?? "", /取得可能:2022-01-04〜2026-07-31/);
  assert.match(validatePeriod(form({}, { end_date: "2026-08-01" }), range).end_date ?? "", /取得可能/);
  // 日付の入力欄は、入力の途中だと空文字になる
  assert.equal(validatePeriod(form({}, { start_date: "" }), range).start_date, "日付は YYYY-MM-DD の形で入力してください");
  // 開始日と終了日が同じ日は、このチェックでは誤りにしない(営業日が3日未満かは API が確かめる)
  assert.deepEqual(validatePeriod(form({}, { start_date: "2025-01-06", end_date: "2025-01-06" }), range), {});
});

test("期間のよく使う指定", () => {
  assert.deepEqual(presetPeriod(range, 1), { start_date: "2025-08-01", end_date: "2026-07-31" });
  assert.deepEqual(presetPeriod(range, 10), { start_date: "2022-01-04", end_date: "2026-07-31" });
  assert.deepEqual(presetPeriod(range, null), { start_date: "2022-01-04", end_date: "2026-07-31" });
});

test("うるう日の1年前は、その月の末日にそろえてから1日足す", () => {
  const leap = { first_date: "2020-01-06", last_date: "2024-02-29" };
  assert.deepEqual(presetPeriod(leap, 1), { start_date: "2023-03-01", end_date: "2024-02-29" });
  assert.deepEqual(presetPeriod(leap, 4), { start_date: "2020-03-01", end_date: "2024-02-29" });
  assert.deepEqual(presetPeriod({ first_date: "2020-01-06", last_date: "2025-03-31" }, 1).start_date, "2024-04-01");
});
