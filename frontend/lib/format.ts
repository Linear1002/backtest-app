// 数値・日付を日本語の表示にする。表示専用(計算には使わない)。
// TODO(複数市場):いまは東証だけなので通貨を「円」で固定している。市場を増やすときは market.currency から単位を決める

const yen = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
const yen2 = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
// 率や係数を指数表記(1e-7 など)にせず、意味のある桁まで書く
const plain = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 8, useGrouping: false });

/** 1,234,567円(小数は四捨五入)。 */
export function formatYen(value: number): string {
  return `${yen.format(Math.round(value))}円`;
}

/** 株価など、小数があり得る金額(最大小数2桁)。 */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return "−";
  return yen2.format(value);
}

/** 符号付きの円(+12,345円 / −12,345円)。マイナスは全角の「−」を使う。 */
export function formatSignedYen(value: number): string {
  // 0.5 は 0 から遠い方に丸める(Math.round は −1234.5 を −1234 にしてしまうため)
  const rounded = Math.sign(value) * Math.round(Math.abs(value));
  if (rounded === 0) return "±0円";
  return `${rounded > 0 ? "+" : "−"}${yen.format(Math.abs(rounded))}円`;
}

/** 割合 → パーセント(0.1234 → 12.34%)。null は「算出不可」。 */
export function formatPercent(
  ratio: number | null | undefined,
  { digits = 2, signed = false, nullLabel = "算出不可" } = {},
): string {
  if (ratio === null || ratio === undefined) return nullLabel;
  const pct = ratio * 100;
  const text = Math.abs(pct).toFixed(digits);
  if (!signed) return `${pct < 0 && Number(text) !== 0 ? "−" : ""}${text}%`;
  if (Number(text) === 0) return `±${text}%`;
  return `${pct > 0 ? "+" : "−"}${text}%`;
}

/** 入力された率(%)をそのまま書く(0.1 → 0.1%、0.0000001 → 0.0000001%)。指数表記にしない。 */
export function formatRatePct(pct: number): string {
  return `${plain.format(pct)}%`;
}

/** 調整係数・端数の株数など、桁数が決まっていない小数(最大8桁)。 */
export function formatDecimal(value: number): string {
  return plain.format(value);
}

/** 小数(シャープレシオなど)。null は「算出不可」。 */
export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "算出不可";
  const text = Math.abs(value).toFixed(digits);
  return `${value < 0 && Number(text) !== 0 ? "−" : ""}${text}`;
}

/** 株数(1,200株)。 */
export function formatShares(value: number): string {
  return `${yen.format(value)}株`;
}

/** 軸用の短い円表記(12万 / 1.2億 / 4,000)。目盛りには axisLabels を使う。 */
export function formatYenCompact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1e8) return `${sign}${trim(abs / 1e8)}億`;
  if (abs >= 1e4) return `${sign}${trim(abs / 1e4)}万`;
  return `${sign}${yen.format(abs)}`;
}

function trim(n: number): string {
  const fixed = n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2);
  // 小数点以下の末尾の 0 だけを消す(150 の 0 は消さない)
  return fixed.includes(".") ? fixed.replace(/\.?0+$/, "") : fixed;
}

/** step を正確に書くのに必要な小数の桁数(0.25 → 2、2.5 → 1、500 → 0)。 */
function decimalsFor(step: number): number {
  for (let digits = 0; digits <= 8; digits += 1) {
    const scaled = step * 10 ** digits;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-6 * Math.max(1, Math.abs(scaled))) return digits;
  }
  return 8;
}

/**
 * 目盛りの数字。目盛りの間隔(step)から桁数を決め、全部の目盛りを同じ単位・同じ桁数で書く。
 * - yen:0 以外の目盛りがすべて1万以上なら「万」、すべて1億以上なら「億」の単位にそろえる
 *   (例:95万・97.5万・100万 → 95.0万・97.5万・100.0万。5,000・7,500・10,000 は万にしない)
 * - percent:割合を % にし、0 以外はマイナス(ドローダウンは下向き)
 */
export function axisLabels(ticks: readonly number[], step: number, kind: "yen" | "percent"): string[] {
  if (kind === "percent") {
    const digits = decimalsFor(step * 100);
    return ticks.map((v) => (v === 0 ? "0%" : `−${(Math.abs(v) * 100).toFixed(digits)}%`));
  }
  const nonzero = ticks.filter((v) => v !== 0).map(Math.abs);
  const minAbs = nonzero.length ? Math.min(...nonzero) : 0;
  const [unit, suffix] = minAbs >= 1e8 ? [1e8, "億"] : minAbs >= 1e4 ? [1e4, "万"] : [1, ""];
  const digits = decimalsFor(step / unit);
  const format = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return ticks.map((v) => `${v < 0 ? "−" : ""}${format.format(Math.abs(v) / unit)}${suffix}`);
}

const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

/** 2025-04-01 → 2025年4月1日(火) */
export function formatDateLong(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${y}年${m}月${d}日(${WEEKDAYS[day]})`;
}

/** 2025-04-01 → 2025/04/01 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "−";
  return iso.replaceAll("-", "/");
}

const tokyo = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** タイムゾーン付きの日時(API は UTC で返す)→ 日本時間の「2026/10/24 07:30」。 */
export function formatDateTimeJst(iso: string | null | undefined): string {
  if (!iso) return "−";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "−";
  const parts = Object.fromEntries(tokyo.formatToParts(date).map((p) => [p.type, p.value]));
  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`;
}

/** 1,000,000 → 「100万円」、1,234,567 → 「約123万円」のような補助表示。ちょうどでないときは「約」を付ける。 */
export function describeYen(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "";
  const [unit, suffix] = value >= 1e8 ? [1e8, "億円"] : value >= 1e4 ? [1e4, "万円"] : [1, "円"];
  if (unit === 1) return `${yen.format(value)}円`;
  const text = trim(value / unit);
  return `${Number(text) * unit === value ? "" : "約"}${text}${suffix}`;
}

/** 損益の向き。日本の習慣どおり、プラス=朱、マイナス=藍。 */
export function direction(value: number | null | undefined): "up" | "down" | "flat" {
  if (value === null || value === undefined || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}
