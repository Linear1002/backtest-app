"use client";

// 総当たりの結果の画面(docs/sweep.md 7章・8章)。
// 何通り試したか・選ぶ期間の1位・その組み合わせの検証期間の成績を、いちばん上に並べて見せる(過剰最適化を隠さない)。
// 画面の見方(並べる基準・色を付ける期間・選んだ組み合わせ)は lib/flow.ts が持つ(1組の結果を見て戻ってきても残る)。

import { memo, useCallback, useId, useMemo, useState } from "react";

import type { Objective, SegmentName, SweepCombo, SweepMetrics, SweepResult, SweepSegment } from "@/lib/api.ts";
import type { SweepRecord, SweepViewState } from "@/lib/flow.ts";
import { direction, formatDate, formatDateTimeJst, formatNumber, formatPercent, formatRatePct, formatYen } from "@/lib/format.ts";
import {
  competitionRank,
  competitionRanks,
  correlationReading,
  OBJECTIVE_LABELS,
  OBJECTIVES,
  rankingFor,
  segmentValues,
  sharpeStandardError,
  uniqueBest,
} from "@/lib/sweep.ts";

import { SecondaryButton } from "../ui.tsx";
import { formatObjective, Heatmap, SEGMENT_LABELS } from "./Heatmap.tsx";

const TONE = { up: "text-shu", down: "text-ai", flat: "text-ink" } as const;
const count = new Intl.NumberFormat("ja-JP");
const TOP = 10;

export function SweepView({
  record,
  view,
  onViewChange,
  onEditParams,
  onRestart,
  onInspect,
}: {
  record: SweepRecord;
  view: SweepViewState;
  onViewChange: (view: Partial<SweepViewState>) => void;
  onEditParams: () => void;
  onRestart: () => void;
  /** 1つの組み合わせを、その期間の通常のバックテストで詳しく見る */
  onInspect: (short: number, long: number, segment: SegmentName) => void;
}) {
  const headingId = useId();
  const result = record.result;
  const { objective, segment, selected } = view;
  const ranking = rankingFor(result.rankings, objective);
  const best = uniqueBest(ranking);
  const hasHoldout = result.segments.some((s) => s.name === "out_of_sample");
  // ヒートマップのマスを描き直さないように、描き直しで変わらない関数にする
  const select = useCallback((index: number) => onViewChange({ selected: index }), [onViewChange]);

  return (
    <article aria-labelledby={headingId} className="space-y-10">
      <Header result={result} headingId={headingId} onEditParams={onEditParams} onRestart={onRestart} />
      <Summary
        result={result}
        objective={objective}
        onObjective={(o) => {
          // 基準を変えたら、その基準の1位を選び直す(同率1位なら選ばない)
          onViewChange({ objective: o, selected: uniqueBest(rankingFor(result.rankings, o)) });
        }}
        hasHoldout={hasHoldout}
      />
      <section aria-label="ヒートマップ" className="rounded-md border border-rule bg-surface p-3 sm:p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-[16px] font-bold text-ink">
            {OBJECTIVE_LABELS[objective]}のヒートマップ({SEGMENT_LABELS[segment]})
          </h3>
          {hasHoldout && (
            <div role="group" aria-label="色を付ける期間" className="flex gap-2">
              {(["in_sample", "out_of_sample"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={segment === s}
                  onClick={() => onViewChange({ segment: s })}
                  className={`rounded-full px-3 py-1 text-[13px] ${
                    segment === s ? "bg-ink text-paper" : "text-ink-2 ring-1 ring-rule-strong hover:bg-surface-2"
                  }`}
                >
                  {SEGMENT_LABELS[s]}
                </button>
              ))}
            </div>
          )}
        </div>
        {segment === "out_of_sample" && (
          <p className="mb-3 rounded-md border border-rule-strong px-3 py-2 text-[13px] leading-6 text-ink-2">
            検証期間の色は、選ぶ期間で選んだ組み合わせを<b className="text-ink">確かめるため</b>のものです。
            ここで良い組み合わせを選び直すと、検証期間も選ぶのに使ったことになり、確かめたことになりません。
          </p>
        )}
        <Heatmap
          key={objective}
          result={result}
          objective={objective}
          segment={segment}
          bestIndex={best}
          selected={selected}
          onSelect={select}
        />
        <p className="mt-3 text-[13px] leading-6 text-ink-3">
          1位のまわりも良い(なだらかな山)なら、日数を少し変えても成績が崩れにくいことは分かります。ただし、となりの組み合わせはほとんど同じ売買をするので、
          たまたまではない証拠にはなりません。1マスだけ飛び抜けているなら疑ってください。
          {hasHoldout && "「検証期間」に切り替えると、選ぶのに使っていない期間で同じ組み合わせがどうだったかを見られます(並べ替えは選ぶ期間のまま)。"}
        </p>
        <AllCombosTable result={result} objective={objective} />
      </section>
      {selected !== null && (
        <ComboDetail result={result} index={selected} objective={objective} isBest={selected === best} onInspect={onInspect} />
      )}
      <TopTable result={result} objective={objective} onSelect={select} />
      <Notes result={result} elapsedMs={record.elapsedMs} />
    </article>
  );
}

// --- 見出し ---------------------------------------------------------------------------

function segmentPeriod(segment: SweepSegment): string {
  return `${formatDate(segment.first_business_day)}〜${formatDate(segment.last_business_day)}(${count.format(segment.business_days)}営業日)`;
}

function Header({
  result,
  headingId,
  onEditParams,
  onRestart,
}: {
  result: SweepResult;
  headingId: string;
  onEditParams: () => void;
  onRestart: () => void;
}) {
  const g = result.grid;
  const inSample = result.segments.find((s) => s.name === "in_sample")!;
  const outOfSample = result.segments.find((s) => s.name === "out_of_sample") ?? null;
  return (
    <header className="grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
      <div>
        {/* 結果が出たら、ほかの手順と同じく見出しにフォーカスを移す(BacktestApp) */}
        <h2 id={headingId} data-step-heading tabIndex={-1} className="text-[24px] font-bold text-ink outline-none sm:text-[28px]">
          <span className="sr-only">手順5:総当たりの結果 </span>
          {result.symbol.name}
          <span className="ml-3 tabular text-[15px] font-normal text-ink-2">{result.symbol.id}</span>
        </h2>
        <p className="mt-1 text-[14px] text-ink-2">
          移動平均クロスの日数の総当たり:短期{g.short_min}〜{g.short_max}日({g.short_step}日ごと)× 長期{g.long_min}〜{g.long_max}日(
          {g.long_step}日ごと)
        </p>
        <p className="mt-0.5 text-[13px] text-ink-3 tabular">
          {outOfSample ? "選ぶ期間" : "期間"} {segmentPeriod(inSample)}
          {outOfSample ? ` ・ 検証期間 ${segmentPeriod(outOfSample)}` : " ・ 検証期間なし"}
        </p>
        {inSample.start_date !== inSample.requested_start_date && (
          <p className="mt-0.5 text-[13px] text-ink-3">
            ※ すべての組み合わせを同じ日から比べるため、{formatDate(inSample.requested_start_date)}からの
            {count.format(inSample.skipped_trading_days)}営業日は、移動平均を作るため(ウォームアップ)にだけ使いました。
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

function Summary({
  result,
  objective,
  onObjective,
  hasHoldout,
}: {
  result: SweepResult;
  objective: Objective;
  onObjective: (objective: Objective) => void;
  hasHoldout: boolean;
}) {
  const headingId = useId();
  const ranking = rankingFor(result.rankings, objective);
  const bestIndex = uniqueBest(ranking);
  const best = bestIndex !== null ? result.combos[bestIndex] : null;
  const tied = ranking.best_tie_count > 1 ? ranking.best_tie_count : 0;
  const tiedValue = tied && ranking.best_index !== null ? result.combos[ranking.best_index].in_sample : null;
  const value = (m: SweepMetrics | null) => formatObjective(m ? (m[objective] as number | null) : null, objective);
  const outOfSample = result.segments.find((s) => s.name === "out_of_sample");
  const error = outOfSample ? sharpeStandardError(outOfSample.business_days, result.params.trading_days_per_year) : null;
  return (
    <section aria-labelledby={headingId}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 id={headingId} className="text-[18px] font-bold text-ink">
          まとめ
        </h3>
        <div role="group" aria-label="並べる基準" className="flex flex-wrap gap-2">
          {OBJECTIVES.map((o) => (
            <button
              key={o}
              type="button"
              aria-pressed={objective === o}
              onClick={() => onObjective(o)}
              className={`rounded-full px-3 py-1 text-[13px] ${
                objective === o ? "bg-ink text-paper" : "text-ink-2 ring-1 ring-rule-strong hover:bg-surface"
              }`}
            >
              {OBJECTIVE_LABELS[o]}で並べる
            </button>
          ))}
        </div>
      </div>
      {objective === "max_drawdown" && (
        <p className="mt-2 text-[13px] leading-6 text-ink-3">
          ※ 最大ドローダウンで並べると、売買の少ない組み合わせほど上に来ます(株を一度も持たなければ0%)。
        </p>
      )}
      <dl className="mt-3 grid border-t border-rule sm:grid-cols-2">
        <Row label="試した組み合わせ" help="たくさん試すほど、たまたま良いものが見つかりやすくなります">
          <span className="text-[22px]">{count.format(result.count)}通り</span>
        </Row>
        <Row label={`選ぶ期間の1位(${OBJECTIVE_LABELS[objective]})`} help="選ぶ期間の成績だけで決めた1位">
          {best ? (
            <>
              <span className="block text-[22px]">
                短期{best.short_window}日・長期{best.long_window}日
              </span>
              <span className="text-[15px] font-normal text-ink-2">{value(best.in_sample)}</span>
              {best.in_sample.holding_days === 0 && (
                <span className="block text-[13px] font-normal text-ink-2">この期間は一度も株を持っていません</span>
              )}
            </>
          ) : tied ? (
            <>
              <span className="block text-[18px]">同率1位が{count.format(tied)}通り</span>
              <span className="text-[13px] font-normal text-ink-2">
                すべて{value(tiedValue)}のため、1位は決められません
              </span>
            </>
          ) : (
            <span className="text-[15px] font-normal text-ink-2">値を出せる組み合わせがありません</span>
          )}
        </Row>
        {hasHoldout ? (
          <>
            <Row label="その組み合わせの検証期間" help="選ぶのに使っていない期間での成績">
              {best ? (
                <>
                  <span className="block text-[22px]">{value(best.out_of_sample)}</span>
                  {ranking.best_out_of_sample_rank !== null && (
                    <span className="block text-[14px] font-normal text-ink-2">
                      検証期間では {count.format(ranking.out_of_sample_ranked)}通り中 {ranking.best_out_of_sample_rank}位
                    </span>
                  )}
                  {objective === "sharpe_ratio" && error !== null && (
                    <span className="block text-[12px] font-normal text-ink-3">偶然だけでも ±{error.toFixed(1)} 程度ぶれます(目安)</span>
                  )}
                </>
              ) : (
                <span className="text-[15px] font-normal text-ink-2">1位が決まらないため出しません</span>
              )}
            </Row>
            <Row
              label="順位の相関(選ぶ期間 ↔ 検証期間)"
              help={correlationReading(ranking.rank_correlation, ranking.correlation_pairs)}
            >
              <span className="block text-[22px]">
                {ranking.rank_correlation === null ? "−" : formatNumber(ranking.rank_correlation)}
              </span>
              {ranking.rank_correlation !== null && (
                <span className="text-[13px] font-normal text-ink-2">{count.format(ranking.correlation_pairs)}通りで計算</span>
              )}
            </Row>
          </>
        ) : (
          <Row label="検証期間" help="選んだ組み合わせが、ほかの期間でも通用するかは確かめていません">
            <span className="text-[18px]">なし</span>
          </Row>
        )}
        <Row
          label="1位のとなりの平均"
          help={`格子で1位のとなり(短期・長期それぞれ1刻み前後)の、選ぶ期間の${OBJECTIVE_LABELS[objective]}の平均`}
        >
          {ranking.neighbors_mean === null ? (
            "−"
          ) : (
            <>
              <span className="block text-[22px]">{formatObjective(ranking.neighbors_mean, objective)}</span>
              <span className="text-[14px] font-normal text-ink-2">となり{ranking.neighbors_count}通り</span>
            </>
          )}
        </Row>
      </dl>
    </section>
  );
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

// --- 選んだ組み合わせ ------------------------------------------------------------------

const DETAIL_ROWS: {
  label: string;
  render: (m: SweepMetrics, tradingDays: number, segment: SweepSegment) => React.ReactNode;
}[] = [
  {
    label: "総リターン",
    render: (m) => <span className={TONE[direction(m.total_return)]}>{formatPercent(m.total_return, { signed: true })}</span>,
  },
  {
    label: "年率リターン",
    render: (m, days) => (
      <>
        <span className={TONE[direction(m.annualized_return)]}>{formatPercent(m.annualized_return, { signed: true })}</span>
        {m.annualized_return !== null && m.return_count < days && <span className="ml-1 text-[12px] font-normal text-ink-3">参考値</span>}
      </>
    ),
  },
  { label: "最大ドローダウン", render: (m) => formatPercent(m.max_drawdown) },
  { label: "シャープレシオ", render: (m) => formatNumber(m.sharpe_ratio) },
  {
    label: "勝率",
    render: (m) =>
      `${formatPercent(m.win_rate, { digits: 1, nullLabel: "−" })}${m.trade_count > 0 ? `(${m.winning_trades}勝${m.trade_count - m.winning_trades}敗)` : ""}`,
  },
  { label: "取引回数", render: (m) => `${m.trade_count}回` },
  {
    label: "株を持っていた日",
    render: (m, _days, segment) => `${count.format(m.holding_days)} / ${count.format(segment.business_days)}営業日`,
  },
  { label: "資金不足で見送り", render: (m) => `${m.insufficient_cash_count}回` },
  { label: "最終資産", render: (m) => formatYen(m.final_equity) },
];

function ComboDetail({
  result,
  index,
  objective,
  isBest,
  onInspect,
}: {
  result: SweepResult;
  index: number;
  objective: Objective;
  isBest: boolean;
  onInspect: (short: number, long: number, segment: SegmentName) => void;
}) {
  const headingId = useId();
  const combo = result.combos[index];
  const ranking = rankingFor(result.rankings, objective);
  const isRank = competitionRank(segmentValues(result.combos, "in_sample", objective), index, objective);
  const oosRank = combo.out_of_sample
    ? competitionRank(segmentValues(result.combos, "out_of_sample", objective), index, objective)
    : null;
  const days = result.params.trading_days_per_year;
  const inSample = result.segments.find((s) => s.name === "in_sample")!;
  const outOfSample = result.segments.find((s) => s.name === "out_of_sample") ?? null;
  return (
    <section aria-labelledby={headingId}>
      {/* ヒートマップや表で選んだときに、読み上げで選んだことが分かるように */}
      <p className="sr-only" aria-live="polite">
        短期{combo.short_window}日・長期{combo.long_window}日を選びました
      </p>
      <h3 id={headingId} className="text-[18px] font-bold text-ink">
        選んだ組み合わせ:短期{combo.short_window}日・長期{combo.long_window}日
        {isBest && <span className="ml-2 text-[13px] font-normal text-ink-2">選ぶ期間の1位</span>}
      </h3>
      <p className="mt-1 text-[13px] text-ink-3">
        {OBJECTIVE_LABELS[objective]}の順位:
        {isRank === null ? "選ぶ期間 −(算出不可)" : `選ぶ期間 ${count.format(ranking.in_sample_ranked)}通り中 ${isRank}位`}
        {oosRank !== null && ` ・ 検証期間 ${count.format(ranking.out_of_sample_ranked)}通り中 ${oosRank}位`}
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[20rem] text-[14px] tabular">
          <caption className="sr-only">選んだ組み合わせの、期間ごとの成績</caption>
          <thead className="border-y border-rule-strong text-ink-2">
            <tr>
              <th scope="col" className="py-2 pr-3 text-left font-normal">
                成績
              </th>
              <th scope="col" className="px-3 py-2 text-right font-normal">
                選ぶ期間
              </th>
              {combo.out_of_sample && (
                <th scope="col" className="py-2 pl-3 text-right font-normal">
                  検証期間
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {DETAIL_ROWS.map((row) => (
              <tr key={row.label}>
                <th scope="row" className="py-2 pr-3 text-left font-normal text-ink-2">
                  {row.label}
                </th>
                <td className="px-3 py-2 text-right text-ink">{row.render(combo.in_sample, days, inSample)}</td>
                {combo.out_of_sample && outOfSample && (
                  <td className="py-2 pl-3 text-right text-ink">{row.render(combo.out_of_sample, days, outOfSample)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <SecondaryButton onClick={() => onInspect(combo.short_window, combo.long_window, "in_sample")}>
          {outOfSample ? "選ぶ期間で詳しく見る(売買の記録まで)" : "この組み合わせで詳しく見る(売買の記録まで)"}
        </SecondaryButton>
        {outOfSample && (
          <SecondaryButton onClick={() => onInspect(combo.short_window, combo.long_window, "out_of_sample")}>
            検証期間で詳しく見る
          </SecondaryButton>
        )}
      </div>
      <p className="mt-2 text-[12px] leading-5 text-ink-3">
        その期間だけを1組のバックテストとして計算し直します(この表の数字と同じになります)。
      </p>
    </section>
  );
}

// --- 上位の表 ---------------------------------------------------------------------------

function TopTable({
  result,
  objective,
  onSelect,
}: {
  result: SweepResult;
  objective: Objective;
  onSelect: (index: number) => void;
}) {
  const headingId = useId();
  const ranking = rankingFor(result.rankings, objective);
  const hasHoldout = result.combos.some((c) => c.out_of_sample !== null);
  const isValues = segmentValues(result.combos, "in_sample", objective);
  const oosValues = segmentValues(result.combos, "out_of_sample", objective);
  const top = ranking.order.slice(0, TOP);
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="text-[18px] font-bold text-ink">
        選ぶ期間の上位{Math.min(TOP, result.count)}通り({OBJECTIVE_LABELS[objective]})
      </h3>
      <p className="mt-1 text-[13px] text-ink-3">順位は、同じ値なら同じ順位です。算出不可の組み合わせには順位を付けません。</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[36rem] whitespace-nowrap text-[14px] tabular">
          <caption className="sr-only">選ぶ期間の成績のよい順</caption>
          <thead className="border-y border-rule-strong text-ink-2">
            <tr>
              <th scope="col" className="py-2 pr-3 text-left font-normal">順位</th>
              <th scope="col" className="px-3 py-2 text-left font-normal">組み合わせ</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">選ぶ期間</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">取引回数</th>
              {hasHoldout && <th scope="col" className="px-3 py-2 text-right font-normal">検証期間</th>}
              {hasHoldout && <th scope="col" className="py-2 pl-3 text-right font-normal">検証期間での順位</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {top.map((index) => {
              const combo = result.combos[index];
              const isRank = competitionRank(isValues, index, objective);
              const oosRank = combo.out_of_sample ? competitionRank(oosValues, index, objective) : null;
              return (
                <tr key={index}>
                  <td className="py-2 pr-3 text-left text-ink-2">{isRank ?? "−"}</td>
                  <td className="px-3 py-2 text-left">
                    <button
                      type="button"
                      onClick={() => onSelect(index)}
                      className="text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
                    >
                      短期{combo.short_window}日・長期{combo.long_window}日
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right text-ink">
                    {formatObjective(combo.in_sample[objective] as number | null, objective)}
                  </td>
                  <td className="px-3 py-2 text-right text-ink-2">{combo.in_sample.trade_count}回</td>
                  {hasHoldout && (
                    <td className="px-3 py-2 text-right text-ink">
                      {formatObjective((combo.out_of_sample?.[objective] as number | null) ?? null, objective)}
                    </td>
                  )}
                  {hasHoldout && (
                    <td className="py-2 pl-3 text-right text-ink-2">
                      {oosRank === null ? "−" : `${oosRank}位 / ${count.format(ranking.out_of_sample_ranked)}`}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * すべての組み合わせの表(ヒートマップの表版。色を見分けにくいときも、値はここで読める)。
 * 2,000行になることがあるので、マスを選んでも描き直さないようにしてある(memo)。
 */
const AllCombosTable = memo(function AllCombosTable({ result, objective }: { result: SweepResult; objective: Objective }) {
  const [open, setOpen] = useState(false);
  const ranking = rankingFor(result.rankings, objective);
  const hasHoldout = result.combos.some((c) => c.out_of_sample !== null);
  // 順位は表を開いたとき(・基準を変えたとき)に1回だけ出す(2,000行で1行ずつ全部と比べると重いため)
  const ranks = useMemo(
    () => (open ? competitionRanks(segmentValues(result.combos, "in_sample", objective), objective) : []),
    [open, result.combos, objective],
  );
  const cell = (combo: SweepCombo, which: "in_sample" | "out_of_sample", key: Objective) => {
    const m = combo[which];
    return m ? formatObjective(m[key] as number | null, key) : "−";
  };
  return (
    <div className="mt-4 border-t border-rule pt-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="text-[14px] text-ink-2 underline decoration-rule-strong underline-offset-4 hover:text-ink"
      >
        {open ? "すべての組み合わせの表を閉じる" : `すべての組み合わせを表で見る(${count.format(result.count)}通り)`}
      </button>
      {open && (
        <div className="mt-3 max-h-[28rem] overflow-auto rounded-md border border-rule">
          <table className="w-full min-w-[48rem] text-[13px] tabular">
            <caption className="sr-only">すべての組み合わせの成績(選ぶ期間の{OBJECTIVE_LABELS[objective]}のよい順)</caption>
            <thead className="sticky top-0 bg-surface-2 text-ink-2">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-normal">順位</th>
                <th scope="col" className="px-3 py-2 text-left font-normal">短期</th>
                <th scope="col" className="px-3 py-2 text-left font-normal">長期</th>
                {OBJECTIVES.map((o) => (
                  <th key={o} scope="col" className="px-3 py-2 text-right font-normal">
                    {OBJECTIVE_LABELS[o]}
                  </th>
                ))}
                <th scope="col" className="px-3 py-2 text-right font-normal">取引</th>
                {hasHoldout &&
                  OBJECTIVES.map((o) => (
                    <th key={`oos-${o}`} scope="col" className="px-3 py-2 text-right font-normal">
                      検証:{OBJECTIVE_LABELS[o]}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {ranking.order.map((index) => {
                const combo = result.combos[index];
                return (
                  <tr key={index}>
                    <td className="px-3 py-1.5 text-left text-ink-2">{ranks[index] ?? "−"}</td>
                    <td className="px-3 py-1.5 text-left">{combo.short_window}日</td>
                    <td className="px-3 py-1.5 text-left">{combo.long_window}日</td>
                    {OBJECTIVES.map((o) => (
                      <td key={o} className="px-3 py-1.5 text-right">
                        {cell(combo, "in_sample", o)}
                      </td>
                    ))}
                    <td className="px-3 py-1.5 text-right">{combo.in_sample.trade_count}回</td>
                    {hasHoldout &&
                      OBJECTIVES.map((o) => (
                        <td key={`oos-${o}`} className="px-3 py-1.5 text-right">
                          {cell(combo, "out_of_sample", o)}
                        </td>
                      ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
});

// --- 注記 -------------------------------------------------------------------------------

function Notes({ result, elapsedMs }: { result: SweepResult; elapsedMs: number | null }) {
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
        {elapsedMs !== null && `(${(elapsedMs / 1000).toFixed(1)}秒・${count.format(result.count)}通り)`}。データ:{result.data_info.source_label}
        {result.data_info.fetched_at ? `(${formatDateTimeJst(result.data_info.fetched_at)} 取得・日本時間)` : ""}
      </p>
    </section>
  );
}
