// 印(判子)。約定は「買」「売」の印で表す。アプリの印は「検」(検印=確かめた印)。

type SealProps = {
  kind: "buy" | "sell" | "check";
  size?: number;
  outline?: boolean;
  title?: string;
  /** 飾りとして置く(読み上げない)。見出しやボタンの文字と同じ意味のときに使う */
  decorative?: boolean;
};

const CHAR = { buy: "買", sell: "売", check: "検" } as const;
const LABEL = { buy: "買い", sell: "売り", check: "検" } as const;

export function Seal({ kind, size = 22, outline = false, title, decorative = false }: SealProps) {
  const className = [
    "seal",
    outline ? "seal-outline" : kind === "sell" ? "seal-sell" : "seal-buy",
  ].join(" ");
  const a11y = decorative
    ? { "aria-hidden": true as const }
    : { role: "img" as const, "aria-label": title ?? LABEL[kind], title };
  return (
    <span className={className} style={{ width: size, height: size, fontSize: Math.round(size * 0.58) }} {...a11y}>
      <span aria-hidden="true">{CHAR[kind]}</span>
    </span>
  );
}

/** SVG の中に置く印(チャート用)。中心が (x, y)。 */
export function SvgSeal({
  kind,
  x,
  y,
  r = 9,
  delay = 0,
  animate = false,
}: {
  kind: "buy" | "sell";
  x: number;
  y: number;
  r?: number;
  delay?: number;
  animate?: boolean;
}) {
  return (
    <g
      className={animate ? "stamp-in" : undefined}
      style={{ ["--stamp-delay" as string]: delay }}
      aria-hidden="true"
    >
      <circle cx={x} cy={y} r={r + 2} fill="var(--surface)" />
      <circle cx={x} cy={y} r={r} fill={kind === "buy" ? "var(--shu)" : "var(--ai)"} />
      <text
        x={x}
        y={y}
        textAnchor="middle"
        dominantBaseline="central"
        fontFamily="var(--font-seal)"
        fontWeight={700}
        fontSize={r * 1.15}
        fill="var(--seal-ink)"
      >
        {kind === "buy" ? "買" : "売"}
      </text>
    </g>
  );
}
