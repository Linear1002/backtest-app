"use client";

import { useId } from "react";

import type { EngineInfo, Params, Strategy, SymbolDetail } from "@/lib/api.ts";
import { describeYen, formatDate } from "@/lib/format.ts";

import { Seal } from "../Seal.tsx";
import { StepHeading } from "../ui.tsx";

const ASSUMPTIONS = [
  "当日の終値でシグナルを判定し、次の営業日の始値で約定します(寄付きの成行注文と同じ)。",
  "買いのみで、空売りはしません。売りのシグナルが出たら全株を売ります。",
  "株数は売買単位の倍数です。資金が足りないときは買わずに見送ります。",
  "移動平均は、その日までに分かる情報だけで分割などを調整した終値で計算します(未来のデータは使いません)。",
  "配当・税金・ストップ高やストップ安で約定できない日は考えません。",
];

export function ConfirmStep({
  detail,
  strategy,
  period,
  params,
  engines,
  engine,
  onEngineChange,
  running,
  error,
  onRun,
}: {
  detail: SymbolDetail;
  strategy: Strategy;
  period: { start_date: string; end_date: string };
  params: Params;
  engines: EngineInfo[];
  engine: string;
  onEngineChange: (id: string) => void;
  running: boolean;
  error: string | null;
  onRun: () => void;
}) {
  const headingId = useId();
  const rows: [string, string][] = [
    ["銘柄", `${detail.symbol.name}(${detail.symbol.id})`],
    ["売買ルール", strategy.name],
    ["期間", `${formatDate(period.start_date)}〜${formatDate(period.end_date)}`],
    ["短期移動平均", `${params.short_window}日`],
    ["長期移動平均", `${params.long_window}日`],
    ["手数料率", `${params.fee_rate_pct}%`],
    ["スリッページ率", `${params.slippage_rate_pct}%`],
    ["初期資金", `${params.initial_cash.toLocaleString("ja-JP")}円(${describeYen(params.initial_cash)})`],
    ["売買単位", `${detail.market.lot_size}株`],
  ];

  return (
    <section aria-labelledby={headingId}>
      <StepHeading id={headingId} step={4} title="確認して実行する">
        この条件で過去の株価を1日ずつたどり、売買を記録します。
      </StepHeading>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <table className="w-full border-y border-rule text-[15px]">
          <caption className="sr-only">実行する条件</caption>
          <tbody className="divide-y divide-rule">
            {rows.map(([label, value]) => (
              <tr key={label}>
                <th scope="row" className="w-36 py-2.5 pr-4 text-left font-normal text-ink-3">
                  {label}
                </th>
                <td className="py-2.5 tabular text-ink">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div>
          <h3 className="text-[15px] font-bold text-ink">計算の前提</h3>
          <ul className="mt-2 space-y-2 text-[13px] leading-6 text-ink-2">
            {ASSUMPTIONS.map((text) => (
              <li key={text} className="flex gap-2">
                <span aria-hidden="true" className="text-ink-3">
                  ※
                </span>
                <span>{text}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <fieldset className="mt-8">
        <legend className="text-[15px] font-bold text-ink">計算エンジン</legend>
        <div className="mt-2 flex flex-wrap gap-3">
          {engines.map((e) => (
            <label
              key={e.id}
              className={`flex min-w-[15rem] items-start gap-2 rounded-md border px-3 py-2 text-[14px] ${
                e.available ? "cursor-pointer border-rule bg-surface" : "cursor-not-allowed border-dashed border-rule text-ink-3"
              } ${engine === e.id ? "border-ink" : ""}`}
            >
              <input
                type="radio"
                name="engine"
                value={e.id}
                checked={engine === e.id}
                disabled={!e.available}
                onChange={() => onEngineChange(e.id)}
                className="mt-1.5 accent-[var(--ink)]"
              />
              <span>
                <span className={`block ${e.available ? "text-ink" : ""}`}>{e.label}</span>
                <span className="block text-[12px] text-ink-3">{e.note}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {error && (
        <p role="alert" className="mt-6 rounded-md border border-shu px-4 py-3 text-[14px] text-shu">
          {error}
        </p>
      )}

      <div className="mt-8 flex justify-end border-t border-rule pt-6">
        <button
          type="button"
          onClick={onRun}
          disabled={running}
          className="inline-flex items-center gap-3 rounded-md bg-ink py-2.5 pl-3 pr-6 text-[16px] font-bold text-paper hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
        >
          <Seal kind="check" size={26} title="検証" />
          {running ? "計算しています…" : "バックテストを実行"}
        </button>
      </div>
    </section>
  );
}
