// チャート用の小さな計算(目盛り・座標・パス)。外部ライブラリを使わず、SVG を自前で描くための道具。
// 横軸は「営業日の番号」(土日・休場日のすき間を詰める。株価チャートの一般的な描き方)。

export type Scale = {
  (value: number): number;
  invert: (pixel: number) => number;
  domain: [number, number];
  range: [number, number];
};

export function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  const scale = ((value: number) => r0 + ((value - d0) / span) * (r1 - r0)) as Scale;
  scale.invert = (pixel: number) => d0 + ((pixel - r0) / (r1 - r0 || 1)) * span;
  scale.domain = domain;
  scale.range = range;
  return scale;
}

/** 1・2・2.5・5 × 10^n の「きりのいい」目盛りと、その間隔(step)。間隔は目盛りの数字の桁数を決めるのに使う。 */
export function niceScale(min: number, max: number, count = 5): { ticks: number[]; step: number } {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { ticks: [], step: 0 };
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad;
    max += pad;
  }
  const rawStep = (max - min) / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rawStep) ?? 10 * power;
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 1e-9; v += step) {
    ticks.push(Number(v.toPrecision(12)));
  }
  return { ticks, step: Number(step.toPrecision(12)) };
}

/** きりのいい目盛り(niceScale の目盛りだけ)。 */
export function niceTicks(min: number, max: number, count = 5): number[] {
  return niceScale(min, max, count).ticks;
}

/** 目盛りを含むように広げた範囲(上下に少し余白を足す)。 */
export function paddedExtent(values: Iterable<number>, padRatio = 0.06): [number, number] {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === Infinity) return [0, 1];
  const pad = (max - min) * padRatio || Math.abs(max) * 0.05 || 1;
  return [min - pad, max + pad];
}

/**
 * 折れ線のパス。null の点で線を切る(売買不成立の日など)。
 * 前後が null の1点だけの区間は、長さ0の線(h0)にする。stroke-linecap="round" なら点として描かれる。
 */
export function linePath(points: ReadonlyArray<readonly [number, number] | null>): string {
  let d = "";
  let run = 0; // いまの区間の点の数
  const close = () => {
    if (run === 1) d += "h0";
    run = 0;
  };
  for (const p of points) {
    if (p === null) {
      close();
      continue;
    }
    d += `${run > 0 ? "L" : "M"}${round(p[0])},${round(p[1])}`;
    run += 1;
  }
  close();
  return d;
}

/** 折れ線と基準線(baseline)のあいだを塗るパス。 */
export function areaPath(points: ReadonlyArray<readonly [number, number]>, baseline: number): string {
  if (points.length === 0) return "";
  const top = points.map((p, i) => `${i === 0 ? "M" : "L"}${round(p[0])},${round(p[1])}`).join("");
  const last = points[points.length - 1];
  const first = points[0];
  return `${top}L${round(last[0])},${round(baseline)}L${round(first[0])},${round(baseline)}Z`;
}

function round(v: number): number {
  return Math.round(v * 10) / 10;
}

export type DateTick = { index: number; label: string; major: boolean };

/**
 * 日付の目盛り。期間が長いときは年の始まりだけ、短いときは四半期や月の始まりに置く。
 * 月の始まりが2つ未満しかない短い期間(1か月ほど)は、日付を等間隔に置く(「4/15」の形)。
 * dates は "YYYY-MM-DD" の配列(古い順)。
 */
export function dateTicks(dates: readonly string[], maxTicks = 8): DateTick[] {
  if (dates.length === 0) return [];
  const candidates: { index: number; year: number; month: number }[] = [];
  let previous = "";
  dates.forEach((iso, index) => {
    const ym = iso.slice(0, 7);
    if (ym !== previous) {
      candidates.push({ index, year: Number(iso.slice(0, 4)), month: Number(iso.slice(5, 7)) });
      previous = ym;
    }
  });
  const monthStarts = candidates.filter((c) => c.index > 0);
  if (monthStarts.length < 2) return dayTicks(dates, Math.min(maxTicks, 5));
  for (const step of [1, 3, 6, 12]) {
    const picked = monthStarts.filter((c) => (c.month - 1) % step === 0);
    if (picked.length <= maxTicks && picked.length > 0) {
      return picked.map((c) => ({
        index: c.index,
        label: c.month === 1 ? `${c.year}年` : `${c.month}月`,
        major: c.month === 1,
      }));
    }
  }
  // 年の数も多すぎるときは、何年かおきにする
  const years = monthStarts.filter((c) => c.month === 1);
  const every = Math.ceil(years.length / maxTicks);
  return years
    .filter((_, i) => i % every === 0)
    .map((c) => ({ index: c.index, label: `${c.year}年`, major: true }));
}

/** 短い期間の目盛り:最初と最後を除いて、日付を等間隔に置く。 */
function dayTicks(dates: readonly string[], count: number): DateTick[] {
  const n = dates.length;
  if (n < 3) return [];
  const ticks: DateTick[] = [];
  const seen = new Set<number>();
  for (let k = 1; k <= count; k += 1) {
    const index = Math.round((k * (n - 1)) / (count + 1));
    if (index <= 0 || index >= n - 1 || seen.has(index)) continue;
    seen.add(index);
    const [, m, d] = dates[index].split("-").map(Number);
    ticks.push({ index, label: `${m}/${d}`, major: false });
  }
  return ticks;
}

/** ピクセル位置に一番近いデータの番号。 */
export function nearestIndex(scale: Scale, pixel: number, length: number): number {
  const i = Math.round(scale.invert(pixel));
  return Math.min(length - 1, Math.max(0, i));
}
