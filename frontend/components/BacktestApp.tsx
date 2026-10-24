"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { api, errorMessage, type ParamKey, type SweepStatus, type SymbolSummary } from "@/lib/api.ts";
import {
  canShowSweep,
  canVisit,
  currentRequest,
  currentSweepRequest,
  fieldErrorsFrom,
  flowReducer,
  holdoutOf,
  initialFlow,
  needsSymbolLoad,
  resultIsOutdated,
  runErrorMessage,
  runMode,
  selectedStrategy,
  sweepEngineInfo,
  unplacedErrorMessage,
  type FlowState,
  type StepId,
} from "@/lib/flow.ts";
import { describeYen, formatDate, formatRatePct, formatYen } from "@/lib/format.ts";
import { parseParams, toNumber } from "@/lib/form.ts";
import { pairCount, parseSweepGrid } from "@/lib/sweep.ts";

import { ResultView } from "./results/ResultView.tsx";
import { Seal } from "./Seal.tsx";
import { Stepper } from "./Stepper.tsx";
import { ConfirmStep } from "./steps/ConfirmStep.tsx";
import { ParamsStep } from "./steps/ParamsStep.tsx";
import { StrategyStep } from "./steps/StrategyStep.tsx";
import { SweepConfirmStep } from "./steps/SweepConfirmStep.tsx";
import { SymbolStep } from "./steps/SymbolStep.tsx";
import { SweepView } from "./sweep/SweepView.tsx";
import { SecondaryButton } from "./ui.tsx";

/** 総当たりの途中経過を問い合わせる間隔(ミリ秒) */
const POLL_MS = 400;
const count = new Intl.NumberFormat("ja-JP");

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function BacktestApp() {
  const [state, dispatch] = useReducer(flowReducer, initialFlow);
  // 問い合わせの番号(銘柄の詳細・バックテストの実行・総当たり)。いちばん新しい番号の応答だけを受け取る
  const seq = useRef(0);
  // いま途中経過を問い合わせている総当たりの番号(画面を閉じたら null にして、問い合わせをやめる)
  const polling = useRef<number | null>(null);
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

  useEffect(
    () => () => {
      polling.current = null;
    },
    [],
  );

  // 手順が変わったら、その手順の見出しへ。入力に誤りがあれば、最初の誤りの欄へフォーカスを移す
  useEffect(() => {
    if (state.focus.seq === 0) return;
    const frame = requestAnimationFrame(() => {
      const main = mainRef.current;
      if (!main) return;
      if (state.focus.target === "error") {
        // 欄のない誤り(総当たりの「組み合わせがない」など)は data-invalid-anchor の場所に出している
        const field = main.querySelector<HTMLElement>('[aria-invalid="true"], [data-invalid-anchor="true"]');
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
      const fieldErrors = fieldErrorsFrom(e, request);
      // 欄に出せる誤りがあるときは、欄に出せない誤りの文だけを画面の上に出す(なければ出さない)
      const message = Object.keys(fieldErrors).length > 0 ? unplacedErrorMessage(e, request) : runErrorMessage(e, request);
      dispatch({ type: "runFailed", id, message, fieldErrors });
    }
  }

  /** 総当たり:API にジョブを作らせ、終わるまで途中経過を問い合わせる(docs/sweep.md 10章)。 */
  async function runSweep() {
    const request = currentSweepRequest(state);
    if (!request || state.running) return;
    seq.current += 1;
    const id = seq.current;
    dispatch({ type: "sweepStarted", id, request });
    polling.current = id;
    try {
      let status: SweepStatus = await api.startSweep(request);
      while (status.status === "running") {
        dispatch({ type: "sweepProgress", id, jobId: status.id, done: status.done, total: status.total });
        await wait(POLL_MS);
        if (polling.current !== id) return; // 画面を閉じた
        status = await api.sweepStatus(status.id);
      }
      if (status.status === "done" && status.result) {
        dispatch({ type: "sweepSucceeded", id, result: status.result, elapsedMs: status.elapsed_ms });
      } else if (status.status === "cancelled") {
        dispatch({ type: "sweepCancelled", id });
      } else {
        dispatch({
          type: "sweepFailed",
          id,
          message: status.error?.detail ?? "総当たりを実行できませんでした",
          fieldErrors: {},
        });
      }
    } catch (e: unknown) {
      const fieldErrors = fieldErrorsFrom(e, request);
      const message =
        Object.keys(fieldErrors).length > 0
          ? unplacedErrorMessage(e, request)
          : runErrorMessage(e, request, "総当たりを実行できませんでした");
      dispatch({ type: "sweepFailed", id, message, fieldErrors });
    } finally {
      if (polling.current === id) polling.current = null;
    }
  }

  function cancelSweep() {
    const running = state.running;
    if (running?.kind !== "sweep" || !running.jobId) return;
    // 中止の結果は、問い合わせの続き(status が cancelled)で受け取る
    api.cancelSweep(running.jobId).catch(() => undefined);
  }

  // 結果の動きを再生し終えたら記録する(dispatch は変わらないので、この関数も描き直しで変わらない)
  const onAnimated = useCallback((id: number) => dispatch({ type: "resultAnimated", id }), []);

  const goTo = (step: StepId) => dispatch({ type: "goTo", step });
  const strategy = selectedStrategy(state);
  const meta = state.catalog?.meta ?? null;
  const mode = runMode(state);
  const request = currentRequest(state);
  const sweepRequest = currentSweepRequest(state);
  const running = state.running;
  const dataSourceLabel = meta
    ? meta.data_sources.map((s) => s.label).join("、")
    : state.catalogError
      ? "読み込めませんでした"
      : "読み込み中";
  const inputError = (
    <div className="rounded-md border border-shu px-4 py-3 text-[14px] text-shu" role="alert">
      条件に入力の誤りがあります。条件の画面に戻って直してください。
      <div className="mt-3">
        <SecondaryButton onClick={() => goTo(3)}>条件の画面に戻る</SecondaryButton>
      </div>
    </div>
  );

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
              notice={state.runError}
              sweepMaxPairs={sweepEngineInfo(state)?.max_pairs ?? null}
              onChange={(form) => dispatch({ type: "editForm", form })}
              onModeChange={(next) => dispatch({ type: "setMode", mode: next })}
              onNext={() => dispatch({ type: "submitParams" })}
            />
          )}
          {state.step === 4 &&
            state.detail &&
            strategy &&
            mode === "single" &&
            (request ? (
              <ConfirmStep
                detail={state.detail}
                strategy={strategy}
                request={request}
                engines={meta?.engines ?? []}
                onEngineChange={(id) => dispatch({ type: "selectEngine", id })}
                running={running !== null}
                error={state.runError}
                outdated={resultIsOutdated(state)}
                onRun={run}
              />
            ) : (
              inputError
            ))}
          {state.step === 4 &&
            state.detail &&
            strategy &&
            mode === "sweep" &&
            (sweepRequest || running?.kind === "sweep" ? (
              <SweepConfirmStep
                detail={state.detail}
                strategy={strategy}
                // 実行中は、送ったリクエストを出す(実行中は条件を変えられないので、いまの条件と同じもの)
                request={running?.kind === "sweep" ? running.request : sweepRequest!}
                engines={meta?.sweep_engines ?? []}
                onEngineChange={(id) => dispatch({ type: "selectSweepEngine", id })}
                running={running !== null}
                progress={running?.kind === "sweep" && running.jobId ? { done: running.done, total: running.total } : null}
                cancelled={state.sweepCancelled}
                error={state.runError}
                outdated={resultIsOutdated(state)}
                onRun={runSweep}
                onCancel={cancelSweep}
              />
            ) : (
              inputError
            ))}
          {state.step === 5 && mode === "single" && state.last && (
            <ResultView
              key={state.last.id}
              record={state.last}
              animate={state.animated !== state.last.id}
              onAnimated={onAnimated}
              onEditParams={() => goTo(3)}
              onRestart={() => goTo(1)}
              onBackToSweep={canShowSweep(state) ? () => dispatch({ type: "showSweep" }) : null}
            />
          )}
          {state.step === 5 && mode === "sweep" && state.lastSweep && (
            <SweepView
              key={state.lastSweep.id}
              record={state.lastSweep}
              onEditParams={() => goTo(3)}
              onRestart={() => goTo(1)}
              onInspect={(short, long) => dispatch({ type: "inspectCombo", short, long })}
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
  const sweep = form?.mode === "sweep";
  const errors = form && strategy ? parseParams(form, strategy.params).errors : {};
  // 項目ごとに、誤りがなければ数値、誤りがあれば null(「入力を確認してください」と出す)
  const value = (key: ParamKey): number | null =>
    form && errors[key] === undefined ? toNumber(form.params[key] ?? "") : null;
  const invalid = (...keys: ParamKey[]) => form !== null && keys.some((k) => errors[k] !== undefined);
  const both = <T,>(a: T | null, b: T | null): [T, T] | null => (a !== null && b !== null ? [a, b] : null);
  const windows = both(value("short_window"), value("long_window"));
  const costs = both(value("fee_rate_pct"), value("slippage_rate_pct"));
  const cash = value("initial_cash");
  const grid = form && sweep ? parseSweepGrid(form.sweep, null).grid : null;
  const holdout = form && sweep ? holdoutOf(form) : null;

  type Row = { step: StepId; label: string; value: string | null; invalid?: boolean };
  const rows: Row[] = [
    { step: 1, label: "銘柄", value: state.symbol ? `${state.symbol.name}\n${state.symbol.id}` : null },
    { step: 2, label: "売買ルール", value: strategy?.name ?? null },
    {
      step: 3,
      label: "期間",
      value: form ? `${formatDate(form.start_date)}〜\n${formatDate(form.end_date)}` : null,
    },
    sweep
      ? {
          step: 3,
          label: "移動平均(総当たり)",
          value: grid
            ? `短期${grid.short_min}〜${grid.short_max}日\n長期${grid.long_min}〜${grid.long_max}日\n${count.format(pairCount(grid))}通り`
            : null,
          invalid: form !== null && grid === null,
        }
      : {
          step: 3,
          label: "移動平均",
          value: windows ? `短期${windows[0]}日・長期${windows[1]}日` : null,
          invalid: invalid("short_window", "long_window"),
        },
    ...(sweep
      ? [{ step: 3 as StepId, label: "検証期間", value: holdout ? `${formatDate(holdout)}〜` : "使わない" }]
      : []),
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
