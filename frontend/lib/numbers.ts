// 入力欄の文字 → 数値と、メッセージに入れる数値の書き方。条件の入力欄(form.ts)と総当たりの入力欄(sweep.ts)で共有する。

// 受け付ける数値の形:符号・整数部・小数部・指数(1e6 など)。16進("0x10")や "Infinity" は受け付けない
const NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
// カンマは3桁区切りの位置だけ(1,000,000)。「0,1」「1,5」「0,005」のような打ち間違いを、黙って別の数にしないため
// (最初のまとまりは 0 で始まらない。「0,005」を 5 と読まない)
const GROUPED = /^[+-]?[1-9]\d{0,2}(?:,\d{3})+(?:\.\d*)?$/;

/**
 * 入力欄の文字を数値にする。読めなければ null。
 * 全角数字・全角カンマ・3桁区切りのカンマ(1,000,000)・前後の空白は受け付ける。
 * マイナスは "-" のほか、画面の表示に使っている「−」(U+2212)と全角の「-」も受け付ける。
 */
export function toNumber(text: string): number | null {
  let normalized = text.normalize("NFKC").replaceAll("−", "-").trim();
  if (normalized.includes(",")) {
    if (!GROUPED.test(normalized)) return null;
    normalized = normalized.replaceAll(",", "");
  }
  if (!NUMBER.test(normalized)) return null;
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

/** メッセージに入れる数値(1000000000 → "10億"、1000 → "1000")。API と同じ書き方。 */
export function numberText(value: number): string {
  if (value >= 1e8 && value % 1e8 === 0) return `${value / 1e8}億`;
  return String(value);
}
