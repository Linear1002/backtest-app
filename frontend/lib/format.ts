// 数値・日付を日本語の表示にする。表示専用(計算には使わない)。

const yen = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
const yen2 = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

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
  if (!signed) return `${pct < 0 ? "−" : ""}${text}%`;
  if (Number(text) === 0) return `±${text}%`;
  return `${pct > 0 ? "+" : "−"}${text}%`;
}

/** 小数(シャープレシオなど)。null は「算出不可」。 */
export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "算出不可";
  return `${value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}`;
}

/** 株数(1,200株)。 */
export function formatShares(value: number): string {
  return `${yen.format(value)}株`;
}

/** 軸用の短い円表記(12万 / 1.2億 / 4,000)。 */
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

/** 1,000,000 → 「100万円」のような補助表示。 */
export function describeYen(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "";
  if (value >= 1e8) return `${trim(value / 1e8)}億円`;
  if (value >= 1e4) return `${trim(value / 1e4)}万円`;
  return `${yen.format(value)}円`;
}

/** 損益の向き。日本の習慣どおり、プラス=朱、マイナス=藍。 */
export function direction(value: number | null | undefined): "up" | "down" | "flat" {
  if (value === null || value === undefined || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}
