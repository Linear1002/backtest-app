// 総当たり(docs/sweep.md)の入力欄・組み合わせ・検証期間・表示の決まり。画面の部品から切り離した純粋な関数。
// 入力チェックの判定とメッセージは API(backend/api/validation.py の validate_sweep_inputs・validate_holdout)と同じにする。
// 両方が同じ答えを返すことは tests/fixtures/sweep_messages.json で確かめている。

import type { Objective, SweepCombo, SweepGrid, SweepGridKey, SweepMetrics, SweepRanking } from "./api.ts";
import { toNumber } from "./numbers.ts";

export const GRID_KEYS: readonly SweepGridKey[] = [
  "short_min",
  "short_max",
  "short_step",
  "long_min",
  "long_max",
  "long_step",
];

/** 日数と刻みの上限(docs/mvp.md 4.3 と同じ) */
export const MAX_WINDOW = 1000;

/** 検証期間の決め方:なし / 期間の最後の2割・3割 / 最後の1年 / 日付を指定 */
export type HoldoutChoice = "none" | "last20" | "last30" | "last1y" | "custom";

export type SweepForm = Record<SweepGridKey, string> & {
  holdout: HoldoutChoice;
  /** holdout が custom のときの開始日(YYYY-MM-DD) */
  holdout_date: string;
};

/** 既定値:短期3〜30日(3日ごと)× 長期20〜120日(10日ごと)= 105通り。検証期間は最後の3割 */
export const DEFAULT_SWEEP_FORM: SweepForm = {
  short_min: "3",
  short_max: "30",
  short_step: "3",
  long_min: "20",
  long_max: "120",
  long_step: "10",
  holdout: "last30",
  holdout_date: "",
};

/** 総当たりの入力欄の誤りを出す欄。grid は「組み合わせがない・多すぎる」(どの欄とも言えない) */
export type SweepFieldKey = SweepGridKey | "grid" | "holdout_start_date";
export type SweepErrors = Partial<Record<SweepFieldKey, string>>;

const count = new Intl.NumberFormat("ja-JP");

// --- 組み合わせ(docs/sweep.md 2章) -------------------------------------------------------

/** min, min + step, … のうち max 以下のもの。 */
export function gridValues(min: number, max: number, step: number): number[] {
  const values: number[] = [];
  for (let v = min; v <= max; v += step) values.push(v);
  return values;
}

/** 組み合わせの順番(短期の小さい順 → 長期の小さい順)。短期 < 長期 の組だけ。 */
export function gridPairs(grid: SweepGrid): [number, number][] {
  const longs = gridValues(grid.long_min, grid.long_max, grid.long_step);
  const pairs: [number, number][] = [];
  for (const short of gridValues(grid.short_min, grid.short_max, grid.short_step)) {
    for (const long of longs) if (short < long) pairs.push([short, long]);
  }
  return pairs;
}

/** 候補 min, min + step, … , ≦ max の数。 */
function valueCount(min: number, max: number, step: number): number {
  return max < min ? 0 : Math.floor((max - min) / step) + 1;
}

/**
 * 組み合わせの数(一覧を作らずに数える。入力のたびに何回も呼ばれるので、短期の候補の数だけの計算で済ませる)。
 * 短期 s ごとに、長期の候補のうち s より大きいものの数を足す。
 */
export function pairCount(grid: SweepGrid): number {
  const longs = valueCount(grid.long_min, grid.long_max, grid.long_step);
  let total = 0;
  for (const short of gridValues(grid.short_min, grid.short_max, grid.short_step)) {
    // 長期の候補のうち short 以下のもの(long_min + k × step ≦ short)の数を引く
    const notLonger = short < grid.long_min ? 0 : Math.min(longs, Math.floor((short - grid.long_min) / grid.long_step) + 1);
    total += longs - notLonger;
  }
  return total;
}

/** いちばん長い長期日数(組み合わせがあるとき。選ぶ期間の始まりをそろえる日数。docs/sweep.md 3章)。 */
export function longestWindow(grid: SweepGrid): number {
  return grid.long_min + (valueCount(grid.long_min, grid.long_max, grid.long_step) - 1) * grid.long_step;
}

/**
 * 格子の入力欄を確かめる(docs/sweep.md 5章の1)。maxPairs はエンジンの組み合わせの上限(null なら確かめない)。
 * 誤りはまとめて返す。誤りがなければ grid と組み合わせの数を返す。
 */
export function parseSweepGrid(
  form: SweepForm,
  maxPairs: number | null,
): { grid: SweepGrid | null; pairs: number | null; errors: SweepErrors } {
  const errors: SweepErrors = {};
  const values = {} as SweepGrid;
  for (const key of GRID_KEYS) {
    const value = toNumber(form[key] ?? "");
    if (value === null) errors[key] = "数値で入力してください";
    else if (!Number.isInteger(value) || value < 1) errors[key] = "日数と刻みは1以上の整数で入力してください";
    else if (value > MAX_WINDOW) errors[key] = `日数と刻みは${MAX_WINDOW}以下で入力してください`;
    else values[key] = value;
  }
  for (const [kind, label] of [
    ["short", "短期"],
    ["long", "長期"],
  ] as const) {
    const lo = `${kind}_min` as const;
    const hi = `${kind}_max` as const;
    if (!errors[lo] && !errors[hi] && values[lo] > values[hi]) {
      errors[lo] = `${label}の日数の範囲は、最小を最大以下にしてください`;
    }
  }
  if (Object.keys(errors).length > 0) return { grid: null, pairs: null, errors };
  const pairs = pairCount(values);
  if (pairs === 0) {
    errors.grid = "短期の日数が長期の日数より小さい組み合わせがありません。範囲を見直してください";
  } else if (maxPairs !== null && pairs > maxPairs) {
    errors.grid =
      `組み合わせが多すぎます(${count.format(pairs)}通り)。このエンジンでは${count.format(maxPairs)}通りまでです。` +
      "範囲を狭めるか、刻みを大きくしてください";
  }
  return { grid: Object.keys(errors).length ? null : values, pairs, errors };
}

// --- 検証期間(docs/sweep.md 3章) ---------------------------------------------------------

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;

/** YYYY-MM-DD の形で、暦にある日付か(2025-02-30 などは false。API も日付として受け付けない)。 */
export function isCalendarDate(text: string): boolean {
  if (!ISO_DATE.test(text)) return false;
  const [y, m, d] = text.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10) === text;
}

function toDay(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function fromDay(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/**
 * 選んだ決め方から、検証期間の開始日を決める。なしなら null。
 * - 最後の2割・3割:期間(暦の日数)の最後の2割・3割(開始日は丸めた日)
 * - 最後の1年:終了日の1年前の翌日(2/29 の1年前は 3/1)
 * 期間の日付が正しくないときは null(期間の欄のほうで誤りを出す)。
 */
export function holdoutStart(
  period: { start_date: string; end_date: string },
  choice: HoldoutChoice,
  customDate: string,
): string | null {
  if (choice === "none") return null;
  if (choice === "custom") return customDate;
  if (!ISO_DATE.test(period.start_date) || !ISO_DATE.test(period.end_date)) return null;
  const start = toDay(period.start_date);
  const end = toDay(period.end_date);
  if (choice === "last1y") {
    const [y, m, d] = period.end_date.split("-").map(Number);
    const daysInMonth = new Date(Date.UTC(y - 1, m, 0)).getUTCDate();
    return fromDay(Date.UTC(y - 1, m - 1, Math.min(d, daysInMonth)) + DAY_MS);
  }
  const share = choice === "last20" ? 0.2 : 0.3;
  const days = Math.round((end - start) / DAY_MS);
  return fromDay(start + Math.round(days * (1 - share)) * DAY_MS);
}

/** 検証期間の開始日の誤り(API と同じ文)。営業日の数は API だけが確かめる(画面はデータを持たないため)。 */
export function validateHoldout(period: { start_date: string; end_date: string }, holdout: string | null): string | null {
  if (holdout === null) return null;
  if (!isCalendarDate(holdout)) return "日付は YYYY-MM-DD の形で入力してください";
  if (!(period.start_date < holdout && holdout <= period.end_date)) {
    return "検証期間の開始日は、期間の開始日より後、終了日以前の日付にしてください";
  }
  return null;
}

/** 前日(選ぶ期間の終わりの日)。 */
export function dayBefore(iso: string): string {
  return fromDay(toDay(iso) - DAY_MS);
}

// --- 並べ方・表示(docs/sweep.md 7章・8章) -------------------------------------------------

export const OBJECTIVES: readonly Objective[] = ["sharpe_ratio", "total_return", "max_drawdown"];

export const OBJECTIVE_LABELS: Record<Objective, string> = {
  sharpe_ratio: "シャープレシオ",
  total_return: "総リターン",
  max_drawdown: "最大ドローダウン",
};

/** よい順の向き(最大ドローダウンは小さいほどよい) */
export const LARGER_IS_BETTER: Record<Objective, boolean> = {
  sharpe_ratio: true,
  total_return: true,
  max_drawdown: false,
};

export function metricValue(metrics: SweepMetrics | null, objective: Objective): number | null {
  if (!metrics) return null;
  const value = metrics[objective];
  return value === null || !Number.isFinite(value) ? null : value;
}

export function rankingFor(rankings: readonly SweepRanking[], objective: Objective): SweepRanking {
  const found = rankings.find((r) => r.objective === objective);
  if (!found) throw new Error(`並べ方がありません: ${objective}`);
  return found;
}

/**
 * ヒートマップの色の強さを決める「いちばん大きい値」。**選ぶ期間の値だけ**で決める(docs/sweep.md 8章)。
 * 検証期間の値を入れると、検証期間の情報が「選ぶ画面」の色の濃さに入り込んでしまうため。
 * 検証期間のヒートマップも同じ物差しで塗る(切り替えても同じ色が同じ値。はみ出す値は端の色)。値がなければ 1。
 */
export function heatScaleMax(combos: readonly SweepCombo[], objective: Objective): number {
  let max = 0;
  for (const combo of combos) {
    const v = metricValue(combo.in_sample, objective);
    if (v !== null) max = Math.max(max, Math.abs(v));
  }
  return max > 0 ? max : 1;
}

/** 検証期間の値のうち、物差し(選ぶ期間の最大)を超えて端の色にそろえたものがあるか。 */
export function exceedsScale(combos: readonly SweepCombo[], objective: Objective, scaleMax: number): boolean {
  return combos.some((c) => {
    const v = metricValue(c.out_of_sample, objective);
    return v !== null && Math.abs(v) > scaleMax;
  });
}

/**
 * ヒートマップのマスの色。シャープレシオ・総リターンは 0 を中心に、プラスは朱・マイナスは藍
 * (日本の習慣どおり。DESIGN.md)。最大ドローダウンは大きいほど濃い藍。
 * strength は 0〜1(0 は中立のグレー)。値がなければ none。
 */
export type HeatTone = { kind: "none" } | { kind: "up" | "down"; strength: number };

export function heatTone(value: number | null, objective: Objective, scaleMax: number): HeatTone {
  if (value === null) return { kind: "none" };
  const strength = Math.min(1, Math.abs(value) / scaleMax);
  if (objective === "max_drawdown") return { kind: "down", strength };
  if (value === 0) return { kind: "up", strength: 0 };
  return { kind: value > 0 ? "up" : "down", strength };
}

/** CSS の背景色(テーマの朱・藍と、中立のグレーを OKLab で混ぜる。ダークモードでも同じ式)。 */
export function heatColor(tone: HeatTone): string {
  if (tone.kind === "none") return "var(--surface)";
  const pole = tone.kind === "up" ? "var(--shu)" : "var(--ai)";
  // 弱い値でも、中立のグレーと見分けられるように少しだけ底上げする
  const percent = tone.strength === 0 ? 0 : Math.round(12 + 88 * tone.strength);
  return `color-mix(in oklab, ${pole} ${percent}%, var(--heat-mid))`;
}

/** 順位相関の読み方の目安を出す、組み合わせの数の下限(これより少ないと、たまたまの値が大きく出る)。 */
export const MIN_CORRELATION_PAIRS = 10;

/**
 * 順位相関の読み方(目安)。pairs は計算に使った組み合わせの数(両方の期間に値があるもの)。
 * となりの組み合わせはほとんど同じ売買をするので、組み合わせの数ほどの独立した証拠にはならない(docs/sweep.md 7章)。
 */
export function correlationReading(rho: number | null, pairs: number): string {
  if (rho === null) {
    return pairs >= 3
      ? "どちらかの期間で、すべての組み合わせが同じ値のため計算できません"
      : "両方の期間に値がある組み合わせが3つ未満のため、計算していません";
  }
  if (pairs < MIN_CORRELATION_PAIRS) {
    return `組み合わせが${pairs}通りと少ないため、読み方の目安は出しません(少ないと、たまたま大きな値が出ます)`;
  }
  if (rho >= 0.5) return "目安:ある程度そろっています(それでも、たまたまの可能性は残ります)";
  if (rho >= 0.2) return "目安:弱い関係しかありません";
  if (rho > -0.2) return "目安:ほとんど関係がありません。選ぶ期間の順位は、検証期間の順位を予想できていません";
  return "目安:逆の関係です。選ぶ期間で良かった組み合わせほど、検証期間では悪くなっています";
}

/**
 * 年率に直したシャープレシオの標準誤差の目安 √(年間の営業日数 / 日次リターンの数)。
 * API の注記(backend/api/sweep_convert.py の sharpe_standard_error)と同じ式。
 */
export function sharpeStandardError(businessDays: number, tradingDaysPerYear: number): number {
  return Math.sqrt(tradingDaysPerYear / Math.max(1, businessDays - 1));
}

/** 選ぶ期間の1位が1つに決まるときだけ、その位置(同率1位なら null)。 */
export function uniqueBest(ranking: SweepRanking): number | null {
  return ranking.best_tie_count === 1 ? ranking.best_index : null;
}

/** 組み合わせごとの、期間の基準の値(combos と同じ順番)。 */
export function segmentValues(
  combos: readonly SweepCombo[],
  segment: "in_sample" | "out_of_sample",
  objective: Objective,
): (number | null)[] {
  return combos.map((c) => metricValue(segment === "in_sample" ? c.in_sample : c.out_of_sample, objective));
}

/** 順位 = 1 + それより良い値の組み合わせの数(API の best_out_of_sample_rank と同じ決め方)。値がなければ null。 */
export function competitionRank(values: readonly (number | null)[], index: number, objective: Objective): number | null {
  const target = values[index];
  if (target === null) return null;
  const larger = LARGER_IS_BETTER[objective];
  const better = values.filter((v) => v !== null && (larger ? v > target : v < target)).length;
  return 1 + better;
}

/**
 * すべての組み合わせの順位(competitionRank と同じ決め方)を、まとめて出す。
 * 1つずつ competitionRank を呼ぶと組み合わせの数の2乗の比較になるので、表のように全部の順位がいるときはこちらを使う。
 */
export function competitionRanks(values: readonly (number | null)[], objective: Objective): (number | null)[] {
  const larger = LARGER_IS_BETTER[objective];
  const sorted = values.filter((v): v is number => v !== null).sort((a, b) => (larger ? b - a : a - b));
  // 値ごとに、よい順に並べて最初に出てくる位置(= それより良い値の数)
  const better = new Map<number, number>();
  sorted.forEach((v, i) => {
    if (!better.has(v)) better.set(v, i);
  });
  return values.map((v) => (v === null ? null : 1 + better.get(v)!));
}
