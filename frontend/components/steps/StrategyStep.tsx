"use client";

import { useId } from "react";

import type { Strategy } from "@/lib/api.ts";

import { SvgSeal } from "../Seal.tsx";
import { PrimaryButton, StepHeading } from "../ui.tsx";

export function StrategyStep({
  strategies,
  selectedId,
  onSelect,
  onNext,
}: {
  strategies: Strategy[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNext: () => void;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId}>
      <StepHeading id={headingId} step={2} title="売買ルールを選ぶ">
        どんなときに買って、どんなときに売るかを決めます。
      </StepHeading>

      <fieldset className="mt-6">
        <legend className="sr-only">戦略</legend>
        <div className="space-y-3">
          {strategies.map((strategy) => {
            const checked = strategy.id === selectedId;
            return (
              <label
                key={strategy.id}
                className={`block rounded-md border p-4 sm:p-5 ${
                  strategy.available
                    ? checked
                      ? "cursor-pointer border-ink bg-surface"
                      : "cursor-pointer border-rule bg-surface hover:border-rule-strong"
                    : "cursor-not-allowed border-dashed border-rule bg-transparent"
                }`}
              >
                <div className="flex items-start gap-3">
                  <input
                    type="radio"
                    name="strategy"
                    value={strategy.id}
                    checked={checked}
                    disabled={!strategy.available}
                    onChange={() => onSelect(strategy.id)}
                    className="mt-1.5 h-4 w-4 accent-[var(--ink)]"
                  />
                  <div className="min-w-0 flex-1">
                    <p className={`text-[17px] font-bold ${strategy.available ? "text-ink" : "text-ink-3"}`}>
                      {strategy.name}
                      {!strategy.available && (
                        <span className="ml-2 text-[13px] font-normal">今後追加予定</span>
                      )}
                    </p>
                    <p className={`text-[14px] ${strategy.available ? "text-ink-2" : "text-ink-3"}`}>
                      {strategy.summary}
                    </p>
                    {strategy.available && (
                      <div className="mt-3 grid gap-4 sm:grid-cols-[1fr_15rem] sm:items-center">
                        <p className="max-w-[36em] text-[14px] leading-7 text-ink-2">{strategy.description}</p>
                        {strategy.id === "ma_cross" && <CrossDiagram />}
                      </div>
                    )}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="mt-6 flex justify-end">
        <PrimaryButton onClick={onNext} disabled={!selectedId}>
          この売買ルールで進む
        </PrimaryButton>
      </div>
    </section>
  );
}

/** 移動平均クロスの説明図:短期線が長期線を上に抜けたら「買」、下に抜けたら「売」。 */
function CrossDiagram() {
  const longPath = "M8,70 C60,74 100,60 140,48 S200,40 232,46";
  const shortPath = "M8,84 C40,90 66,78 90,58 S120,20 150,26 S190,72 232,70";
  return (
    <figure className="rounded-md border border-rule bg-surface-2 p-2">
      <svg viewBox="0 0 240 110" className="h-auto w-full" role="img" aria-label="短期線が長期線を上に抜けた翌日に買い、下に抜けた翌日に売る図">
        <path d={longPath} fill="none" stroke="var(--ma-long)" strokeWidth={2} strokeLinecap="round" />
        <path d={shortPath} fill="none" stroke="var(--ma-short)" strokeWidth={2} strokeLinecap="round" />
        <SvgSeal kind="buy" x={95} y={53} r={11} />
        <SvgSeal kind="sell" x={178} y={53} r={11} />
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 px-1 text-[12px] text-ink-3">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded bg-[var(--ma-short)]" aria-hidden="true" />
          短期線
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded bg-[var(--ma-long)]" aria-hidden="true" />
          長期線
        </span>
      </figcaption>
    </figure>
  );
}
