"use client";

import { useEffect, useId, useState } from "react";

import type { BacktestResult, Trade } from "@/lib/api.ts";
import type { RunRecord } from "@/lib/flow.ts";
import {
  direction,
  formatDate,
  formatDateTimeJst,
  formatDecimal,
  formatNumber,
  formatPercent,
  formatPrice,
  formatRatePct,
  formatShares,
  formatSignedYen,
  formatYen,
} from "@/lib/format.ts";

import { Seal } from "../Seal.tsx";
import { SecondaryButton } from "../ui.tsx";
import { TimeSeriesCharts } from "./TimeSeriesCharts.tsx";

const TONE = { up: "text-shu", down: "text-ai", flat: "text-ink" } as const;

/**
 * 結果が出たときの動き(線を描く・印を押す)が終わるまでの時間。終わったら「再生済み」にする。
 * globals.css のいちばん長い動き(印の遅れ 最大900ms + 500ms + 押す動き 260ms = 1660ms)より長くする
 */
const ANIMATION_MS = 1800;

export function ResultView({
  record,
  animate,
  onAnimated,
  onEditParams,
  onRestart,
}: {
  record: RunRecord;
  /** 結果が出たときの動きを再生するか(同じ結果に戻ってきたときは再生しない) */
  animate: boolean;
  onAnimated: (id: number) => void;
  onEditParams: () => void;
  onRestart: () => void;
}) {
  const headingId = useId();
  const result = record.result;
  // 権利落ちは、この結果と一緒に返ってきたもの(期間内・株を持っていない日も含む)を使う。
  // 係数が1の日は、何も起きていないので描かない
  const actions = result.corporate_actions.filter((a) => a.adj_factor !== 1);

  useEffect(() => {
    if (!animate) return;
    const timer = setTimeout(() => onAnimated(record.id), ANIMATION_MS);
    return () => clearTimeout(timer);
  }, [animate, onAnimated, record.id]);

  return (
    <article aria-labelledby={headingId} className="space-y-10">
      <Statement result={result} headingId={headingId} onEditParams={onEditParams} onRestart={onRestart} />
      <Metrics result={result} />
      <section aria-label="チャート" className="rounded-md border border-rule bg-surface p-3 sm:p-5">
        <TimeSeriesCharts result={result} actions={actions} animate={animate} />
        <DailyTable result={result} />
      </section>
      <TradeLedger result={result} />
      <Activity result={result} />
      <Notes result={result} />
    </article>
  );
}

// --- 計算書(いちばん上) -----------------------------------------------------------

function Statement({
  result,
  headingId,
  onEditParams,
  onRestart,
}: {
  result: BacktestResult;
  headingId: string;
  onEditParams: () => void;
  onRestart: () => void;
}) {
  const m = result.metrics;
  const tone = TONE[direction(m.profit)];
  return (
    <header className="grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
      <div>
        {/* 結果が出たら、ほかの手順と同じく見出しにフォーカスを移す(BacktestApp) */}
        <h2
          id={headingId}
          data-step-heading
          tabIndex={-1}
          className="text-[24px] font-bold text-ink outline-none sm:text-[28px]"
        >
          <span className="sr-only">手順5:結果 </span>
          {result.symbol.name}
          <span className="ml-3 tabular text-[15px] font-normal text-ink-2">{result.symbol.id}</span>
        </h2>
        <p className="mt-1 text-[14px] text-ink-2">
          移動平均クロス(短期{result.params.short_window}日・長期{result.params.long_window}日)/
          <span className="tabular">
            {formatDate(result.period.first_business_day)}〜{formatDate(result.period.last_business_day)}
          </span>
          ({result.period.business_days.toLocaleString("ja-JP")}営業日)
        </p>
        <p className="mt-0.5 text-[13px] text-ink-3">
          手数料率 {formatRatePct(result.params.fee_rate_pct)}・スリッページ率 {formatRatePct(result.params.slippage_rate_pct)}
          ・売買単位 {result.params.lot_size}株
        </p>
        <div className="mt-5 max-w-[34rem]">
          <div className="flex items-baseline justify-between gap-6 border-b border-rule py-2">
            <span className="text-[14px] text-ink-2">初期資金</span>
            <span className="text-[17px] text-ink">{formatYen(result.params.initial_cash)}</span>
          </div>
          <div className="flex items-baseline justify-between gap-6 py-2">
            <span className="text-[14px] text-ink-2">損益</span>
            <span className={`text-[17px] font-bold ${tone}`}>
              {formatSignedYen(m.profit)}({formatPercent(m.total_return, { signed: true })})
            </span>
          </div>
          <div className="closing-rule flex items-baseline justify-between gap-6 border-t border-ink pb-2 pt-3">
            <span className="text-[15px] font-bold text-ink">最終資産</span>
            <span className="text-[34px] font-bold leading-none text-ink sm:text-[44px]">
              {formatYen(m.final_equity)}
            </span>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 lg:justify-end">
        <SecondaryButton onClick={onEditParams}>条件を変えて試す</SecondaryButton>
        <SecondaryButton onClick={onRestart}>別の銘柄で試す</SecondaryButton>
      </div>
    </header>
  );
}

// --- 成績表 -----------------------------------------------------------------------

function Metrics({ result }: { result: BacktestResult }) {
  const headingId = useId();
  const m = result.metrics;
  // 値が出せないとき(算出不可)は「参考値」を付けない
  const reference = m.annualized_return !== null && result.notes.some((n) => n.kind === "annualized_reference");
  const losses = m.trade_count - m.winning_trades;
  const rows: { label: string; value: React.ReactNode; help: string }[] = [
    {
      label: "総リターン",
      value: <span className={TONE[direction(m.total_return)]}>{formatPercent(m.total_return, { signed: true })}</span>,
      help: "最終資産 ÷ 初期資金 − 1",
    },
    {
      label: "年率リターン",
      value: (
        <>
          <span className={TONE[direction(m.annualized_return)]}>
            {formatPercent(m.annualized_return, { signed: true })}
          </span>
          {reference && <span className="ml-2 text-[12px] font-normal text-ink-3">参考値</span>}
        </>
      ),
      help: `1年(${result.params.trading_days_per_year}営業日)あたりに直した値`,
    },
    {
      label: "最大ドローダウン",
      value: formatPercent(m.max_drawdown),
      help: "それまでの最高値から最も大きく減ったときの割合",
    },
    {
      label: "シャープレシオ",
      value: formatNumber(m.sharpe_ratio),
      help: "値動きの大きさの割に、どれだけ増えたか(無リスク金利0)",
    },
    {
      label: "勝率",
      value: (
        <>
          {formatPercent(m.win_rate, { digits: 1, nullLabel: "−" })}
          {m.trade_count > 0 && (
            <span className="ml-2 text-[12px] font-normal text-ink-3">
              {m.winning_trades}勝{losses}敗
            </span>
          )}
        </>
      ),
      help: "決済した取引のうち、手数料などを引いて利益が出た割合",
    },
    { label: "取引回数", value: `${m.trade_count}回`, help: "買いから売りまでを1回と数える(未決済は含めない)" },
    {
      label: "資金不足で見送り",
      value: `${result.insufficient_cash_count}回`,
      help: "買いのシグナルが出たが、売買単位分の資金がなかった回数",
    },
  ];
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="text-[18px] font-bold text-ink">
        成績表
      </h3>
      <dl className="mt-3 grid border-t border-rule sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label} className="grid grid-cols-[1fr_auto] items-baseline gap-x-4 border-b border-rule py-3 sm:pr-6 sm:odd:border-r sm:even:pl-6">
            <dt className="text-[14px] text-ink-2">
              {row.label}
              <span className="block text-[12px] leading-5 text-ink-3">{row.help}</span>
            </dt>
            <dd className="text-right text-[20px] font-bold text-ink">{row.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[13px] leading-6 text-ink-3">
        {result.warmup.label}。計算:{result.engine.label}({result.elapsed_ms.toFixed(0)}ミリ秒)。データ:{result.data_info.source_label}
        {result.data_info.fetched_at ? `(${formatDateTimeJst(result.data_info.fetched_at)} 取得・日本時間)` : ""}
      </p>
    </section>
  );
}

// --- 日々の数値の表(チャートの表版) ------------------------------------------------

function DailyTable({ result }: { result: BacktestResult }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4 border-t border-rule pt-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="text-[14px] text-ink-2 underline decoration-rule-strong underline-offset-4 hover:text-ink"
      >
        {open ? "日々の数値の表を閉じる" : `日々の数値を表で見る(${result.daily.length.toLocaleString("ja-JP")}日分)`}
      </button>
      {open && (
        <div className="mt-3 max-h-[28rem] overflow-auto rounded-md border border-rule">
          <table className="w-full min-w-[44rem] text-[13px] tabular">
            <caption className="sr-only">日々の数値</caption>
            <thead className="sticky top-0 bg-surface-2 text-ink-2">
              <tr>
                {["日付", "終値", "短期線", "長期線", "株数", "現金", "資産額", "ドローダウン"].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2 text-right font-normal first:text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {result.daily.map((d) => (
                <tr key={d.date}>
                  <td className="px-3 py-1.5 text-left text-ink-2">{formatDate(d.date)}</td>
                  <td className="px-3 py-1.5 text-right">{d.close === null ? "売買なし" : formatPrice(d.close)}</td>
                  <td className="px-3 py-1.5 text-right">{formatPrice(d.short_ma)}</td>
                  <td className="px-3 py-1.5 text-right">{formatPrice(d.long_ma)}</td>
                  <td className="px-3 py-1.5 text-right">{d.shares.toLocaleString("ja-JP")}</td>
                  <td className="px-3 py-1.5 text-right">{formatYen(d.cash)}</td>
                  <td className="px-3 py-1.5 text-right">{formatYen(d.equity)}</td>
                  <td className="px-3 py-1.5 text-right">{formatPercent(d.drawdown, { digits: 1 })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --- 取引の記録(帳簿) --------------------------------------------------------------

/** 取引が0件のときの説明。なぜ0件なのかと、次に何をすればよいかを書く。 */
function emptyTradesMessage(result: BacktestResult): string {
  if (result.insufficient_cash_count > 0) {
    return "買いのシグナルは出ましたが、資金が売買単位分に足りなかったため、一度も買っていません。初期資金を増やして試してください。";
  }
  if (result.signals.some((s) => s.side === "buy" && s.action === "order")) {
    // シグナルの次の有効日に約定するので、期間の最終日のシグナルは約定しない(docs/mvp.md 2.6)
    return "買いのシグナルは出ましたが、期間の最後の日(またはその後に売買が成立しなかった日)だったため約定していません。終了日を後ろにずらして試してください。";
  }
  return "この期間には、買いのシグナルが出ませんでした。期間を広げるか、移動平均の日数を変えて試してください。";
}

function TradeLedger({ result }: { result: BacktestResult }) {
  const headingId = useId();
  const trades = result.trades;
  const closed = trades.filter((t) => t.pnl !== null);
  const total = closed.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
  const acrossSplit = trades.some(changedShares);
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="text-[18px] font-bold text-ink">
        取引の記録
      </h3>
      {trades.length === 0 ? (
        <p className="mt-3 text-[14px] text-ink-2">{emptyTradesMessage(result)}</p>
      ) : (
        <>
        <TradeList trades={trades} total={total} closedCount={closed.length} />
        <div className="mt-3 hidden overflow-x-auto sm:block">
          <table className="w-full min-w-[46rem] whitespace-nowrap text-[14px] tabular">
            <caption className="sr-only">買いから売りまでの取引の一覧</caption>
            <thead className="border-y border-rule-strong text-ink-2">
              <tr>
                <th scope="col" className="py-2 pr-3 text-left font-normal">買い</th>
                <th scope="col" className="px-3 py-2 text-right font-normal">買値</th>
                <th scope="col" className="px-3 py-2 text-right font-normal">株数</th>
                <th scope="col" className="px-3 py-2 text-left font-normal">売り</th>
                <th scope="col" className="px-3 py-2 text-right font-normal">売値</th>
                <th scope="col" className="px-3 py-2 text-right font-normal">損益</th>
                <th scope="col" className="py-2 pl-3 text-right font-normal">損益率</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {trades.map((t) => (
                <TradeRow key={`${t.entry_date}-${t.exit_date ?? "open"}`} trade={t} />
              ))}
            </tbody>
            <tfoot>
              <tr className="closing-rule border-t border-ink">
                <th scope="row" colSpan={5} className="py-2 pr-3 text-left font-bold text-ink">
                  決済した取引の損益の合計({closed.length}回)
                </th>
                <td className={`px-3 py-2 text-right font-bold ${TONE[direction(total)]}`}>{formatSignedYen(total)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
        {acrossSplit && (
          <p className="mt-2 text-[13px] leading-6 text-ink-3">
            ※ 分割・併合をまたいだ取引は、株数を「買った株数 → 売った株数」で示しています。売値は分割・併合の後の株価です。
          </p>
        )}
        </>
      )}
    </section>
  );
}

/** 分割・併合で、買ったときと売ったときの株数が違う取引か。 */
function changedShares(t: Trade): boolean {
  return t.exit_shares !== null && t.exit_shares !== t.entry_shares;
}

function sharesText(t: Trade): string {
  return changedShares(t)
    ? `${formatShares(t.entry_shares)} → ${formatShares(t.exit_shares ?? 0)}`
    : formatShares(t.entry_shares);
}

/** 画面が狭いときの取引の記録(1取引を2行で書く)。 */
function TradeList({ trades, total, closedCount }: { trades: Trade[]; total: number; closedCount: number }) {
  return (
    <div className="mt-3 sm:hidden">
      <ol className="divide-y divide-rule border-y border-rule text-[14px] tabular">
        {trades.map((t) => {
          const tone = TONE[direction(t.pnl)];
          return (
            <li key={`${t.entry_date}-${t.exit_date ?? "open"}`} className="py-2.5">
              <div className="flex items-center justify-between gap-3">
                <span className="inline-flex items-center gap-2">
                  <Seal kind="buy" size={20} />
                  {formatDate(t.entry_date)}
                </span>
                <span className="text-ink-2">
                  {formatPrice(t.entry_price)} × {sharesText(t)}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between gap-3">
                {t.exit_date ? (
                  <span className="inline-flex items-center gap-2">
                    {t.closed_by === "sell" ? <Seal kind="sell" size={20} /> : <span className="text-[12px] text-ink-3">併合</span>}
                    {formatDate(t.exit_date)}
                  </span>
                ) : (
                  <span className="text-ink-3">保有中(期間の終わりまで)</span>
                )}
                <span className={`font-bold ${tone}`}>
                  {t.pnl === null ? "−" : formatSignedYen(t.pnl)}
                  {t.return_pct !== null && (
                    <span className="ml-1 text-[12px] font-normal">
                      ({formatPercent(t.return_pct / 100, { signed: true })})
                    </span>
                  )}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="closing-rule flex items-baseline justify-between border-t border-ink py-2 text-[14px]">
        <span className="font-bold text-ink">決済した取引の合計({closedCount}回)</span>
        <span className={`font-bold ${TONE[direction(total)]}`}>{formatSignedYen(total)}</span>
      </div>
    </div>
  );
}

function TradeRow({ trade: t }: { trade: Trade }) {
  const tone = TONE[direction(t.pnl)];
  return (
    <tr>
      <td className="py-2 pr-3 text-left">
        <span className="inline-flex items-center gap-2">
          <Seal kind="buy" size={20} />
          {formatDate(t.entry_date)}
        </span>
      </td>
      <td className="px-3 py-2 text-right">{formatPrice(t.entry_price)}</td>
      <td className="px-3 py-2 text-right">{sharesText(t)}</td>
      <td className="px-3 py-2 text-left">
        {t.exit_date ? (
          <span className="inline-flex items-center gap-2">
            {t.closed_by === "sell" ? <Seal kind="sell" size={20} /> : <span className="text-[12px] text-ink-3">併合</span>}
            {formatDate(t.exit_date)}
          </span>
        ) : (
          <span className="text-ink-3">保有中(期間の終わりまで)</span>
        )}
      </td>
      <td className="px-3 py-2 text-right">{t.exit_price === null ? "−" : formatPrice(t.exit_price)}</td>
      <td className={`px-3 py-2 text-right ${tone}`}>{t.pnl === null ? "−" : formatSignedYen(t.pnl)}</td>
      <td className={`py-2 pl-3 text-right ${tone}`}>
        {t.return_pct === null ? "−" : formatPercent(t.return_pct / 100, { signed: true })}
      </td>
    </tr>
  );
}

// --- シグナル・見送り・分割の処理 -------------------------------------------------

function Activity({ result }: { result: BacktestResult }) {
  const headingId = useId();
  const ignored = result.signals.filter((s) => s.action === "ignored").length;
  return (
    <section aria-labelledby={headingId} className="grid gap-8 lg:grid-cols-2">
      <div>
        <h3 id={headingId} className="text-[18px] font-bold text-ink">
          シグナルの記録
        </h3>
        {result.signals.length === 0 ? (
          <p className="mt-1 text-[14px] leading-7 text-ink-2">
            この期間には、短期線と長期線のクロスが一度もありませんでした。期間を広げるか、移動平均の日数を短くして試してください。
          </p>
        ) : (
        <>
        <p className="mt-1 text-[13px] leading-6 text-ink-3">
          クロスを {result.signals.length} 回検出し、そのうち {ignored} 回は売買ルールにより見送りました
          (保有中の上抜け・未保有の下抜け)。
        </p>
        <details className="mt-2">
          <summary className="cursor-pointer text-[14px] text-ink-2 hover:text-ink">一覧を開く</summary>
          <ul className="mt-2 max-h-72 divide-y divide-rule overflow-auto border-y border-rule text-[13px] tabular">
            {result.signals.map((s) => (
              <li key={`${s.date}-${s.side}`} className="flex items-center justify-between gap-4 py-1.5">
                <span className="text-ink-2">{formatDate(s.date)}</span>
                <span className={s.action === "ignored" ? "text-ink-3" : "text-ink"}>
                  {s.side === "buy" ? "上抜け(買い)" : "下抜け(売り)"}
                  {s.action === "ignored" ? "・見送り" : ""}
                </span>
              </li>
            ))}
          </ul>
        </details>
        </>
        )}
      </div>
      <div className="space-y-6">
        {result.events.length > 0 && (
          <div>
            <h3 className="text-[18px] font-bold text-ink">分割・併合の処理</h3>
            <ul className="mt-2 divide-y divide-rule border-y border-rule text-[14px] tabular">
              {result.events.map((e) => (
                <li key={e.date} className="py-2">
                  <span className="text-ink-2">{formatDate(e.date)}</span>
                  <span className="ml-3 text-ink">
                    {e.label}:持ち株 {formatShares(e.shares_before)} → {formatShares(e.shares_after)}(×{e.ratio})
                  </span>
                  {e.fraction_shares > 0 && (
                    <span className="block text-[13px] text-ink-3">
                      1株未満の端数 {formatDecimal(e.fraction_shares)} 株を {formatYen(e.fraction_cash)} の現金に換えました
                      {e.closed_position ? "(0株になったので、この日に決済)" : ""}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {result.skipped_orders.length > 0 && (
          <div>
            <h3 className="text-[18px] font-bold text-ink">資金不足で見送った買い</h3>
            <ul className="mt-2 max-h-56 divide-y divide-rule overflow-auto border-y border-rule text-[13px] tabular">
              {result.skipped_orders.map((s) => (
                <li key={s.date} className="flex flex-wrap justify-between gap-x-4 py-1.5">
                  <span className="text-ink-2">{formatDate(s.date)}</span>
                  <span className="text-ink">
                    {result.params.lot_size}株で約 {formatYen(s.fill_price * result.params.lot_size)} 必要/現金 {formatYen(s.cash)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

// --- 注記 ---------------------------------------------------------------------------

function Notes({ result }: { result: BacktestResult }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="border-t border-rule pt-6">
      <h3 id={headingId} className="text-[16px] font-bold text-ink">
        この結果を読むときの注意
      </h3>
      <ul className="mt-2 space-y-1.5 text-[14px] leading-7 text-ink-2">
        {result.notes.map((note) => (
          <li key={note.kind} className="flex gap-2">
            <span aria-hidden="true" className="text-ink-3">
              ※
            </span>
            <span>{note.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
