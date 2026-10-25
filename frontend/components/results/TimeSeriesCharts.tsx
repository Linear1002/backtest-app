"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { BacktestResult, CorporateAction } from "@/lib/api.ts";
import { areaPath, dateTicks, linearScale, linePath, nearestIndex, niceScale, paddedExtent } from "@/lib/chart.ts";
import { axisLabels, formatDateLong, formatDecimal, formatPercent, formatPrice, formatYen } from "@/lib/format.ts";

import { SvgSeal } from "../Seal.tsx";

type Props = { result: BacktestResult; actions: CorporateAction[]; animate: boolean };

/** Shift+矢印・PageUp/PageDown で動かす日数 */
const BIG_STEP = 20;

const MARGIN = { left: 60, right: 14 };
const LABEL = 22; // パネルの上の見出しの高さ
const GAP = 14;
const AXIS = 26;

function useWidth<T extends HTMLElement>(fallback = 860) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(300, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function TimeSeriesCharts({ result, actions, animate }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const daily = result.daily;
  const n = daily.length;
  const [hover, setHover] = useState<number | null>(null);
  const index = hover ?? n - 1;
  const compact = width < 640;
  // 比較の買い持ち(docs/benchmark.md)は、買えたときだけ資産額の段に点線で描く
  const showBenchmark = result.benchmark.status === "bought";

  const heights = compact ? { price: 210, equity: 120, dd: 80 } : { price: 290, equity: 150, dd: 96 };
  const top = {
    price: LABEL,
    equity: LABEL + heights.price + GAP + LABEL,
    dd: LABEL + heights.price + GAP + LABEL + heights.equity + GAP + LABEL,
  };
  const totalHeight = top.dd + heights.dd + AXIS;

  const dateIndex = useMemo(() => new Map(daily.map((d, i) => [d.date, i])), [daily]);

  const geometry = useMemo(() => {
    const x = linearScale([0, Math.max(1, n - 1)], [MARGIN.left, width - MARGIN.right]);

    const priceValues: number[] = [];
    for (const d of daily) {
      if (d.close !== null) priceValues.push(d.close);
      if (d.short_ma !== null) priceValues.push(d.short_ma);
      if (d.long_ma !== null) priceValues.push(d.long_ma);
    }
    for (const f of result.fills) priceValues.push(f.fill_price);
    const [pMin, pMax] = paddedExtent(priceValues);
    const yPrice = linearScale([pMin, pMax], [top.price + heights.price, top.price]);

    const equityValues = daily.map((d) => d.equity).concat(result.params.initial_cash);
    if (showBenchmark) for (const d of daily) equityValues.push(d.benchmark_equity);
    const [eMin, eMax] = paddedExtent(equityValues);
    const yEquity = linearScale([eMin, eMax], [top.equity + heights.equity, top.equity]);

    const ddMax = Math.max(0.01, ...daily.map((d) => d.drawdown)) * 1.08;
    const yDd = linearScale([0, ddMax], [top.dd, top.dd + heights.dd]);

    // 分割・併合で持ち株数が変わる日は、株価(未調整)と移動平均の線を切る(値動きではないため)。
    // エンジンと同じ条件(ExRT が1か2で、係数が1でない日。docs/mvp.md 2.8)を API が changes_shares で返す
    const breaks = new Set(actions.filter((a) => a.changes_shares).map((a) => a.date));
    const series = (
      pick: (i: number) => number | null,
      y: (v: number) => number,
      breakAtActions = false,
    ) => {
      const points: ((readonly [number, number]) | null)[] = [];
      daily.forEach((d, i) => {
        if (breakAtActions && breaks.has(d.date)) points.push(null);
        const v = pick(i);
        points.push(v === null ? null : ([x(i), y(v)] as const));
      });
      return linePath(points);
    };

    // 目盛りの数字は、目盛りの間隔から桁数を決めてそろえる(102.5万を「103万」と書かないように)
    const priceScale = niceScale(pMin, pMax, compact ? 3 : 5);
    const equityScale = niceScale(eMin, eMax, compact ? 3 : 4);
    const ddScale = niceScale(0, ddMax, 2);
    const ticks = (scale: { ticks: number[]; step: number }, kind: "yen" | "percent") => {
      const labels = axisLabels(scale.ticks, scale.step, kind);
      return scale.ticks.map((value, i) => ({ value, label: labels[i] }));
    };

    return {
      x,
      yPrice,
      yEquity,
      yDd,
      priceTicks: ticks(priceScale, "yen"),
      equityTicks: ticks(equityScale, "yen"),
      ddTicks: ticks(ddScale, "percent"),
      closePath: series((i) => daily[i].close, yPrice, true),
      shortPath: series((i) => daily[i].short_ma, yPrice, true),
      longPath: series((i) => daily[i].long_ma, yPrice, true),
      equityPath: series((i) => daily[i].equity, yEquity),
      benchmarkPath: showBenchmark ? series((i) => daily[i].benchmark_equity, yEquity) : null,
      equityArea: areaPath(daily.map((d, i) => [x(i), yEquity(d.equity)] as const), top.equity + heights.equity),
      ddPath: series((i) => daily[i].drawdown, yDd),
      ddArea: areaPath(daily.map((d, i) => [x(i), yDd(d.drawdown)] as const), top.dd),
      xTicks: dateTicks(daily.map((d) => d.date), compact ? 4 : 8),
    };
  }, [daily, n, width, compact, actions, result.fills, result.params.initial_cash, showBenchmark, heights.price, heights.equity, heights.dd, top.price, top.equity, top.dd]);

  const { x, yPrice, yEquity, yDd } = geometry;
  // 印の大きさ:同じ向き(買い同士・売り同士)の印がいちばん近いときの間隔に合わせて小さくする
  const sealRadius = useMemo(() => {
    let minGap = Infinity;
    for (const side of ["buy", "sell"] as const) {
      const xs = result.fills
        .filter((f) => f.side === side)
        .map((f) => x(dateIndex.get(f.date) ?? 0));
      for (let k = 1; k < xs.length; k += 1) minGap = Math.min(minGap, xs[k] - xs[k - 1]);
    }
    return Math.max(6, Math.min(compact ? 7 : 9, minGap / 2.3));
  }, [result.fills, x, dateIndex, compact]);
  const current = daily[index];

  function pickIndex(clientX: number, target: SVGSVGElement) {
    const rect = target.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * width;
    setHover(nearestIndex(x, px, n));
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const step = e.shiftKey ? BIG_STEP : 1;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") setHover(Math.max(0, index - step));
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") setHover(Math.min(n - 1, index + step));
    else if (e.key === "PageDown") setHover(Math.max(0, index - BIG_STEP));
    else if (e.key === "PageUp") setHover(Math.min(n - 1, index + BIG_STEP));
    else if (e.key === "Home") setHover(0);
    else if (e.key === "End") setHover(n - 1);
    else return;
    e.preventDefault();
  }

  // マウスが離れたら最終日の表示に戻す。タッチは指を離しても、選んだ日のままにする
  function onPointerLeave(e: React.PointerEvent) {
    if (e.pointerType === "mouse") setHover(null);
  }

  // 読み上げ用:いま選んでいる日の数値(スライダーの値として伝える)
  const valueText = [
    formatDateLong(current.date),
    `終値 ${current.close === null ? "売買なし" : `${formatPrice(current.close)}円`}`,
    `資産額 ${formatYen(current.equity)}`,
    ...(showBenchmark ? [`買い持ちの資産額 ${formatYen(current.benchmark_equity)}`] : []),
    `ドローダウン ${formatPercent(current.drawdown, { digits: 1 })}`,
    `株数 ${current.shares.toLocaleString("ja-JP")}株`,
  ].join("、");

  return (
    <figure className="m-0">
      <Legend result={result} />
      <Readout result={result} index={index} />
      {/* キーボードと読み上げでは「日付を選ぶスライダー」として扱う(数値は aria-valuetext で伝える) */}
      <div
        ref={ref}
        className="relative mt-2 touch-pan-y outline-none focus-visible:ring-2 focus-visible:ring-[var(--ai)]"
        tabIndex={0}
        role="slider"
        aria-label="チャートの日付"
        aria-valuemin={0}
        aria-valuemax={Math.max(0, n - 1)}
        aria-valuenow={index}
        aria-valuetext={valueText}
        onKeyDown={onKeyDown}
      >
        <svg
          width="100%"
          viewBox={`0 0 ${width} ${totalHeight}`}
          className="block overflow-visible"
          onPointerMove={(e) => pickIndex(e.clientX, e.currentTarget)}
          onPointerDown={(e) => pickIndex(e.clientX, e.currentTarget)}
          onPointerLeave={onPointerLeave}
          aria-hidden="true"
        >
          {/* 縦の目盛り線(日付) */}
          {geometry.xTicks.flatMap((t) =>
            (
              [
                [top.price, heights.price],
                [top.equity, heights.equity],
                [top.dd, heights.dd],
              ] as const
            ).map(([y0, h]) => (
              <line
                key={`v-${t.index}-${y0}`}
                x1={x(t.index)}
                x2={x(t.index)}
                y1={y0}
                y2={y0 + h}
                stroke="var(--rule)"
                strokeWidth={1}
              />
            )),
          )}

          {/* --- 株価と移動平均 --- */}
          <PanelLabel x={MARGIN.left} y={top.price} text="株価(円)" />
          {geometry.priceTicks.map((t) => (
            <HTick key={`p-${t.value}`} y={yPrice(t.value)} left={MARGIN.left} right={width - MARGIN.right} label={t.label} />
          ))}
          {actions.map((a) => {
            const i = dateIndex.get(a.date);
            if (i === undefined) return null;
            const nearRight = x(i) > width - 140;
            return (
              <g key={`ev-${a.date}`}>
                <line x1={x(i)} x2={x(i)} y1={top.price} y2={top.price + heights.price} stroke="var(--rule-strong)" strokeWidth={1} />
                <text
                  x={nearRight ? x(i) - 5 : x(i) + 5}
                  y={top.price + 12}
                  textAnchor={nearRight ? "end" : "start"}
                  fontSize={11}
                  fill="var(--ink-2)"
                  stroke="var(--surface)"
                  strokeWidth={4}
                  paintOrder="stroke"
                >
                  {a.label}(係数 {formatDecimal(a.adj_factor)})
                </text>
              </g>
            );
          })}
          <path d={geometry.closePath} fill="none" stroke="var(--price)" strokeWidth={1.25} strokeLinejoin="round" strokeLinecap="round" opacity={0.85} />
          <path d={geometry.longPath} fill="none" stroke="var(--ma-long)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          <path d={geometry.shortPath} fill="none" stroke="var(--ma-short)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {result.fills.map((f, k) => {
            const i = dateIndex.get(f.date);
            if (i === undefined) return null;
            return (
              <SvgSeal
                key={`f-${f.date}-${f.side}`}
                kind={f.side}
                x={x(i)}
                // 買いは約定価格の少し下、売りは少し上に押す(線と重ならないように)
                y={yPrice(f.fill_price) + (f.side === "buy" ? 1 : -1) * (sealRadius + 4)}
                r={sealRadius}
                delay={Math.min(k * 22, 900)}
                animate={animate}
              />
            );
          })}

          {/* --- 資産額 --- */}
          <PanelLabel x={MARGIN.left} y={top.equity} text="資産額(円)" />
          {geometry.equityTicks.map((t) => (
            <HTick key={`e-${t.value}`} y={yEquity(t.value)} left={MARGIN.left} right={width - MARGIN.right} label={t.label} />
          ))}
          <line
            x1={MARGIN.left}
            x2={width - MARGIN.right}
            y1={yEquity(result.params.initial_cash)}
            y2={yEquity(result.params.initial_cash)}
            stroke="var(--ink-3)"
            strokeWidth={1}
          />
          <text x={width - MARGIN.right} y={yEquity(result.params.initial_cash) - 4} textAnchor="end" fontSize={11} fill="var(--ink-3)">
            初期資金
          </text>
          <path d={geometry.equityArea} fill="var(--ink)" opacity={0.06} />
          {geometry.benchmarkPath && (
            // 比較の買い持ち:灰色の点線(色だけでなく線の形でも見分けられるように)
            <path
              d={geometry.benchmarkPath}
              fill="none"
              stroke="var(--ink-3)"
              strokeWidth={1.5}
              strokeDasharray="5 4"
              strokeLinejoin="round"
            />
          )}
          <path
            d={geometry.equityPath}
            fill="none"
            stroke="var(--ink)"
            strokeWidth={2}
            strokeLinejoin="round"
            className={animate ? "draw-in" : undefined}
            pathLength={animate ? 1 : undefined}
            style={animate ? { ["--path-length" as string]: 1 } : undefined}
          />

          {/* --- ドローダウン --- */}
          <PanelLabel x={MARGIN.left} y={top.dd} text="ドローダウン" />
          {geometry.ddTicks.map((t) => (
            <HTick key={`d-${t.value}`} y={yDd(t.value)} left={MARGIN.left} right={width - MARGIN.right} label={t.label} />
          ))}
          <path d={geometry.ddArea} fill="var(--ai)" opacity={0.12} />
          <path d={geometry.ddPath} fill="none" stroke="var(--ai)" strokeWidth={1.5} strokeLinejoin="round" />

          {/* 日付の目盛り */}
          {geometry.xTicks.map((t) => (
            <text
              key={`xt-${t.index}`}
              x={x(t.index)}
              y={top.dd + heights.dd + 18}
              textAnchor="middle"
              fontSize={12}
              fill={t.major ? "var(--ink-2)" : "var(--ink-3)"}
              className="tabular"
            >
              {t.label}
            </text>
          ))}

          {/* 十字線 */}
          {hover !== null && (
            <g pointerEvents="none">
              <line x1={x(index)} x2={x(index)} y1={top.price} y2={top.dd + heights.dd} stroke="var(--ink-2)" strokeWidth={1} />
              {current.close !== null && <Dot x={x(index)} y={yPrice(current.close)} color="var(--price)" />}
              {showBenchmark && <Dot x={x(index)} y={yEquity(current.benchmark_equity)} color="var(--ink-3)" />}
              <Dot x={x(index)} y={yEquity(current.equity)} color="var(--ink)" />
              <Dot x={x(index)} y={yDd(current.drawdown)} color="var(--ai)" />
            </g>
          )}
        </svg>
      </div>
      <figcaption className="mt-2 text-[12px] leading-6 text-ink-3">
        横軸は営業日(休場日のすき間は詰めています)。株価は分割前後でそのまま(未調整)、移動平均はその日までに分かる情報で調整した値です。
        チャートを選んで、矢印キーで1日ずつ、Shift+矢印キーで{BIG_STEP}日ずつ、Home・End で最初と最後の日に動かせます。
      </figcaption>
    </figure>
  );
}

function PanelLabel({ x, y, text }: { x: number; y: number; text: string }) {
  return (
    <text x={x} y={y - 8} fontSize={12} fill="var(--ink-2)" fontWeight={700}>
      {text}
    </text>
  );
}

function HTick({ y, left, right, label }: { y: number; left: number; right: number; label: string }) {
  return (
    <g>
      <line x1={left} x2={right} y1={y} y2={y} stroke="var(--rule)" strokeWidth={1} />
      <text x={left - 8} y={y} textAnchor="end" dominantBaseline="middle" fontSize={12} fill="var(--ink-3)" className="tabular">
        {label}
      </text>
    </g>
  );
}

function Dot({ x, y, color }: { x: number; y: number; color: string }) {
  return (
    <g>
      <circle cx={x} cy={y} r={6} fill="var(--surface)" />
      <circle cx={x} cy={y} r={4} fill={color} />
    </g>
  );
}

function LineKey({ color }: { color: string }) {
  return <span className="inline-block h-0.5 w-4 rounded" style={{ background: color }} aria-hidden="true" />;
}

function DashedKey() {
  return (
    <svg width="16" height="4" aria-hidden="true" className="inline-block">
      <line x1="0" x2="16" y1="2" y2="2" stroke="var(--ink-3)" strokeWidth="1.5" strokeDasharray="5 4" />
    </svg>
  );
}

function Legend({ result }: { result: BacktestResult }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px] text-ink-2">
      <span className="inline-flex items-center gap-1.5">
        <LineKey color="var(--price)" />
        終値
      </span>
      <span className="inline-flex items-center gap-1.5">
        <LineKey color="var(--ma-short)" />
        短期線({result.params.short_window}日)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <LineKey color="var(--ma-long)" />
        長期線({result.params.long_window}日)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="seal seal-buy" style={{ width: 16, height: 16, fontSize: 10 }} aria-hidden="true">
          買
        </span>
        買いの約定
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="seal seal-sell" style={{ width: 16, height: 16, fontSize: 10 }} aria-hidden="true">
          売
        </span>
        売りの約定
      </span>
      {result.benchmark.status === "bought" && (
        <span className="inline-flex items-center gap-1.5">
          <DashedKey />
          買い持ちの資産額(比較)
        </span>
      )}
    </div>
  );
}

/** 上の読み取り欄。読み上げはチャートのスライダー(aria-valuetext)が受け持つので、ここは見た目だけにする。 */
function Readout({ result, index }: { result: BacktestResult; index: number }) {
  const d = result.daily[index];
  const item = (label: string, value: string, color?: string) => (
    <span className="inline-flex items-baseline gap-1.5">
      {color && <LineKey color={color} />}
      <span className="text-ink-3">{label}</span>
      <span className="font-bold text-ink">{value}</span>
    </span>
  );
  return (
    <div className="mt-3 flex min-h-[3.25rem] flex-wrap items-baseline gap-x-4 gap-y-0.5 rounded-md bg-surface-2 px-3 py-2 text-[13px] tabular" aria-hidden="true">
      <span className="font-bold text-ink">{formatDateLong(d.date)}</span>
      {item("終値", d.close === null ? "売買なし" : formatPrice(d.close), "var(--price)")}
      {item("短期線", formatPrice(d.short_ma), "var(--ma-short)")}
      {item("長期線", formatPrice(d.long_ma), "var(--ma-long)")}
      {item("資産額", formatYen(d.equity), "var(--ink)")}
      {result.benchmark.status === "bought" && (
        <span className="inline-flex items-baseline gap-1.5">
          <DashedKey />
          <span className="text-ink-3">買い持ち</span>
          <span className="font-bold text-ink">{formatYen(d.benchmark_equity)}</span>
        </span>
      )}
      {item("ドローダウン", formatPercent(d.drawdown, { digits: 1 }), "var(--ai)")}
      {item("株数", `${d.shares.toLocaleString("ja-JP")}株`)}
    </div>
  );
}
