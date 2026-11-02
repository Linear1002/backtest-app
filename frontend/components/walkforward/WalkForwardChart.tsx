"use client";

// ウォークフォワード分析の、つないだ資産額と買い持ちの資産額のチャート(docs/walkforward.md 6章)。
// 区切り(使う期間)ごとに背景を交互に塗り分け、どの日がどの区切りの、どの日数で売買した結果かを読み取れるようにする。

import { useEffect, useMemo, useRef, useState } from "react";

import type { WalkForwardResult } from "@/lib/api.ts";
import { dateTicks, linearScale, linePath, nearestIndex, niceScale, paddedExtent } from "@/lib/chart.ts";
import { axisLabels, formatDateLong, formatYen } from "@/lib/format.ts";

/** Shift+矢印・PageUp/PageDown で動かす日数 */
const BIG_STEP = 20;
const MARGIN = { left: 64, right: 14, top: 26, bottom: 28 };
/** 区切りの番号を書くのは、区切りがこの数以下のとき(多いと重なって読めない) */
const MAX_LABELED_WINDOWS = 12;

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

/** 日ごとに、その日が属する区切り(windows の中の位置)。 */
export function windowOfDay(result: WalkForwardResult): number[] {
  const out: number[] = [];
  let w = 0;
  for (const d of result.daily) {
    while (w < result.windows.length - 1 && d.date > result.windows[w].out_of_sample.end_date) w += 1;
    out.push(w);
  }
  return out;
}

function choiceText(result: WalkForwardResult, w: number): string {
  const chosen = result.windows[w].chosen;
  return chosen ? `短期${chosen.short_window}日・長期${chosen.long_window}日` : "選ばず(現金のまま)";
}

export function WalkForwardChart({ result }: { result: WalkForwardResult }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const daily = result.daily;
  const n = daily.length;
  const [hover, setHover] = useState<number | null>(null);
  const index = hover ?? n - 1;
  const compact = width < 640;
  const height = compact ? 220 : 300;
  const showBenchmark = result.benchmark.status === "bought";
  const owner = useMemo(() => windowOfDay(result), [result]);

  const geometry = useMemo(() => {
    const x = linearScale([0, Math.max(1, n - 1)], [MARGIN.left, width - MARGIN.right]);
    const values = daily.map((d) => d.equity).concat(result.params.initial_cash);
    if (showBenchmark) for (const d of daily) values.push(d.benchmark_equity);
    const [min, max] = paddedExtent(values);
    const y = linearScale([min, max], [MARGIN.top + height, MARGIN.top]);
    const scale = niceScale(min, max, compact ? 3 : 5);
    const labels = axisLabels(scale.ticks, scale.step, "yen");
    // 区切りの帯:その区切りの最初の日から、次の区切りの最初の日まで(半日ずつ広げて、すき間なく並べる)
    const half = n > 1 ? (x(1) - x(0)) / 2 : 0;
    const bands: { w: number; x0: number; x1: number }[] = [];
    owner.forEach((w, i) => {
      if (i === 0 || owner[i - 1] !== w) bands.push({ w, x0: Math.max(MARGIN.left, x(i) - half), x1: x(i) + half });
      else bands[bands.length - 1].x1 = Math.min(width - MARGIN.right, x(i) + half);
    });
    return {
      x,
      y,
      ticks: scale.ticks.map((value, i) => ({ value, label: labels[i] })),
      equityPath: linePath(daily.map((d, i) => [x(i), y(d.equity)] as const)),
      benchmarkPath: showBenchmark ? linePath(daily.map((d, i) => [x(i), y(d.benchmark_equity)] as const)) : null,
      bands,
      xTicks: dateTicks(
        daily.map((d) => d.date),
        compact ? 4 : 8,
      ),
    };
  }, [daily, n, width, height, compact, owner, result.params.initial_cash, showBenchmark]);

  const { x, y } = geometry;
  const current = daily[index];
  const currentWindow = owner[index];

  function pickIndex(clientX: number, target: SVGSVGElement) {
    const rect = target.getBoundingClientRect();
    setHover(nearestIndex(x, ((clientX - rect.left) / rect.width) * width, n));
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

  const valueText = [
    formatDateLong(current.date),
    `区切り${result.windows[currentWindow].index}(${choiceText(result, currentWindow)})`,
    `資産額 ${formatYen(current.equity)}`,
    ...(showBenchmark ? [`買い持ちの資産額 ${formatYen(current.benchmark_equity)}`] : []),
  ].join("、");

  return (
    <figure className="m-0">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px] text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded bg-ink" aria-hidden="true" />
          つないだ資産額
        </span>
        {showBenchmark && (
          <span className="inline-flex items-center gap-1.5">
            <svg width="16" height="4" aria-hidden="true" className="inline-block">
              <line x1="0" x2="16" y1="2" y2="2" stroke="var(--ink-3)" strokeWidth="1.5" strokeDasharray="5 4" />
            </svg>
            買い持ちの資産額(比較)
          </span>
        )}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-sm bg-rule/50 ring-1 ring-rule" aria-hidden="true" />
          区切り(使う期間)ごとに背景を塗り分け
        </span>
      </div>
      <div
        className="mt-3 flex min-h-[3.25rem] flex-wrap items-baseline gap-x-4 gap-y-0.5 rounded-md bg-surface-2 px-3 py-2 text-[13px] tabular"
        aria-hidden="true"
      >
        <span className="font-bold text-ink">{formatDateLong(current.date)}</span>
        <span>
          <span className="text-ink-3">区切り{result.windows[currentWindow].index} </span>
          <span className="font-bold text-ink">{choiceText(result, currentWindow)}</span>
        </span>
        <span>
          <span className="text-ink-3">資産額 </span>
          <span className="font-bold text-ink">{formatYen(current.equity)}</span>
        </span>
        {showBenchmark && (
          <span>
            <span className="text-ink-3">買い持ち </span>
            <span className="font-bold text-ink">{formatYen(current.benchmark_equity)}</span>
          </span>
        )}
      </div>
      {/* キーボードと読み上げでは「日付を選ぶスライダー」として扱う(数値は aria-valuetext で伝える) */}
      <div
        ref={ref}
        className="relative mt-2 touch-pan-y outline-none focus-visible:ring-2 focus-visible:ring-[var(--ai)]"
        tabIndex={0}
        role="slider"
        aria-label="ウォークフォワードのチャートの日付"
        aria-valuemin={0}
        aria-valuemax={Math.max(0, n - 1)}
        aria-valuenow={index}
        aria-valuetext={valueText}
        onKeyDown={onKeyDown}
      >
        <svg
          width="100%"
          viewBox={`0 0 ${width} ${MARGIN.top + height + MARGIN.bottom}`}
          className="block overflow-visible"
          onPointerMove={(e) => pickIndex(e.clientX, e.currentTarget)}
          onPointerDown={(e) => pickIndex(e.clientX, e.currentTarget)}
          onPointerLeave={(e) => {
            if (e.pointerType === "mouse") setHover(null);
          }}
          aria-hidden="true"
        >
          {geometry.bands.map((b) => (
            <g key={`band-${b.w}`}>
              {b.w % 2 === 1 && (
                <rect x={b.x0} y={MARGIN.top} width={Math.max(0, b.x1 - b.x0)} height={height} fill="var(--rule)" opacity={0.5} />
              )}
              {result.windows.length <= MAX_LABELED_WINDOWS && b.x1 - b.x0 > 22 && (
                <text x={(b.x0 + b.x1) / 2} y={MARGIN.top - 8} textAnchor="middle" fontSize={11} fill="var(--ink-3)" className="tabular">
                  {result.windows[b.w].index}
                </text>
              )}
            </g>
          ))}
          {geometry.ticks.map((t) => (
            <g key={`t-${t.value}`}>
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(t.value)} y2={y(t.value)} stroke="var(--rule)" strokeWidth={1} />
              <text x={MARGIN.left - 8} y={y(t.value)} textAnchor="end" dominantBaseline="middle" fontSize={12} fill="var(--ink-3)" className="tabular">
                {t.label}
              </text>
            </g>
          ))}
          <line
            x1={MARGIN.left}
            x2={width - MARGIN.right}
            y1={y(result.params.initial_cash)}
            y2={y(result.params.initial_cash)}
            stroke="var(--ink-3)"
            strokeWidth={1}
          />
          <text x={width - MARGIN.right} y={y(result.params.initial_cash) - 4} textAnchor="end" fontSize={11} fill="var(--ink-3)">
            初期資金
          </text>
          {geometry.benchmarkPath && (
            <path d={geometry.benchmarkPath} fill="none" stroke="var(--ink-3)" strokeWidth={1.5} strokeDasharray="5 4" strokeLinejoin="round" />
          )}
          <path d={geometry.equityPath} fill="none" stroke="var(--ink)" strokeWidth={2} strokeLinejoin="round" />
          {geometry.xTicks.map((t) => (
            <text
              key={`xt-${t.index}`}
              x={x(t.index)}
              y={MARGIN.top + height + 18}
              textAnchor="middle"
              fontSize={12}
              fill={t.major ? "var(--ink-2)" : "var(--ink-3)"}
              className="tabular"
            >
              {t.label}
            </text>
          ))}
          {hover !== null && (
            <g pointerEvents="none">
              <line x1={x(index)} x2={x(index)} y1={MARGIN.top} y2={MARGIN.top + height} stroke="var(--ink-2)" strokeWidth={1} />
              {showBenchmark && <Dot x={x(index)} y={y(current.benchmark_equity)} color="var(--ink-3)" />}
              <Dot x={x(index)} y={y(current.equity)} color="var(--ink)" />
            </g>
          )}
        </svg>
      </div>
      <figcaption className="mt-2 text-[12px] leading-6 text-ink-3">
        横軸は営業日(休場日のすき間は詰めています)。上の数字は区切りの番号です。区切りの最終日は、株を売ったものとして清算したあとの額です。
        チャートを選んで、矢印キーで1日ずつ、Shift+矢印キーで{BIG_STEP}日ずつ、Home・End で最初と最後の日に動かせます。
      </figcaption>
    </figure>
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
