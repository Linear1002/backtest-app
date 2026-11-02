"use client";

import { useId } from "react";

import type { Strategy, SweepEngineInfo, SymbolDetail, WalkForwardRequest } from "@/lib/api.ts";
import { describeYen, formatDate, formatRatePct, formatYen } from "@/lib/format.ts";
import { longestWindow, OBJECTIVE_LABELS, pairCount } from "@/lib/sweep.ts";
import { calendarWindows, monthsText, runCounts } from "@/lib/walkforward.ts";

import { StepHeading } from "../ui.tsx";
import { EngineChoice, JobStatusAndRun } from "./JobParts.tsx";

const count = new Intl.NumberFormat("ja-JP");

// docs/walkforward.md 3章〜5章の要約(1組のバックテストの前提に加えて)
function assumptions(request: WalkForwardRequest, longest: number): string[] {
  const objective = OBJECTIVE_LABELS[request.objective];
  return [
    `区切りごとに、直前の${monthsText(request.in_sample_months)}(選ぶ期間)だけで組み合わせをすべて試し、${objective}が1位の日数を選びます。同率1位なら、短期の短い順 → 長期の短い順で最初のものにします。`,
    `選んだ日数で、次の${monthsText(request.out_of_sample_months)}(使う期間)だけ売買します。どの日も、その日より前のデータだけで選んだ日数で売買することになります。`,
    "使う期間の最後に株を持っていたら、その日の評価価格で売ったものとして(売りの手数料・スリッページを引いて)次の区切りに進みます。次の区切りは株を持たない状態から始め、次にゴールデンクロスが起きるまで買いません(実際に持ち続けた場合とは、良くも悪くも違います)。",
    `どの区切りでも、すべての組み合わせを同じ日から比べます。開始日より前のデータが長期の日数(最長${longest}日)に足りない区切りは、選ぶ期間の始まりを、そのウォームアップがそろう日まで遅らせます。`,
    "選ぶ期間の計算は、どの区切りも入力の初期資金から始めます(その時点の資産ではありません)。",
    "当日の終値でシグナルを判定し、次に売買が成立した日の始値で約定します。配当・税金・ストップ高やストップ安は考えません。",
  ];
}

export function WalkForwardConfirmStep({
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
  /** この内容で実行する(lib/flow.ts の currentWalkForwardRequest。表示と実行で同じものを使う) */
  request: WalkForwardRequest;
  engines: SweepEngineInfo[];
  onEngineChange: (id: string) => void;
  running: boolean;
  /** 実行中の途中経過(API が受け付ける前は null) */
  progress: { done: number; total: number } | null;
  cancelled: boolean;
  cancelError?: string | null;
  error: string | null;
  outdated: boolean;
  onRun: () => void;
  onCancel: () => void;
}) {
  const headingId = useId();
  const g = request.grid;
  const pairs = pairCount(g);
  const windows = calendarWindows(request.start_date, request.end_date, request.in_sample_months, request.out_of_sample_months);
  const first = windows[0];
  const last = windows[windows.length - 1];
  const runs = runCounts(pairs, windows.length);
  const rows: [string, string][] = [
    ["銘柄", `${detail.symbol.name}(${request.symbol_id})`],
    ["売買ルール", `${strategy.name}(日数をウォークフォワードで選ぶ)`],
    ["期間", `${formatDate(request.start_date)}〜${formatDate(request.end_date)}`],
    ["1位を選ぶ基準", OBJECTIVE_LABELS[request.objective]],
    ["選ぶ期間", `直前の${monthsText(request.in_sample_months)}`],
    ["使う期間", `${monthsText(request.out_of_sample_months)}ずつ`],
    ["区切り", `${count.format(windows.length)}回`],
    ...(first && last
      ? ([["つなぐ期間", `${formatDate(first.outOfSampleStart)}〜${formatDate(last.outOfSampleEnd)}`]] as [string, string][])
      : []),
    ["短期の日数", `${g.short_min}〜${g.short_max}日(${g.short_step}日ごと)`],
    ["長期の日数", `${g.long_min}〜${g.long_max}日(${g.long_step}日ごと)`],
    ["組み合わせ", `${count.format(pairs)}通り`],
    [
      "計算",
      `選ぶ期間 ${count.format(pairs)}通り × 区切り${count.format(windows.length)}回 = ${count.format(runs.inSample)}回 + 使う期間 ${count.format(runs.outOfSample)}回 = ${count.format(runs.total)}回`,
    ],
    ["手数料率", formatRatePct(request.params.fee_rate_pct)],
    ["スリッページ率", formatRatePct(request.params.slippage_rate_pct)],
    ["初期資金", `${formatYen(request.params.initial_cash)}(${describeYen(request.params.initial_cash)})`],
    ["売買単位", `${detail.market.lot_size}株`],
  ];

  return (
    <section aria-labelledby={headingId}>
      <StepHeading id={headingId} step={4} title="確認してウォークフォワード分析を実行する">
        区切りごとに日数を選び直しながら進めて、使う期間だけをつないだ成績を出します。
      </StepHeading>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <table className="w-full border-y border-rule text-[15px]">
          <caption className="sr-only">実行する条件</caption>
          <tbody className="divide-y divide-rule">
            {rows.map(([label, value]) => (
              <tr key={label}>
                <th scope="row" className="w-36 py-2.5 pr-4 text-left align-top font-normal text-ink-3">
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
            {assumptions(request, longestWindow(g)).map((text) => (
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

      <EngineChoice engines={engines} selected={request.engine} running={running} onChange={onEngineChange} />

      <JobStatusAndRun
        name="ウォークフォワード分析"
        runLabel="ウォークフォワード分析を実行"
        running={running}
        progress={progress}
        cancelled={cancelled}
        cancelError={cancelError}
        error={error}
        outdated={outdated}
        onRun={onRun}
        onCancel={onCancel}
      />
    </section>
  );
}
