// 詳細設定の入力値と、その場で出す入力チェック(docs/mvp.md 4.3)。
// 最終的なチェックは API が行う。ここは打ち間違いにすぐ気づけるようにするためのもの。

import type { ParamKey, Params, ParamSpec } from "./api.ts";

export type FormState = {
  start_date: string;
  end_date: string;
  params: Record<ParamKey, string>;
};

export type FieldErrors = Partial<Record<ParamKey | "start_date" | "end_date", string>>;

export function defaultForm(specs: ParamSpec[], range: { first_date: string; last_date: string }): FormState {
  const params = {} as Record<ParamKey, string>;
  for (const spec of specs) params[spec.key] = String(spec.default);
  return { start_date: range.first_date, end_date: range.last_date, params };
}

function toNumber(text: string): number | null {
  // 全角数字やカンマも受け付ける(「１００万」は受け付けない)
  const normalized = text.normalize("NFKC").replaceAll(",", "").trim();
  if (normalized === "") return null;
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

export function parseParams(form: FormState): { params: Params | null; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const values = {} as Params;
  for (const key of Object.keys(form.params) as ParamKey[]) {
    const value = toNumber(form.params[key]);
    if (value === null) errors[key] = "数値で入力してください";
    else values[key] = value;
  }
  for (const key of ["short_window", "long_window"] as const) {
    const v = values[key];
    if (errors[key] === undefined && (!Number.isInteger(v) || v < 1)) {
      errors[key] = "日数は1以上の整数で入力してください";
    }
  }
  if (!errors.short_window && !errors.long_window && values.short_window >= values.long_window) {
    errors.short_window = "短期の日数は長期の日数より小さくしてください";
  }
  for (const key of ["fee_rate_pct", "slippage_rate_pct"] as const) {
    const v = values[key];
    if (errors[key] !== undefined) continue;
    if (v < 0) errors[key] = "手数料率とスリッページ率は0以上で入力してください";
    else if (v >= 10) errors[key] = "手数料率とスリッページ率は10%未満で入力してください";
  }
  if (errors.initial_cash === undefined) {
    if (values.initial_cash < 1) errors.initial_cash = "初期資金は1円以上で入力してください";
    else if (values.initial_cash > 1_000_000_000) errors.initial_cash = "初期資金は10億円以下で入力してください";
  }
  return { params: Object.keys(errors).length ? null : values, errors };
}

export function validatePeriod(
  form: FormState,
  range: { first_date: string; last_date: string },
): FieldErrors {
  const errors: FieldErrors = {};
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.start_date)) errors.start_date = "日付は YYYY-MM-DD の形で入力してください";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.end_date)) errors.end_date = "日付は YYYY-MM-DD の形で入力してください";
  if (errors.start_date || errors.end_date) return errors;
  if (form.start_date > form.end_date) errors.start_date = "開始日は終了日より前の日付にしてください";
  else if (form.start_date < range.first_date || form.end_date > range.last_date) {
    const message = `指定した期間のデータがありません(取得可能:${range.first_date}〜${range.last_date})`;
    if (form.start_date < range.first_date) errors.start_date = message;
    else errors.end_date = message;
  }
  return errors;
}

/** 期間のよく使う指定(最後の日から n 年前まで)。データの最初の日より前にはしない。 */
export function presetPeriod(
  range: { first_date: string; last_date: string },
  years: number | null,
): { start_date: string; end_date: string } {
  if (years === null) return { start_date: range.first_date, end_date: range.last_date };
  const [y, m, d] = range.last_date.split("-").map(Number);
  const start = new Date(Date.UTC(y - years, m - 1, d + 1)).toISOString().slice(0, 10);
  return {
    start_date: start < range.first_date ? range.first_date : start,
    end_date: range.last_date,
  };
}
