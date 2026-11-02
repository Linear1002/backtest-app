"use client";

// ウォークフォワード分析の結果の画面(docs/walkforward.md 8章)。
// いちばん上に「つないだ成績」と「同じ期間の買い持ち」を並べ、そのあとに資産額のチャート・区切りごとの表・注意を出す。
// 選ぶ期間は区切りごとに重なるが、使う期間は重ならない。つないだ成績は、どの日も「その日より前のデータだけで選んだ日数」で売買した結果。

import { useId } from "react";

import type { Objective, WalkForwardResult, WalkForwardWindow } from "@/lib/api.ts";
import { benchmarkUnavailable, returnGap, versusBenchmark, versusText } from "@/lib/benchmark.ts";
import type { WalkForwardRecord } from "@/lib/flow.ts";
import { direction, formatDate, formatDateTimeJst, formatNumber, formatPercent, formatRatePct, formatYen } from "@/lib/format.ts";
import { OBJECTIVE_LABELS } from "@/lib/sweep.ts";
import { monthsText } from "@/lib/walkforward.ts";

import { formatObjective } from "../sweep/Heatmap.tsx";
import { ScrollRegion, SecondaryButton } from "../ui.tsx";
import { WalkForwardChart } from "./WalkForwardChart.tsx";

const TONE = { up: "text-shu", down: "text-ai", flat: "text-ink" } as const;
const count = new Intl.NumberFormat("ja-JP");

export function WalkForwardView({
  record,
  onEditParams,
  onRestart,
}: {
  record: WalkForwardRecord;
  onEditParams: () => void;
  onRestart: () => void;
}) {
  const headingId = useId();
  const result = record.result;
  return (
    <article aria-labelledby={headingId} className="space-y-10">
      <Header result={result} headingId={headingId} onEditParams={onEditParams} onRestart={onRestart} />
      <Summary result={result} />
      <section aria-label="つないだ資産額のチャート" className="rounded-md border border-rule bg-surface p-3 sm:p-5">
        <h3 className="mb-3 text-[16px] font-bold text-ink">つないだ資産額と買い持ち</h3>
        <WalkForwardChart result={result} />
      </section>
      <WindowTable result={result} />
      <Notes result={result} elapsedMs={record.elapsedMs} />
    </article>
  );
}

// --- 見出し ---------------------------------------------------------------------------

function stitchedPeriod(result: WalkForwardResult): { first: string; last: string; days: number } {
  const first = result.windows[0].out_of_sample;
  const last = result.windows[result.windows.length - 1].out_of_sample;
  const days = result.windows.reduce((sum, w) => sum + w.out_of_sample.business_days, 0);
  return { first: first.first_business_day, last: last.last_business_day, days };
}

function Header({
  result,
  headingId,
  onEditParams,
  onRestart,
}: {
  result: WalkForwardResult;
  headingId: string;
  onEditParams: () => void;
  onRestart: () => void;
}) {
  const g = result.grid;
  const period = stitchedPeriod(result);
  const first = result.windows[0];
  return (
    <header className="grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
      <div>
        {/* 結果が出たら、ほかの手順と同じく見出しにフォーカスを移す(BacktestApp) */}
        <h2 id={headingId} data-step-heading tabIndex={-1} className="text-[24px] font-bold text-ink outline-none sm:text-[28px]">
          <span className="sr-only">手順5:ウォークフォワード分析の結果 </span>
          {result.symbol.name}
          <span className="ml-3 tabular text-[15px] font-normal text-ink-2">{result.symbol.id}</span>
        </h2>
        <p className="mt-1 text-[14px] text-ink-2">
          ウォークフォワード分析:直前{monthsText(result.in_sample_months)}で{OBJECTIVE_LABELS[result.objective]}が1位の日数を選び、次の
          {monthsText(result.out_of_sample_months)}だけ使う、を{count.format(result.windows.length)}回
        </p>
        <p className="mt-0.5 text-[13px] text-ink-3">
          日数の候補:短期{g.short_min}〜{g.short_max}日({g.short_step}日ごと)× 長期{g.long_min}〜{g.long_max}日({g.long_step}日ごと)=
          {count.format(result.count)}通り
        </p>
        <p className="mt-0.5 text-[13px] text-ink-3 tabular">
          つないだ期間 {formatDate(period.first)}〜{formatDate(period.last)}({count.format(period.days)}営業日)
        </p>
        {first.in_sample.start_date !== first.requested_in_sample_start && (
          <p className="mt-0.5 text-[13px] text-ink-3">
            ※ すべての組み合わせを同じ日から比べるため、区切り1の選ぶ期間は{formatDate(first.requested_in_sample_start)}ではなく
            {formatDate(first.in_sample.start_date)}から始めました(それより前は移動平均のウォームアップにだけ使いました)。
          </p>
        )}
        <p className="mt-0.5 text-[13px] text-ink-3">
          手数料率 {formatRatePct(result.params.fee_rate_pct)}・スリッページ率 {formatRatePct(result.params.slippage_rate_pct)}・初期資金{" "}
          {formatYen(result.params.initial_cash)}・売買単位 {result.params.lot_size}株
        </p>
      </div>
      <div className="flex flex-wrap gap-2 lg:justify-end">
        <SecondaryButton onClick={onEditParams}>条件を変えて試す</SecondaryButton>
        <SecondaryButton onClick={onRestart}>別の銘柄で試す</SecondaryButton>
      </div>
    </header>
  );
}

// --- まとめ(いちばん上) -------------------------------------------------------------

function Summary({ result }: { result: WalkForwardResult }) {
  const headingId = useId();
  const m = result.metrics;
  const b = result.benchmark;
  const unavailable = benchmarkUnavailable(b, result.params.lot_size, result.params.fee_rate);
  const bm = unavailable ? null : b.metrics;
  const versus = (objective: Objective, value: number | null, benchmark: number | null) =>
    versusText(value, benchmark, objective, formatObjective(benchmark, objective));
  const windows = result.windows.length;
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="text-[18px] font-bold text-ink">
        まとめ
      </h3>
      <p className="mt-1 text-[13px] leading-6 text-ink-2">
        使う期間だけをつないだ成績です。どの日も、その日より前のデータだけで選んだ日数で売買しているので、
        「この選び方を実際に続けていたら」に近い成績になります(費用・約定の前提はそのまま)。
      </p>
      <dl className="mt-3 grid border-t border-rule sm:grid-cols-2">
        <Row label="つないだ総リターン" help="入力の初期資金から、最後の日(清算する前)まで">
          <span className={`block text-[22px] ${TONE[direction(m.total_return)]}`}>
            {formatPercent(m.total_return, { signed: true })}
          </span>
          {bm && <span className="block text-[13px] font-normal text-ink-2">{returnGap(m.total_return, bm.total_return)}</span>}
        </Row>
        <Row label="買い持ち(比較)" help="同じ期間・同じ費用で、最初に買って最後まで持った場合。配当は含めません">
          {bm ? (
            <>
              <span className={`block text-[22px] ${TONE[direction(bm.total_return)]}`}>
                {formatPercent(bm.total_return, { signed: true })}
              </span>
              <span className="block text-[13px] font-normal text-ink-2">{formatYen(bm.final_equity)}</span>
            </>
          ) : (
            // 理由の文は長いので、まとめの表の下に出す(ここに入れると見出しの列が細くつぶれる)
            <span className="text-[18px]">買えず(比べない)</span>
          )}
        </Row>
        <Row label="シャープレシオ(年率)" help="値動きの大きさに対するリターン。大きいほど良い">
          <span className="block text-[22px]">{formatNumber(m.sharpe_ratio)}</span>
          {bm && <Versus text={versus("sharpe_ratio", m.sharpe_ratio, bm.sharpe_ratio)} />}
        </Row>
        <Row label="最大ドローダウン" help="資産額の山からの、いちばん大きな下がり幅。小さいほど良い">
          <span className="block text-[22px]">{formatPercent(m.max_drawdown)}</span>
          {bm && <Versus text={versus("max_drawdown", m.max_drawdown, bm.max_drawdown)} />}
        </Row>
        <Row label="最後の資産額" help="清算する前の額と、最後の日に売ったものとして手数料・スリッページを引いた額">
          <span className="block text-[20px] tabular">{formatYen(m.final_equity)}</span>
          <span className="block text-[13px] font-normal text-ink-2 tabular">清算したあと {formatYen(m.liquidated_equity)}</span>
        </Row>
        <Row label="年率リターン" help="1年あたりに直した値(期間が1年未満なら参考)">
          <span className="block text-[22px]">{formatPercent(m.annualized_return, { signed: true })}</span>
        </Row>
        <Row
          label="使う期間で買い持ちを上回った区切り"
          help="区切りごとに、その使う期間だけの買い持ちと総リターンを比べた数(買い持ちを買えた区切りだけ)"
        >
          <span className="block text-[22px]">
            {result.compared_windows > 0 ? `${count.format(result.compared_windows)}回中 ${count.format(result.beats_benchmark)}回` : "−"}
          </span>
        </Row>
        <Row
          label="日数を選び直した回数"
          help="選んだ組み合わせが前の区切りから変わった回数。毎回大きく変わるなら、その時々のたまたまを追いかけているかもしれません"
        >
          <span className="block text-[22px]">
            {windows > 1 ? `${count.format(windows - 1)}回中 ${count.format(result.choice_changes)}回` : "−(区切り1回)"}
          </span>
        </Row>
        <Row
          label="試した組み合わせ"
          help="区切りごとにこの数を試して選びました。設定を変えて何度も試すと、その選び方自体が過剰最適化になります"
        >
          <span className="block text-[22px]">{count.format(result.count)}通り</span>
          <span className="block text-[13px] font-normal text-ink-2">計算 {count.format(result.runs)}回</span>
        </Row>
        <Row label="使わなかった日" help="最後の区切りのあと、使う期間が丸ごと入らずに残った日">
          {result.unused ? (
            <>
              <span className="block text-[18px]">{count.format(result.unused.business_days)}営業日</span>
              <span className="block text-[13px] font-normal text-ink-2 tabular">
                {formatDate(result.unused.start_date)}〜{formatDate(result.unused.end_date)}
              </span>
            </>
          ) : (
            <span className="text-[18px]">なし</span>
          )}
        </Row>
      </dl>
      {unavailable && <p className="mt-2 text-[13px] leading-6 text-ink-2">※ {unavailable}。区切りごとの比較は、買えた使う期間だけで数えています。</p>}
    </section>
  );
}

function Versus({ text }: { text: string | null }) {
  if (text === null) return null;
  return <span className="block text-[13px] font-normal text-ink-2">{text}</span>;
}

function Row({ label, help, children }: { label: string; help: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-4 border-b border-rule py-3 sm:pr-6 sm:odd:border-r sm:even:pl-6">
      <dt className="text-[14px] text-ink-2">
        {label}
        <span className="block text-[12px] leading-5 text-ink-3">{help}</span>
      </dt>
      <dd className="text-right font-bold text-ink">{children}</dd>
    </div>
  );
}

// --- 区切りごとの表 ----------------------------------------------------------------------

function sameChoice(a: WalkForwardWindow | undefined, b: WalkForwardWindow): boolean {
  if (!a) return true;
  return a.chosen?.short_window === b.chosen?.short_window && a.chosen?.long_window === b.chosen?.long_window;
}

/** 使う期間の総リターンを、その使う期間だけの買い持ちと比べた言い方。比べられないときは「−」。 */
function windowVersus(w: WalkForwardWindow): { text: string; tone: string } {
  if (w.benchmark_total_return === null) return { text: "−", tone: "text-ink-3" };
  // 画面に出す桁で同じなら「同じ」(lib/benchmark.ts)
  switch (versusBenchmark(w.out_of_sample_metrics.total_return, w.benchmark_total_return, "total_return")) {
    case "良い":
      return { text: "上回った", tone: "text-ink" };
    case "同じ":
      return { text: "同じ", tone: "text-ink-2" };
    default:
      return { text: "下回った", tone: "text-ink-2" };
  }
}

function WindowTable({ result }: { result: WalkForwardResult }) {
  const headingId = useId();
  const objective = result.objective;
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="text-[18px] font-bold text-ink">
        区切りごとの結果
      </h3>
      <p className="mt-1 text-[13px] leading-6 text-ink-2">
        選ぶ期間({monthsText(result.in_sample_months)})の{OBJECTIVE_LABELS[objective]}で選んだ日数と、それを使った期間(
        {monthsText(result.out_of_sample_months)})の成績です。「変更」は前の区切りと違う日数を選んだ区切りです。
      </p>
      <ScrollRegion label="区切りごとの結果の表" className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[56rem] border-y border-rule text-[14px] tabular">
          <caption className="sr-only">区切りごとの、選んだ日数と使う期間の成績</caption>
          <thead className="text-[12px] text-ink-3">
            <tr className="border-b border-rule">
              <th scope="col" className="py-2 pr-3 text-left font-normal">
                区切り
              </th>
              <th scope="col" className="py-2 pr-3 text-left font-normal">
                選ぶ期間
              </th>
              <th scope="col" className="py-2 pr-3 text-left font-normal">
                選んだ日数
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-normal">
                選ぶ期間の{OBJECTIVE_LABELS[objective]}
              </th>
              <th scope="col" className="py-2 pr-3 text-left font-normal">
                使う期間
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-normal">
                総リターン
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-normal">
                買い持ち
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-normal">
                取引
              </th>
              <th scope="col" className="py-2 text-right font-normal">
                清算したあとの資産
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {result.windows.map((w, i) => {
              const changed = i > 0 && !sameChoice(result.windows[i - 1], w);
              const versus = windowVersus(w);
              const ret = w.out_of_sample_metrics.total_return;
              return (
                <tr key={w.index}>
                  <th scope="row" className="py-2 pr-3 text-left font-normal text-ink-2">
                    {w.index}
                  </th>
                  <td className="whitespace-nowrap py-2 pr-3 text-ink-2">
                    {formatDate(w.in_sample.start_date)}〜{formatDate(w.in_sample.end_date)}
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-ink">
                    {w.chosen ? (
                      <>
                        短期{w.chosen.short_window}・長期{w.chosen.long_window}
                        {changed && (
                          <span className="ml-2 rounded-sm px-1 text-[11px] text-ink-2 ring-1 ring-rule-strong">変更</span>
                        )}
                        {w.tie_count > 1 && (
                          <span className="block text-[11px] text-ink-3">同率{count.format(w.tie_count)}通りの最初</span>
                        )}
                      </>
                    ) : (
                      <span className="text-ink-2">選ばず(現金)</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right text-ink-2">{formatObjective(w.in_sample_value, objective)}</td>
                  <td className="whitespace-nowrap py-2 pr-3 text-ink-2">
                    {formatDate(w.out_of_sample.start_date)}〜{formatDate(w.out_of_sample.end_date)}
                  </td>
                  <td className={`py-2 pr-3 text-right font-bold ${TONE[direction(ret)]}`}>{formatPercent(ret, { signed: true })}</td>
                  <td className="whitespace-nowrap py-2 pr-3 text-right text-ink-2">
                    {w.benchmark_total_return === null ? "買えず" : formatPercent(w.benchmark_total_return, { signed: true })}
                    <span className={`block text-[11px] ${versus.tone}`}>{versus.text}</span>
                  </td>
                  <td className="py-2 pr-3 text-right text-ink-2">{count.format(w.out_of_sample_metrics.trade_count)}回</td>
                  <td className="whitespace-nowrap py-2 text-right text-ink">
                    {formatYen(w.liquidated_equity)}
                    {w.ended_with_shares && <span className="block text-[11px] text-ink-3">最終日に清算</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollRegion>
    </section>
  );
}

// --- 注意 ---------------------------------------------------------------------------

function Notes({ result, elapsedMs }: { result: WalkForwardResult; elapsedMs: number | null }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="border-t border-rule pt-6">
      <h3 id={headingId} className="text-[16px] font-bold text-ink">
        この結果を読むときの注意
      </h3>
      <ul className="mt-2 space-y-1.5 text-[14px] leading-7 text-ink-2">
        {result.notes.map((note) => (
          <li key={`${note.kind}-${note.message}`} className="flex gap-2">
            <span aria-hidden="true" className="text-ink-3">
              ※
            </span>
            <span>{note.message}</span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[13px] leading-6 text-ink-3">
        計算:{result.engine.label}
        {elapsedMs !== null && `(${(elapsedMs / 1000).toFixed(1)}秒・${count.format(result.runs)}回)`}。データ:{result.data_info.source_label}
        {result.data_info.fetched_at ? `(${formatDateTimeJst(result.data_info.fetched_at)} 取得・日本時間)` : ""}
      </p>
    </section>
  );
}
