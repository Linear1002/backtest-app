// ウォークフォワード分析(docs/walkforward.md)の入力欄・区切り方・入力チェック。画面の部品から切り離した純粋な関数。
// 区切り方は Python(engine/reference/walkforward.py の add_months・calendar_windows)と同じ計算で、
// 両方が同じ答えを返すことは tests/fixtures/walkforward_windows.json で確かめている。
// 入力チェックのメッセージは API(backend/api/validation.py・engine/reference/walkforward.py)と同じ文にする
// (tests/fixtures/walkforward_messages.json)。

import type { WalkForwardObjective } from "./api.ts";

/** 選ぶ期間・使う期間の長さの上限(か月。docs/walkforward.md 2章) */
export const MAX_IN_SAMPLE_MONTHS = 120;
export const MAX_OUT_OF_SAMPLE_MONTHS = 60;

/** 1位を選ぶ基準(最大ドローダウンは選べない。docs/walkforward.md 2章) */
export const WALKFORWARD_OBJECTIVES: readonly WalkForwardObjective[] = ["sharpe_ratio", "total_return"];

/** 画面で選べる長さ(docs/walkforward.md 2章) */
export const IN_SAMPLE_CHOICES = [
  { months: 12, label: "1年" },
  { months: 24, label: "2年" },
  { months: 36, label: "3年" },
  { months: 60, label: "5年" },
] as const;
export const OUT_OF_SAMPLE_CHOICES = [
  { months: 3, label: "3か月" },
  { months: 6, label: "6か月" },
  { months: 12, label: "1年" },
] as const;

export type WalkForwardForm = {
  objective: WalkForwardObjective;
  in_sample_months: number;
  out_of_sample_months: number;
};

/** 既定値:シャープレシオが1位の日数を、直前2年で選び、次の半年使う */
export const DEFAULT_WALKFORWARD_FORM: WalkForwardForm = {
  objective: "sharpe_ratio",
  in_sample_months: 24,
  out_of_sample_months: 6,
};

/**
 * ウォークフォワードの入力の誤りを出す欄。windows は「区切りが1つも作れない」(どの欄とも言えない)。
 * 格子の「計算が多すぎる」は、総当たりと同じ grid の欄に出す。
 */
export type WalkForwardFieldKey = "objective" | "in_sample_months" | "out_of_sample_months" | "windows";

const count = new Intl.NumberFormat("ja-JP");

// --- 区切り方(docs/walkforward.md 3章) ------------------------------------------------

function parse(iso: string): [number, number, number] {
  const [y, m, d] = iso.split("-").map(Number);
  return [y, m, d];
}

function iso(y: number, m: number, d: number): string {
  return new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);
}

/** day の年月に months か月を足す。日はそのままで、その月にない日なら月末にする(1月31日 + 1か月 = 2月28日)。 */
export function addMonths(day: string, months: number): string {
  const [y, m, d] = parse(day);
  const total = y * 12 + (m - 1) + months;
  const year = Math.floor(total / 12);
  const month = (total % 12) + 1;
  // その月の末日(翌月の0日)
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return iso(year, month, Math.min(d, last));
}

/** 前の日。 */
function dayBefore(day: string): string {
  const [y, m, d] = parse(day);
  return iso(y, m, d - 1);
}

/** 暦だけで決まる区切り。日付はすべて YYYY-MM-DD。 */
export type CalendarWindow = {
  /** 区切りの番号(1から) */
  index: number;
  inSampleStart: string;
  inSampleEnd: string;
  outOfSampleStart: string;
  outOfSampleEnd: string;
};

/**
 * 区切り(docs/walkforward.md 3章)。すべて start から月を足して決める(前の区切りから足し重ねない)。
 * 使う期間が end までに丸ごと入る区切りだけ。始まりのそろえ(営業日が要る)は API が行う。
 */
export function calendarWindows(start: string, end: string, inSampleMonths: number, outOfSampleMonths: number): CalendarWindow[] {
  const windows: CalendarWindow[] = [];
  for (let k = 1; ; k += 1) {
    const inStart = addMonths(start, (k - 1) * outOfSampleMonths);
    const outStart = addMonths(start, inSampleMonths + (k - 1) * outOfSampleMonths);
    const outEnd = dayBefore(addMonths(start, inSampleMonths + k * outOfSampleMonths));
    if (outEnd > end) return windows;
    windows.push({
      index: k,
      inSampleStart: inStart,
      inSampleEnd: dayBefore(outStart),
      outOfSampleStart: outStart,
      outOfSampleEnd: outEnd,
    });
  }
}

// --- 入力チェック(docs/walkforward.md 7章) ---------------------------------------------

/** 計算の量の上限(組み合わせの数 × 区切りの数):総当たりの組み合わせの上限 × 2(docs/walkforward.md 9章) */
export function maxRuns(maxPairs: number): number {
  return maxPairs * 2;
}

/** 基準・選ぶ期間の長さ・使う期間の長さ(7章の3)。画面はボタンで選ぶので、ふつうは誤りにならない。 */
export function settingsErrors(form: WalkForwardForm): Partial<Record<WalkForwardFieldKey, string>> {
  const errors: Partial<Record<WalkForwardFieldKey, string>> = {};
  if (!WALKFORWARD_OBJECTIVES.includes(form.objective)) {
    errors.objective = "1位を選ぶ基準は、シャープレシオか総リターンを選んでください";
  }
  const months = [
    ["in_sample_months", form.in_sample_months, MAX_IN_SAMPLE_MONTHS, "選ぶ期間"],
    ["out_of_sample_months", form.out_of_sample_months, MAX_OUT_OF_SAMPLE_MONTHS, "使う期間"],
  ] as const;
  for (const [key, value, maximum, label] of months) {
    if (!Number.isInteger(value) || value < 1 || value > maximum) {
      errors[key] = `${label}の長さは1〜${maximum}か月の整数で入力してください`;
    }
  }
  return errors;
}

/** 区切りが1つも作れないときの文(7章の6)。 */
export function noWindowsMessage(form: WalkForwardForm): string {
  return (
    `期間が短すぎて、選ぶ期間(${form.in_sample_months}か月)と使う期間(${form.out_of_sample_months}か月)を1回も取れません。` +
    "期間を広げるか、選ぶ期間・使う期間を短くしてください"
  );
}

/** 計算が多すぎるときの文(7章の7)。上限を超えていなければ null。 */
export function tooManyRunsMessage(pairs: number, windows: number, limit: number): string | null {
  const runs = pairs * windows;
  if (runs <= limit) return null;
  return (
    `計算が多すぎます(${count.format(pairs)}通り × 区切り${count.format(windows)}回 = ${count.format(runs)}回)。` +
    `このエンジンでは${count.format(limit)}回までです。範囲を狭める・刻みを大きくする・使う期間を長くする、のどれかをしてください`
  );
}

/**
 * 期間と格子が正しいときに確かめる、区切りと計算の量(7章の6・7)。
 * 営業日が要るチェック(始まりをそろえたあとの選ぶ期間・使う期間が3営業日以上か)は API が行う。
 * pairs は組み合わせの数、limit は計算の量の上限(null なら確かめない)。
 */
export function validateWalkForward(
  form: WalkForwardForm,
  period: { start_date: string; end_date: string },
  pairs: number,
  limit: number | null,
): { windows: CalendarWindow[]; errors: { windows?: string; grid?: string } } {
  const windows = calendarWindows(period.start_date, period.end_date, form.in_sample_months, form.out_of_sample_months);
  if (windows.length === 0) return { windows, errors: { windows: noWindowsMessage(form) } };
  const tooMany = limit === null ? null : tooManyRunsMessage(pairs, windows.length, limit);
  return { windows, errors: tooMany ? { grid: tooMany } : {} };
}

/** 選ぶ期間・使う期間の長さの読み方(「2年」「6か月」。12の倍数は年で書く)。 */
export function monthsText(months: number): string {
  return months % 12 === 0 ? `${months / 12}年` : `${months}か月`;
}
