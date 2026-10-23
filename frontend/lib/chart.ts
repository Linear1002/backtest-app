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

/** 1・2・2.5・5 × 10^n の「きりのいい」目盛り。 */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
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
  return ticks;
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

/** 折れ線のパス。null の点で線を切る(売買不成立の日など)。 */
export function linePath(points: ReadonlyArray<readonly [number, number] | null>): string {
  let d = "";
  let drawing = false;
  for (const p of points) {
    if (p === null) {
      drawing = false;
      continue;
    }
    d += `${drawing ? "L" : "M"}${round(p[0])},${round(p[1])}`;
    drawing = true;
  }
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
  const steps = [1, 3, 6, 12];
  for (const step of steps) {
    const picked = candidates.filter((c) => (c.month - 1) % step === 0);
    if (picked.length <= maxTicks) {
      return picked
        .filter((c) => c.index > 0 || dates.length === 1)
        .map((c) => ({
          index: c.index,
          label: c.month === 1 ? `${c.year}年` : `${c.month}月`,
          major: c.month === 1,
        }));
    }
  }
  const years = candidates.filter((c) => c.month === 1);
  const every = Math.ceil(years.length / maxTicks);
  return years
    .filter((_, i) => i % every === 0)
    .map((c) => ({ index: c.index, label: `${c.year}年`, major: true }));
}

/** ピクセル位置に一番近いデータの番号。 */
export function nearestIndex(scale: Scale, pixel: number, length: number): number {
  const i = Math.round(scale.invert(pixel));
  return Math.min(length - 1, Math.max(0, i));
}
