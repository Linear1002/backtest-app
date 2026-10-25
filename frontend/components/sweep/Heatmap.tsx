"use client";

// 総当たりのヒートマップ(縦 = 短期の日数、横 = 長期の日数)。docs/sweep.md 8章:「山」の形を見るためのもの。
// - マスの色:シャープレシオ・総リターンは 0 を中心に、プラスは朱・マイナスは藍(DESIGN.md)。最大ドローダウンは大きいほど濃い藍
// - 色の物差しは選ぶ期間の値だけで決める(検証期間の情報を選ぶ画面に入れないため)。検証期間も同じ物差しで塗る
// - キーボード:矢印キーでマスを動き、Enter・スペースで選ぶ(WAI-ARIA の grid)。値は上の読み取り欄・下の表でも読める
// - マスがたくさんあるときも1マスの幅を保ち、はみ出す分は横にスクロールする
// - マスの一覧(HeatGrid)は、マウスで指すマスが変わっても描き直さない(読み取り欄だけを描き直す)

import { memo, useCallback, useMemo, useState } from "react";

import type { Objective, SegmentName, SweepResult } from "@/lib/api.ts";
import { formatNumber, formatPercent } from "@/lib/format.ts";
import { exceedsScale, heatColor, heatScaleMax, heatTone, metricValue, OBJECTIVE_LABELS } from "@/lib/sweep.ts";

export const SEGMENT_LABELS: Record<SegmentName, string> = { in_sample: "選ぶ期間", out_of_sample: "検証期間" };

/** 基準の値の表示(シャープレシオは小数、総リターンは符号付きの %、最大ドローダウンは %)。 */
export function formatObjective(value: number | null, objective: Objective): string {
  if (objective === "sharpe_ratio") return formatNumber(value);
  if (objective === "total_return") return formatPercent(value, { signed: true });
  return formatPercent(value);
}

type Position = { row: number; col: number };

/** 列の数に合わせた、1マスの最小の幅とすき間(px)。 */
function cellSizing(columns: number): { minWidth: number; gap: number } {
  if (columns > 60) return { minWidth: 6, gap: 1 };
  if (columns > 30) return { minWidth: 10, gap: 1 };
  return { minWidth: 16, gap: 2 };
}

const ROW_HEADER_PX = 52; // 縦の目盛り(短期の日数)の列の幅

export function Heatmap({
  result,
  objective,
  segment,
  bestIndex,
  selected,
  onSelect,
  benchmark = null,
}: {
  result: SweepResult;
  objective: Objective;
  segment: SegmentName;
  /** 選ぶ期間の1位(太い枠)。同率1位のときは null */
  bestIndex: number | null;
  /** 選んでいるマス(下の「選んだ組み合わせ」に出る) */
  selected: number | null;
  onSelect: (index: number) => void;
  /** 色を付けている期間の、買い持ちの値(凡例の物差しに印を付ける。算出不可なら null) */
  benchmark?: number | null;
}) {
  const shorts = result.grid.short_values;
  const longs = result.grid.long_values;
  const indexOf = useMemo(() => {
    const map = new Map<string, number>();
    result.combos.forEach((c, i) => map.set(`${c.short_window}-${c.long_window}`, i));
    return map;
  }, [result.combos]);
  // 最初に描くときだけ決める(そのあとは HeatGrid がキーボードの位置を持つ)
  const [initial] = useState<Position>(() => {
    const index = selected ?? bestIndex;
    if (index === null) return { row: 0, col: longs.length - 1 };
    const c = result.combos[index];
    return { row: shorts.indexOf(c.short_window), col: longs.indexOf(c.long_window) };
  });
  // 読み取り欄に出すマス(マウスで指しているマスか、キーボードで動かしたマス)
  const [shown, setShown] = useState<Position>(initial);
  const scaleMax = useMemo(() => heatScaleMax(result.combos, objective), [result.combos, objective]);
  const clamped = segment === "out_of_sample" && exceedsScale(result.combos, objective, scaleMax);

  const shownIndex = indexOf.get(`${shorts[shown.row]}-${longs[shown.col]}`) ?? null;
  const shownCombo = shownIndex !== null ? result.combos[shownIndex] : null;

  return (
    <div>
      {/* 読み取り欄:指している(フォーカスしている)マスの値。数字はいつでもここと下の表で読める */}
      <div className="flex min-h-[3.25rem] flex-wrap items-baseline gap-x-5 gap-y-1 rounded-md bg-surface-2 px-3 py-2 text-[13px] tabular" aria-hidden="true">
        {shownCombo ? (
          <>
            <span className="font-bold text-ink">
              短期{shownCombo.short_window}日・長期{shownCombo.long_window}日
            </span>
            <span className="text-ink-2">
              選ぶ期間 <b className="text-ink">{formatObjective(metricValue(shownCombo.in_sample, objective), objective)}</b>
            </span>
            {shownCombo.out_of_sample && (
              <span className="text-ink-2">
                検証期間 <b className="text-ink">{formatObjective(metricValue(shownCombo.out_of_sample, objective), objective)}</b>
              </span>
            )}
            <span className="text-ink-3">取引 {shownCombo.in_sample.trade_count}回</span>
            {shownIndex === bestIndex && <span className="text-ink-2">選ぶ期間の1位</span>}
          </>
        ) : (
          <span className="text-ink-3">
            短期{shorts[shown.row]}日・長期{longs[shown.col]}日:短期が長期以上なので計算しません
          </span>
        )}
      </div>

      <p className="mt-3 text-[12px] text-ink-3">縦:短期の日数 / 横:長期の日数</p>
      <HeatGrid
        result={result}
        indexOf={indexOf}
        objective={objective}
        segment={segment}
        scaleMax={scaleMax}
        bestIndex={bestIndex}
        selected={selected}
        initial={initial}
        onSelect={onSelect}
        onShow={setShown}
      />
      <Legend objective={objective} scaleMax={scaleMax} clamped={clamped} benchmark={benchmark} />
    </div>
  );
}

/** マスの一覧(WAI-ARIA の grid)。キーボードで動く位置(roving tabindex)はここで持つ。 */
const HeatGrid = memo(function HeatGrid({
  result,
  indexOf,
  objective,
  segment,
  scaleMax,
  bestIndex,
  selected,
  initial,
  onSelect,
  onShow,
}: {
  result: SweepResult;
  indexOf: Map<string, number>;
  objective: Objective;
  segment: SegmentName;
  scaleMax: number;
  bestIndex: number | null;
  selected: number | null;
  initial: Position;
  onSelect: (index: number) => void;
  /** 読み取り欄に出すマスを伝える */
  onShow: (pos: Position) => void;
}) {
  const shorts = result.grid.short_values;
  const longs = result.grid.long_values;
  // キーボードで動くマス(表の中で Tab で止まるのは1マスだけ)
  const [cursor, setCursor] = useState<Position>(initial);
  const label = OBJECTIVE_LABELS[objective];

  const many = shorts.length > 25;
  const cellHeight = shorts.length <= 12 ? 30 : shorts.length <= 25 ? 22 : 14;
  const sizing = cellSizing(longs.length);
  const template = `${ROW_HEADER_PX}px repeat(${longs.length}, minmax(${sizing.minWidth}px, 1fr))`;
  const minWidth = ROW_HEADER_PX + longs.length * (sizing.minWidth + sizing.gap);
  // 横の目盛りが多いときは、間引いて書く
  const labelEvery = Math.max(1, Math.ceil(longs.length / 12));

  const comboAt = useCallback(
    (pos: Position) => indexOf.get(`${shorts[pos.row]}-${longs[pos.col]}`) ?? null,
    [indexOf, shorts, longs],
  );

  function move(event: React.KeyboardEvent, pos: Position) {
    const last = { row: shorts.length - 1, col: longs.length - 1 };
    const next = { ...pos };
    switch (event.key) {
      case "ArrowUp":
        next.row = Math.max(0, pos.row - 1);
        break;
      case "ArrowDown":
        next.row = Math.min(last.row, pos.row + 1);
        break;
      case "ArrowLeft":
        next.col = Math.max(0, pos.col - 1);
        break;
      case "ArrowRight":
        next.col = Math.min(last.col, pos.col + 1);
        break;
      case "Home":
        next.col = 0;
        break;
      case "End":
        next.col = last.col;
        break;
      case "Enter":
      case " ": {
        const index = comboAt(pos);
        if (index !== null) onSelect(index);
        event.preventDefault();
        return;
      }
      default:
        return;
    }
    event.preventDefault();
    setCursor(next);
    onShow(next);
    // 次のマスにすぐフォーカスを移す(マスはすべて描いてあるので、描き直しを待たない。続けて押した Enter が次のマスに届くように)。
    // 横にスクロールしていても、フォーカスしたマスが見えるところまでブラウザがスクロールする
    const grid = (event.currentTarget as HTMLElement).closest("[role=grid]");
    grid?.querySelector<HTMLElement>(`[data-pos="${next.row}-${next.col}"]`)?.focus();
  }

  return (
    // relative:読み上げ用に隠した目盛り(sr-only は position: absolute)も、この枠の中でスクロールさせる。
    // ないと、右端の列の隠した目盛りが枠の外に出て、ページ全体が横にはみ出す
    <div className="relative mt-1 overflow-x-auto pb-1">
      <div
        role="grid"
        aria-label={`${label}(${SEGMENT_LABELS[segment]})のヒートマップ。縦が短期の日数、横が長期の日数。矢印キーで動き、Enter で選びます`}
        aria-rowcount={shorts.length + 1}
        aria-colcount={longs.length + 1}
        className="heat-grid select-none"
        // マスが細いとき(列が多いとき)は、1位の枠を内側ではなく外側に描く(内側の枠でマスの色が隠れないように。globals.css)
        data-size={sizing.minWidth < 10 ? "tiny" : undefined}
        style={{ minWidth }}
        onMouseLeave={() => onShow(cursor)}
      >
        <div role="row" className="grid" style={{ gridTemplateColumns: template, gap: sizing.gap }}>
          <div role="columnheader" className="text-right text-[11px] text-ink-3">
            <span className="sr-only">短期の日数 \ 長期の日数</span>
          </div>
          {longs.map((long, col) => (
            <div key={long} role="columnheader" className="text-center text-[11px] leading-5 text-ink-3 tabular">
              <span className={col % labelEvery === 0 ? "" : "sr-only"}>{long}</span>
              <span className="sr-only">日</span>
            </div>
          ))}
        </div>
        {shorts.map((short, row) => (
          <div key={short} role="row" className="grid" style={{ gridTemplateColumns: template, gap: sizing.gap, marginTop: sizing.gap }}>
            <div role="rowheader" className="flex items-center justify-end pr-2 text-[11px] text-ink-3 tabular">
              <span className={many && row % 2 === 1 ? "sr-only" : ""}>{short}</span>
              <span className="sr-only">日</span>
            </div>
            {longs.map((long, col) => {
              const index = indexOf.get(`${short}-${long}`) ?? null;
              const isCursor = cursor.row === row && cursor.col === col;
              const common = {
                role: "gridcell",
                "data-pos": `${row}-${col}`,
                tabIndex: isCursor ? 0 : -1,
                onKeyDown: (e: React.KeyboardEvent) => move(e, { row, col }),
                onFocus: () => {
                  setCursor({ row, col });
                  onShow({ row, col });
                },
                onMouseEnter: () => onShow({ row, col }),
                style: { height: cellHeight },
              } as const;
              if (index === null) {
                return (
                  <div
                    key={long}
                    {...common}
                    aria-label={`短期${short}日・長期${long}日:計算しない組み合わせ(短期の日数が長期の日数以上)`}
                    className="heat-cell"
                  />
                );
              }
              const combo = result.combos[index];
              const metrics = segment === "in_sample" ? combo.in_sample : combo.out_of_sample;
              const value = metricValue(metrics, objective);
              const isBest = index === bestIndex;
              return (
                <div
                  key={long}
                  {...common}
                  aria-selected={selected === index}
                  aria-label={
                    `短期${short}日・長期${long}日:${label} ${formatObjective(value, objective)}(${SEGMENT_LABELS[segment]})` +
                    (isBest ? "。選ぶ期間の1位" : "")
                  }
                  data-best={isBest ? "true" : undefined}
                  onClick={() => {
                    setCursor({ row, col });
                    onSelect(index);
                  }}
                  className="heat-cell flex cursor-pointer items-center justify-center text-[11px] text-ink-3"
                  style={{ ...common.style, background: heatColor(heatTone(value, objective, scaleMax)) }}
                >
                  {value === null && <span aria-hidden="true">−</span>}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
});

/** 色の物差し(凡例)。 */
function Legend({
  objective,
  scaleMax,
  clamped,
  benchmark,
}: {
  objective: Objective;
  scaleMax: number;
  clamped: boolean;
  benchmark: number | null;
}) {
  const diverging = objective !== "max_drawdown";
  // 買い持ちの値の、物差しの上の位置(0〜1。はみ出すときは端)
  const benchmarkAt =
    benchmark === null
      ? null
      : Math.min(1, Math.max(0, diverging ? (benchmark / scaleMax + 1) / 2 : benchmark / scaleMax));
  const steps = diverging ? [-1, -0.5, 0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1];
  const gradient = steps.map((t) => heatColor(heatTone(t * scaleMax, objective, scaleMax))).join(", ");
  const ends = diverging
    ? [formatObjective(-scaleMax, objective), "0", formatObjective(scaleMax, objective)]
    : [formatObjective(0, objective), formatObjective(scaleMax / 2, objective), formatObjective(scaleMax, objective)];
  return (
    <div className="mt-4 space-y-2 text-[12px] text-ink-2">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="min-w-[14rem] flex-1 sm:max-w-[22rem]">
          <div aria-hidden="true" className="relative h-2.5 rounded-sm" style={{ background: `linear-gradient(to right, ${gradient})` }}>
            {benchmarkAt !== null && (
              // 買い持ちの値の位置に、墨の縦線(面の色で縁取り)
              <span
                className="absolute -top-1 h-[18px] w-[3px] -translate-x-1/2 rounded-sm bg-ink"
                style={{ left: `${benchmarkAt * 100}%`, boxShadow: "0 0 0 1.5px var(--surface)" }}
              />
            )}
          </div>
          <div className="mt-1 flex justify-between tabular">
            {ends.map((text, i) => (
              <span key={i}>{text}</span>
            ))}
          </div>
          <p className="sr-only">
            色の物差し:{diverging ? `${OBJECTIVE_LABELS[objective]}がプラスなら朱、マイナスなら藍。0 は灰色` : "最大ドローダウンが大きいほど濃い藍"}
          </p>
        </div>
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="heat-legend-best inline-block h-4 w-6" />
          太い枠:選ぶ期間の1位
        </span>
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="heat-legend-selected relative inline-block h-4 w-6" />
          黒い点:選んだ組み合わせ
        </span>
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="inline-grid h-4 w-6 place-items-center bg-surface text-ink-3 ring-1 ring-rule">−</span>
          算出不可
        </span>
        {benchmark !== null && (
          <span className="inline-flex items-center gap-2">
            <span aria-hidden="true" className="inline-block h-4 w-[3px] rounded-sm bg-ink" />
            物差しの縦線:買い持ち({formatObjective(benchmark, objective)})
          </span>
        )}
      </div>
      <p className="text-ink-3">
        色の物差しは選ぶ期間の値で決めています(検証期間の値で決めると、検証期間の情報が選ぶ画面に入るため)。
        {clamped && "検証期間には物差しを超える値があり、そのマスは端の色で塗っています(値は読み取り欄と表で読めます)。"}
      </p>
    </div>
  );
}
