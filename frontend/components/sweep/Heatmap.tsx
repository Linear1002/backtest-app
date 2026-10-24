"use client";

// 総当たりのヒートマップ(縦 = 短期の日数、横 = 長期の日数)。docs/sweep.md 8章:「山」の形を見るためのもの。
// - マスの色:シャープレシオ・総リターンは 0 を中心に、プラスは朱・マイナスは藍(DESIGN.md)。最大ドローダウンは大きいほど濃い藍
// - 選ぶ期間と検証期間で同じ物差しを使う(切り替えても、同じ色が同じ値を表す)
// - キーボード:矢印キーでマスを動き、Enter・スペースで選ぶ(WAI-ARIA の grid)。値は上の読み取り欄・下の表でも読める

import { useMemo, useState } from "react";

import type { Objective, SegmentName, SweepResult } from "@/lib/api.ts";
import { formatNumber, formatPercent } from "@/lib/format.ts";
import { heatColor, heatScaleMax, heatTone, metricValue, OBJECTIVE_LABELS } from "@/lib/sweep.ts";

export const SEGMENT_LABELS: Record<SegmentName, string> = { in_sample: "選ぶ期間", out_of_sample: "検証期間" };

/** 基準の値の表示(シャープレシオは小数、総リターンは符号付きの %、最大ドローダウンは %)。 */
export function formatObjective(value: number | null, objective: Objective): string {
  if (objective === "sharpe_ratio") return formatNumber(value);
  if (objective === "total_return") return formatPercent(value, { signed: true });
  return formatPercent(value);
}

type Position = { row: number; col: number };

export function Heatmap({
  result,
  objective,
  segment,
  bestIndex,
  selected,
  onSelect,
}: {
  result: SweepResult;
  objective: Objective;
  segment: SegmentName;
  /** 選ぶ期間の1位(太い枠) */
  bestIndex: number | null;
  /** 選んでいるマス(下の「選んだ組み合わせ」に出る) */
  selected: number | null;
  onSelect: (index: number) => void;
}) {
  const shorts = result.grid.short_values;
  const longs = result.grid.long_values;
  const indexOf = useMemo(() => {
    const map = new Map<string, number>();
    result.combos.forEach((c, i) => map.set(`${c.short_window}-${c.long_window}`, i));
    return map;
  }, [result.combos]);
  const comboAt = (pos: Position) => indexOf.get(`${shorts[pos.row]}-${longs[pos.col]}`) ?? null;
  const positionOf = (index: number | null): Position | null => {
    if (index === null) return null;
    const c = result.combos[index];
    return { row: shorts.indexOf(c.short_window), col: longs.indexOf(c.long_window) };
  };
  // キーボードで動くマス(roving tabindex:表の中で Tab で止まるのは1マスだけ)
  const [cursor, setCursor] = useState<Position>(() => positionOf(selected ?? bestIndex) ?? { row: 0, col: longs.length - 1 });
  // 読み取り欄に出すマス(マウスで指しているマス。なければキーボードのマス)
  const [hover, setHover] = useState<Position | null>(null);
  const scaleMax = useMemo(() => heatScaleMax(result.combos, objective), [result.combos, objective]);
  const label = OBJECTIVE_LABELS[objective];

  const many = shorts.length > 25;
  const cellHeight = shorts.length <= 12 ? 30 : shorts.length <= 25 ? 22 : 14;
  // 横の目盛りが多いときは、間引いて書く
  const labelEvery = Math.max(1, Math.ceil(longs.length / 12));
  const template = `3.25rem repeat(${longs.length}, minmax(0, 1fr))`;

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
    setHover(null);
    // 次のマスにフォーカスを移す(描き直しのあとで)
    const grid = (event.currentTarget as HTMLElement).closest("[role=grid]");
    requestAnimationFrame(() => {
      grid?.querySelector<HTMLElement>(`[data-pos="${next.row}-${next.col}"]`)?.focus();
    });
  }

  const shown = hover ?? cursor;
  const shownIndex = comboAt(shown);
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
      <div
        role="grid"
        aria-label={`${label}(${SEGMENT_LABELS[segment]})のヒートマップ。縦が短期の日数、横が長期の日数。矢印キーで動き、Enter で選びます`}
        aria-rowcount={shorts.length + 1}
        aria-colcount={longs.length + 1}
        className="mt-1 select-none"
        onMouseLeave={() => setHover(null)}
      >
        <div role="row" className="grid gap-[2px]" style={{ gridTemplateColumns: template }}>
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
          <div key={short} role="row" className="mt-[2px] grid gap-[2px]" style={{ gridTemplateColumns: template }}>
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
                onFocus: () => setCursor({ row, col }),
                onMouseEnter: () => setHover({ row, col }),
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
      <Legend objective={objective} scaleMax={scaleMax} />
    </div>
  );
}

/** 色の物差し(凡例)。 */
function Legend({ objective, scaleMax }: { objective: Objective; scaleMax: number }) {
  const diverging = objective !== "max_drawdown";
  const steps = diverging ? [-1, -0.5, 0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1];
  const gradient = steps.map((t) => heatColor(heatTone(t * scaleMax, objective, scaleMax))).join(", ");
  const ends = diverging
    ? [formatObjective(-scaleMax, objective), "0", formatObjective(scaleMax, objective)]
    : [formatObjective(0, objective), formatObjective(scaleMax / 2, objective), formatObjective(scaleMax, objective)];
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-[12px] text-ink-2">
      <div className="min-w-[14rem] flex-1 sm:max-w-[22rem]">
        <div aria-hidden="true" className="h-2.5 rounded-sm" style={{ background: `linear-gradient(to right, ${gradient})` }} />
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
        <span aria-hidden="true" className="inline-block h-4 w-6" style={{ boxShadow: "inset 0 0 0 2px var(--ink)", background: "var(--heat-mid)" }} />
        太い枠:選ぶ期間の1位
      </span>
      <span className="inline-flex items-center gap-2">
        <span aria-hidden="true" className="inline-grid h-4 w-6 place-items-center bg-surface text-ink-3 ring-1 ring-rule">−</span>
        算出不可
      </span>
    </div>
  );
}
