// 詳細設定の入力値と、その場で出す入力チェック(docs/mvp.md 4.3)。
// 最終的なチェックは API が行う。ここは打ち間違いにすぐ気づけるようにするためのもの。
// 範囲の数値は API が返す ParamSpec(backend/strategies.py が正)から読み、ここには書かない。
// メッセージは API(backend/api/validation.py)と同じ文にする。

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

// 受け付ける数値の形:符号・整数部・小数部・指数(1e6 など)。16進("0x10")や "Infinity" は受け付けない
const NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;

/**
 * 入力欄の文字を数値にする。読めなければ null。
 * 全角数字・全角カンマ・カンマ区切り(1,000,000)・前後の空白は受け付ける。
 * マイナスは "-" のほか、画面の表示に使っている「−」(U+2212)と全角の「-」も受け付ける。
 */
export function toNumber(text: string): number | null {
  const normalized = text
    .normalize("NFKC")
    .replaceAll("−", "-")
    .replaceAll(",", "")
    .trim();
  if (!NUMBER.test(normalized)) return null;
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

/** メッセージに入れる数値(1000000000 → "10億"、1000 → "1000")。API と同じ書き方。 */
export function numberText(value: number): string {
  if (value >= 1e8 && value % 1e8 === 0) return `${value / 1e8}億`;
  return String(value);
}

function checkSpec(spec: ParamSpec, value: number): string | null {
  const max = spec.maximum;
  const overMax = max !== null && (spec.exclusive_maximum ? value >= max : value > max);
  switch (spec.kind) {
    case "integer":
      if (!Number.isInteger(value) || value < spec.minimum) {
        return `日数は${numberText(spec.minimum)}以上の整数で入力してください`;
      }
      if (overMax) return `日数は${numberText(max)}以下で入力してください`;
      return null;
    case "percent":
      if (value < spec.minimum) return `手数料率とスリッページ率は${numberText(spec.minimum)}以上で入力してください`;
      if (overMax) {
        return spec.exclusive_maximum
          ? `手数料率とスリッページ率は${numberText(max)}%未満で入力してください`
          : `手数料率とスリッページ率は${numberText(max)}%以下で入力してください`;
      }
      return null;
    case "yen":
      if (value < spec.minimum) return `初期資金は${numberText(spec.minimum)}円以上で入力してください`;
      if (overMax) return `初期資金は${numberText(max)}円以下で入力してください`;
      return null;
  }
}

export function parseParams(form: FormState, specs: ParamSpec[]): { params: Params | null; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const values = {} as Params;
  for (const spec of specs) {
    const value = toNumber(form.params[spec.key] ?? "");
    if (value === null) {
      errors[spec.key] = "数値で入力してください";
      continue;
    }
    const message = checkSpec(spec, value);
    if (message) errors[spec.key] = message;
    else values[spec.key] = value;
  }
  // 移動平均クロスだけの決まり:短期は長期より短くする
  const hasWindows = specs.some((s) => s.key === "short_window") && specs.some((s) => s.key === "long_window");
  if (
    hasWindows &&
    !errors.short_window &&
    !errors.long_window &&
    values.short_window >= values.long_window
  ) {
    errors.short_window = "短期の日数は長期の日数より小さくしてください";
  }
  return { params: Object.keys(errors).length ? null : values, errors };
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function validatePeriod(
  form: FormState,
  range: { first_date: string; last_date: string },
): FieldErrors {
  const errors: FieldErrors = {};
  // 日付の入力欄は、入力の途中(年だけ打った等)だと空文字になる
  if (!ISO_DATE.test(form.start_date)) errors.start_date = "日付は YYYY-MM-DD の形で入力してください";
  if (!ISO_DATE.test(form.end_date)) errors.end_date = "日付は YYYY-MM-DD の形で入力してください";
  if (errors.start_date || errors.end_date) return errors;
  if (form.start_date > form.end_date) errors.start_date = "開始日は終了日より前の日付にしてください";
  else if (form.start_date < range.first_date || form.end_date > range.last_date) {
    const message = `指定した期間のデータがありません(取得可能:${range.first_date}〜${range.last_date})`;
    if (form.start_date < range.first_date) errors.start_date = message;
    else errors.end_date = message;
  }
  return errors;
}

function isoDate(y: number, m: number, d: number): string {
  return new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);
}

/**
 * 期間のよく使う指定(最後の日の n 年前の翌日から、最後の日まで)。データの最初の日より前にはしない。
 * n 年前の同じ日がない(2/29 の1年前)ときは、その月の末日にそろえてから1日足す(2024-02-29 → 2023-03-01)。
 */
export function presetPeriod(
  range: { first_date: string; last_date: string },
  years: number | null,
): { start_date: string; end_date: string } {
  if (years === null) return { start_date: range.first_date, end_date: range.last_date };
  const [y, m, d] = range.last_date.split("-").map(Number);
  const daysInMonth = new Date(Date.UTC(y - years, m, 0)).getUTCDate();
  const start = isoDate(y - years, m, Math.min(d, daysInMonth) + 1);
  return {
    start_date: start < range.first_date ? range.first_date : start,
    end_date: range.last_date,
  };
}
