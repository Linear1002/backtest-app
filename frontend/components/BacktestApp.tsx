"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { api, errorMessage, type ParamKey, type SymbolSummary } from "@/lib/api.ts";
import {
  canVisit,
  currentRequest,
  fieldErrorsFrom,
  flowReducer,
  initialFlow,
  needsSymbolLoad,
  resultIsOutdated,
  runErrorMessage,
  selectedStrategy,
  type FlowState,
  type StepId,
} from "@/lib/flow.ts";
import { describeYen, formatDate, formatRatePct, formatYen } from "@/lib/format.ts";
import { parseParams, toNumber } from "@/lib/form.ts";

import { ResultView } from "./results/ResultView.tsx";
import { Seal } from "./Seal.tsx";
import { Stepper } from "./Stepper.tsx";
import { ConfirmStep } from "./steps/ConfirmStep.tsx";
import { ParamsStep } from "./steps/ParamsStep.tsx";
import { StrategyStep } from "./steps/StrategyStep.tsx";
import { SymbolStep } from "./steps/SymbolStep.tsx";
import { SecondaryButton } from "./ui.tsx";

export function BacktestApp() {
  const [state, dispatch] = useReducer(flowReducer, initialFlow);
  // 問い合わせの番号(銘柄の詳細・バックテストの実行)。いちばん新しい番号の応答だけを受け取る
  const seq = useRef(0);
  const mainRef = useRef<HTMLElement>(null);

  const loadCatalog = useCallback(() => {
    Promise.all([api.meta(), api.strategies()])
      .then(([meta, strategies]) => dispatch({ type: "catalogLoaded", meta, strategies }))
      .catch((e: unknown) =>
        dispatch({ type: "catalogFailed", message: errorMessage(e, "初期データを読み込めませんでした") }),
      );
  }, []);

  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  // 手順が変わったら、その手順の見出しへ。入力に誤りがあれば、最初の誤りの欄へフォーカスを移す
  useEffect(() => {
    if (state.focus.seq === 0) return;
    const frame = requestAnimationFrame(() => {
      const main = mainRef.current;
      if (!main) return;
      if (state.focus.target === "error") {
        const field = main.querySelector<HTMLElement>('[aria-invalid="true"]');
        if (field) {
          field.focus({ preventScroll: true });
          field.scrollIntoView({ block: "center" });
          return;
        }
      }
      main.scrollIntoView({ block: "start" });
      const heading = main.querySelector<HTMLElement>("[data-step-heading]");
      (heading ?? main).focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [state.focus]);

  function selectSymbol(next: SymbolSummary) {
    if (state.running || !needsSymbolLoad(state, next)) return;
    seq.current += 1;
    const request = seq.current;
    dispatch({ type: "selectSymbol", symbol: next, request });
    api
      .symbol(next.id)
      .then((detail) => dispatch({ type: "detailLoaded", request, detail }))
      .catch((e: unknown) =>
        dispatch({ type: "detailFailed", request, message: errorMessage(e, "銘柄の情報を読み込めませんでした") }),
      );
  }

  async function run() {
    const request = currentRequest(state);
    if (!request || state.running) return;
    seq.current += 1;
    const id = seq.current;
    // 送るリクエストそのものを記録する(結果の画面に移れるかは、この条件で判定する)
    dispatch({ type: "runStarted", id, request });
    try {
      const result = await api.runBacktest(request);
      dispatch({ type: "runSucceeded", id, result });
    } catch (e: unknown) {
      dispatch({ type: "runFailed", id, message: runErrorMessage(e, request), fieldErrors: fieldErrorsFrom(e, request) });
    }
  }

  // 結果の動きを再生し終えたら記録する(dispatch は変わらないので、この関数も描き直しで変わらない)
  const onAnimated = useCallback((id: number) => dispatch({ type: "resultAnimated", id }), []);

  const goTo = (step: StepId) => dispatch({ type: "goTo", step });
  const strategy = selectedStrategy(state);
  const meta = state.catalog?.meta ?? null;
  const request = currentRequest(state);
  const dataSourceLabel = meta
    ? meta.data_sources.map((s) => s.label).join("、")
    : state.catalogError
      ? "読み込めませんでした"
      : "読み込み中";

  return (
    <div className="mx-auto w-full max-w-[1180px] px-4 pb-24 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule py-4">
        <div className="flex items-center gap-3">
          <Seal kind="check" size={34} decorative />
          <div>
            <h1 className="text-[19px] font-bold leading-tight text-ink">日本語バックテスト</h1>
            <p className="text-[12px] leading-5 text-ink-3">売買ルールを、過去の株価で確かめる</p>
          </div>
        </div>
        <p className="text-[12px] text-ink-3">
          使えるデータ:<span className="text-ink-2">{dataSourceLabel}</span>
        </p>
      </header>

      <div className="sticky top-0 z-10 -mx-4 border-b border-rule bg-paper/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        <Stepper
          current={state.step}
          isAvailable={(s) => canVisit(state, s)}
          locked={state.running !== null}
          onSelect={goTo}
        />
      </div>

      {state.catalogError && (
        <div
          role="alert"
          className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-md border border-shu px-4 py-3 text-[14px] text-shu"
        >
          <span>{state.catalogError}</span>
          <SecondaryButton
            onClick={() => {
              dispatch({ type: "catalogRetry" });
              loadCatalog();
            }}
          >
            もう一度読み込む
          </SecondaryButton>
        </div>
      )}

      <div className={`mt-8 grid gap-10 ${state.step < 5 ? "lg:grid-cols-[17rem_1fr]" : ""}`}>
        {state.step < 5 && <ConditionSlip state={state} onJump={goTo} />}
        <main ref={mainRef} tabIndex={-1} className="min-w-0 scroll-mt-20 outline-none">
          {state.step === 1 && (
            <SymbolStep
              meta={meta}
              selected={state.symbol}
              detail={state.detail}
              detailError={state.detailError}
              onSelect={selectSymbol}
              onNext={() => dispatch({ type: "advance" })}
            />
          )}
          {state.step === 2 && (
            <StrategyStep
              strategies={state.catalog?.strategies ?? null}
              selectedId={state.strategyId}
              onSelect={(id) => dispatch({ type: "selectStrategy", id })}
              onNext={() => dispatch({ type: "advance" })}
            />
          )}
          {state.step === 3 && state.detail && strategy && state.form && (
            <ParamsStep
              detail={state.detail}
              specs={strategy.params}
              form={state.form}
              errors={state.fieldErrors}
              onChange={(form) => dispatch({ type: "editForm", form })}
              onNext={() => dispatch({ type: "submitParams" })}
            />
          )}
          {state.step === 4 &&
            state.detail &&
            strategy &&
            (request ? (
              <ConfirmStep
                detail={state.detail}
                strategy={strategy}
                request={request}
                engines={meta?.engines ?? []}
                onEngineChange={(id) => dispatch({ type: "selectEngine", id })}
                running={state.running !== null}
                error={state.runError}
                outdated={resultIsOutdated(state)}
                onRun={run}
              />
            ) : (
              <div className="rounded-md border border-shu px-4 py-3 text-[14px] text-shu" role="alert">
                条件に入力の誤りがあります。条件の画面に戻って直してください。
                <div className="mt-3">
                  <SecondaryButton onClick={() => goTo(3)}>条件の画面に戻る</SecondaryButton>
                </div>
              </div>
            ))}
          {state.step === 5 && state.last && (
            <ResultView
              key={state.last.id}
              record={state.last}
              animate={state.animated !== state.last.id}
              onAnimated={onAnimated}
              onEditParams={() => goTo(3)}
              onRestart={() => goTo(1)}
            />
          )}
        </main>
      </div>
    </div>
  );
}

/** 左側の「条件票」。ここまでに決めた内容をいつでも見られるようにする。 */
function ConditionSlip({ state, onJump }: { state: FlowState; onJump: (step: StepId) => void }) {
  const strategy = selectedStrategy(state);
  const form = state.form;
  const errors = form && strategy ? parseParams(form, strategy.params).errors : {};
  // 項目ごとに、誤りがなければ数値、誤りがあれば null(「入力を確認してください」と出す)
  const value = (key: ParamKey): number | null =>
    form && errors[key] === undefined ? toNumber(form.params[key] ?? "") : null;
  const invalid = (...keys: ParamKey[]) => form !== null && keys.some((k) => errors[k] !== undefined);
  const both = <T,>(a: T | null, b: T | null): [T, T] | null => (a !== null && b !== null ? [a, b] : null);
  const windows = both(value("short_window"), value("long_window"));
  const costs = both(value("fee_rate_pct"), value("slippage_rate_pct"));
  const cash = value("initial_cash");

  type Row = { step: StepId; label: string; value: string | null; invalid?: boolean };
  const rows: Row[] = [
    { step: 1, label: "銘柄", value: state.symbol ? `${state.symbol.name}\n${state.symbol.id}` : null },
    { step: 2, label: "売買ルール", value: strategy?.name ?? null },
    {
      step: 3,
      label: "期間",
      value: form ? `${formatDate(form.start_date)}〜\n${formatDate(form.end_date)}` : null,
    },
    {
      step: 3,
      label: "移動平均",
      value: windows ? `短期${windows[0]}日・長期${windows[1]}日` : null,
      invalid: invalid("short_window", "long_window"),
    },
    {
      step: 3,
      label: "費用",
      value: costs ? `手数料${formatRatePct(costs[0])}\nスリッページ${formatRatePct(costs[1])}` : null,
      invalid: invalid("fee_rate_pct", "slippage_rate_pct"),
    },
    {
      step: 3,
      label: "初期資金",
      value: cash !== null ? `${formatYen(cash)}\n${describeYen(cash)}` : null,
      invalid: invalid("initial_cash"),
    },
  ];
  return (
    <aside aria-label="ここまでの条件" className="hidden lg:block">
      <div className="sticky top-24 rounded-md border border-rule bg-surface">
        <p className="border-b border-rule px-4 py-2.5 text-[13px] font-bold text-ink">条件票</p>
        <dl className="divide-y divide-rule">
          {rows.map((row) => {
            const available = canVisit(state, row.step) && row.step !== state.step;
            const placeholder = row.invalid ? "入力を確認してください" : "まだ決めていません";
            return (
              <div key={row.label} className="px-4 py-2.5">
                <dt className="text-[12px] text-ink-3">{row.label}</dt>
                <dd className="whitespace-pre-line text-[14px] leading-6 text-ink">
                  {row.value ??
                    (available ? (
                      <button type="button" onClick={() => onJump(row.step)} className="text-ink-3 underline-offset-4 hover:text-ink hover:underline">
                        {placeholder}
                      </button>
                    ) : (
                      <span className={row.invalid ? "text-shu" : "text-ink-3"}>{placeholder}</span>
                    ))}
                </dd>
              </div>
            );
          })}
        </dl>
      </div>
    </aside>
  );
}
