"use client";

import { useId } from "react";

import type { Strategy, SweepEngineInfo, SweepRequest, SymbolDetail } from "@/lib/api.ts";
import { describeYen, formatDate, formatRatePct, formatYen } from "@/lib/format.ts";
import { dayBefore, longestWindow, pairCount } from "@/lib/sweep.ts";

import { Seal } from "../Seal.tsx";
import { SecondaryButton, StepHeading } from "../ui.tsx";

const count = new Intl.NumberFormat("ja-JP");

// docs/sweep.md 3章・4章の要約(1組のバックテストの前提に加えて)
function assumptions(longest: number): string[] {
  return [
    "組み合わせごとに、選ぶ期間と検証期間を別々にバックテストします。1つ1つの計算は「1組で試す」とまったく同じです。",
    `すべての組み合わせを同じ日から比べるため、開始日より前のデータが長期の日数(最長${longest}日)に足りないときは、選ぶ期間の始まりを、そのウォームアップがそろう日まで遅らせます。`,
    "検証期間は、初期資金・持ち株なしから始めます(選ぶ期間の持ち株は引き継ぎません)。",
    "順位は選ぶ期間の成績だけで付けます。検証期間は、選んだ組み合わせを確かめるためだけに使います。",
    "当日の終値でシグナルを判定し、次に売買が成立した日の始値で約定します。配当・税金・ストップ高やストップ安は考えません。",
  ];
}

/** 読み上げで知らせる区切り(途中経過の数字が変わるたびには読み上げない)。 */
const MILESTONES = ["計算を始めました", "4分の1まで終わりました", "半分まで終わりました", "4分の3まで終わりました"];

export function SweepConfirmStep({
  detail,
  strategy,
  request,
  engines,
  onEngineChange,
  running,
  progress,
  cancelled,
  cancelError = null,
  error,
  outdated,
  onRun,
  onCancel,
}: {
  detail: SymbolDetail;
  strategy: Strategy;
  /** この内容で実行する(lib/flow.ts の currentSweepRequest。表示と実行で同じものを使う) */
  request: SweepRequest;
  engines: SweepEngineInfo[];
  onEngineChange: (id: string) => void;
  running: boolean;
  /** 実行中の途中経過(API が受け付ける前は null) */
  progress: { done: number; total: number } | null;
  /** 中止したところ */
  cancelled: boolean;
  /** 「中止する」が API に届かなかったときの文 */
  cancelError?: string | null;
  error: string | null;
  outdated: boolean;
  onRun: () => void;
  onCancel: () => void;
}) {
  const headingId = useId();
  const g = request.grid;
  const pairs = pairCount(g);
  const holdout = request.holdout_start_date;
  const rows: [string, string][] = [
    ["銘柄", `${detail.symbol.name}(${request.symbol_id})`],
    ["売買ルール", `${strategy.name}(日数の総当たり)`],
    ["期間", `${formatDate(request.start_date)}〜${formatDate(request.end_date)}`],
    [
      "選ぶ期間",
      holdout ? `${formatDate(request.start_date)}〜${formatDate(dayBefore(holdout))}` : "期間全体",
    ],
    ["検証期間", holdout ? `${formatDate(holdout)}〜${formatDate(request.end_date)}` : "なし"],
    ["短期の日数", `${g.short_min}〜${g.short_max}日(${g.short_step}日ごと)`],
    ["長期の日数", `${g.long_min}〜${g.long_max}日(${g.long_step}日ごと)`],
    ["組み合わせ", `${count.format(pairs)}通り(計算は${count.format(pairs * (holdout ? 2 : 1))}回)`],
    ["手数料率", formatRatePct(request.params.fee_rate_pct)],
    ["スリッページ率", formatRatePct(request.params.slippage_rate_pct)],
    ["初期資金", `${formatYen(request.params.initial_cash)}(${describeYen(request.params.initial_cash)})`],
    ["売買単位", `${detail.market.lot_size}株`],
  ];
  const ratio = progress && progress.total > 0 ? progress.done / progress.total : 0;
  const milestone = MILESTONES[Math.min(MILESTONES.length - 1, Math.floor(ratio * 4))];

  return (
    <section aria-labelledby={headingId}>
      <StepHeading id={headingId} step={4} title="確認して総当たりを実行する">
        日数の組み合わせをすべて試し、選ぶ期間の成績で並べます。
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
            {assumptions(longestWindow(g)).map((text) => (
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
              } ${request.engine === e.id ? "border-ink" : ""}`}
            >
              <input
                type="radio"
                name="sweep-engine"
                value={e.id}
                checked={request.engine === e.id}
                disabled={!e.available || running}
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

      {outdated && !running && (
        <p className="mt-6 text-[13px] leading-6 text-ink-2">
          ※ 前に出した総当たりの結果とは条件が違います。実行すると、この条件の新しい結果になります。
        </p>
      )}

      {cancelled && !running && (
        // 押した「中止する」ボタンは消えるので、フォーカスをこの知らせに移す(lib/flow.ts の sweepCancelled)
        <p className="mt-6 text-[14px] text-ink-2 outline-none" role="status" tabIndex={-1} data-focus-notice>
          総当たりを中止しました。条件を変えるか、もう一度実行してください。
        </p>
      )}

      {error && (
        <p role="alert" className="mt-6 rounded-md border border-shu px-4 py-3 text-[14px] text-shu">
          {error}
        </p>
      )}

      {/* 読み上げは区切り(始め・4分の1・半分・4分の3)だけ。数字は見た目の文とバーで伝える。
          読み上げの領域は実行していないときも置いておく(実行と同時に作ると、最初の区切りが読まれにくいため) */}
      <p className="sr-only" aria-live="polite">
        {running ? `総当たりの${milestone}` : ""}
      </p>
      {running && (
        <div className="mt-8 rounded-md border border-rule bg-surface px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[14px] text-ink" aria-hidden="true">
              {progress && progress.total > 0
                ? `計算しています(${count.format(progress.done)} / ${count.format(progress.total)}通り)`
                : "計算を始めています…"}
            </p>
            <SecondaryButton onClick={onCancel} disabled={!progress}>
              中止する
            </SecondaryButton>
          </div>
          {cancelError && (
            <p role="alert" className="mt-2 text-[13px] text-shu">
              {cancelError}
            </p>
          )}
          <div
            role="progressbar"
            aria-label="総当たりの進み具合"
            aria-valuemin={0}
            aria-valuemax={progress?.total || 1}
            aria-valuenow={progress?.done ?? 0}
            className="mt-3 h-2 overflow-hidden rounded-full bg-paper"
          >
            <div className="h-full rounded-full bg-ink transition-[width] duration-300" style={{ width: `${Math.round(ratio * 100)}%` }} />
          </div>
        </div>
      )}

      <div className="mt-8 flex justify-end border-t border-rule pt-6">
        <button
          type="button"
          onClick={onRun}
          disabled={running}
          className="inline-flex items-center gap-3 rounded-md bg-ink py-2.5 pl-3 pr-6 text-[16px] font-bold text-paper hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
        >
          <Seal kind="check" size={26} decorative />
          {running ? "計算しています…" : "総当たりを実行"}
        </button>
      </div>
    </section>
  );
}
