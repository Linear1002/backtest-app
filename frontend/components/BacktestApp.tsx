"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  api,
  ApiError,
  type BacktestResult,
  type Meta,
  type Params,
  type Strategy,
  type SymbolDetail,
  type SymbolSummary,
} from "@/lib/api.ts";
import { describeYen, formatDate } from "@/lib/format.ts";
import { defaultForm, parseParams, validatePeriod, type FieldErrors, type FormState } from "@/lib/form.ts";

import { ResultView } from "./results/ResultView.tsx";
import { Seal } from "./Seal.tsx";
import { Stepper, type StepId } from "./Stepper.tsx";
import { ConfirmStep } from "./steps/ConfirmStep.tsx";
import { ParamsStep } from "./steps/ParamsStep.tsx";
import { StrategyStep } from "./steps/StrategyStep.tsx";
import { SymbolStep } from "./steps/SymbolStep.tsx";

export function BacktestApp() {
  const [step, setStep] = useState<StepId>(1);
  const [reached, setReached] = useState<StepId>(1);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [symbol, setSymbol] = useState<SymbolSummary | null>(null);
  const [detail, setDetail] = useState<SymbolDetail | null>(null);
  const [strategyId, setStrategyId] = useState<string | null>("ma_cross");
  const [form, setForm] = useState<FormState | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [engine, setEngine] = useState("python");

  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const mainRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    Promise.all([api.meta(), api.strategies()])
      .then(([m, s]) => {
        setMeta(m);
        setStrategies(s);
      })
      .catch((e: unknown) => setLoadError(e instanceof ApiError ? e.message : "初期データを読み込めませんでした"));
  }, []);

  const strategy = strategies.find((s) => s.id === strategyId) ?? null;

  const goTo = useCallback((next: StepId) => {
    setStep(next);
    setReached((r) => (next > r ? next : r));
    // 手順が変わったら、画面の上から読めるようにする
    requestAnimationFrame(() => {
      mainRef.current?.scrollIntoView({ block: "start" });
      mainRef.current?.focus({ preventScroll: true });
    });
  }, []);

  function selectSymbol(next: SymbolSummary) {
    setSymbol(next);
    setResult(null);
    setDetail((d) => (d?.symbol.id === next.id ? d : null));
    setReached(1);
    api
      .symbol(next.id)
      .then((d) => {
        setDetail(d);
        if (strategy) setForm(defaultForm(strategy.params, d.range));
      })
      .catch((e: unknown) => setLoadError(e instanceof ApiError ? e.message : "銘柄の情報を読み込めませんでした"));
  }

  function toParamsStep() {
    if (!detail || !strategy) return;
    setForm((f) => f ?? defaultForm(strategy.params, detail.range));
    goTo(3);
  }

  function toConfirmStep() {
    if (!form || !detail) return;
    const { errors } = parseParams(form);
    const all = { ...errors, ...validatePeriod(form, detail.range) };
    setFieldErrors(all);
    if (Object.keys(all).length === 0) {
      setRunError(null);
      goTo(4);
    }
  }

  async function run() {
    if (!form || !symbol || !strategy) return;
    const { params } = parseParams(form);
    if (!params) return;
    setRunning(true);
    setRunError(null);
    try {
      const r = await api.runBacktest({
        symbol_id: symbol.id,
        strategy_id: strategy.id,
        engine,
        start_date: form.start_date,
        end_date: form.end_date,
        params,
      });
      setResult(r);
      goTo(5);
    } catch (e: unknown) {
      if (e instanceof ApiError && e.errors.some((x) => x.field && x.field in form.params)) {
        // 条件の入力に問題があれば、条件の画面に戻ってその場所に表示する
        setFieldErrors(e.fieldErrors());
        goTo(3);
      } else if (e instanceof ApiError && e.errors.some((x) => x.field === "start_date" || x.field === "end_date")) {
        setFieldErrors(e.fieldErrors());
        goTo(3);
      } else {
        setRunError(e instanceof ApiError ? e.message : "バックテストを実行できませんでした");
      }
    } finally {
      setRunning(false);
    }
  }

  const parsed = form ? parseParams(form).params : null;
  const dataSourceLabel = meta
    ? meta.data_sources.map((s) => s.label).join("、")
    : "読み込み中";

  return (
    <div className="mx-auto w-full max-w-[1180px] px-4 pb-24 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule py-4">
        <div className="flex items-center gap-3">
          <Seal kind="check" size={34} title="検" />
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
        <Stepper current={step} reached={reached} onSelect={(s) => goTo(s)} />
      </div>

      {loadError && (
        <p role="alert" className="mt-6 rounded-md border border-shu px-4 py-3 text-[14px] text-shu">
          {loadError}
        </p>
      )}

      <div className={`mt-8 grid gap-10 ${step < 5 ? "lg:grid-cols-[17rem_1fr]" : ""}`}>
        {step < 5 && (
          <ConditionSlip
            symbol={symbol}
            strategy={strategy}
            form={form}
            params={parsed}
            onJump={(s) => (s <= reached ? goTo(s) : undefined)}
          />
        )}
        <div ref={mainRef} tabIndex={-1} className="min-w-0 scroll-mt-20 outline-none">
          {step === 1 && (
            <SymbolStep meta={meta} selected={symbol} detail={detail} onSelect={selectSymbol} onNext={() => goTo(2)} />
          )}
          {step === 2 && (
            <StrategyStep strategies={strategies} selectedId={strategyId} onSelect={setStrategyId} onNext={toParamsStep} />
          )}
          {step === 3 && detail && strategy && form && (
            <ParamsStep
              detail={detail}
              specs={strategy.params}
              form={form}
              errors={fieldErrors}
              onChange={(next) => {
                setForm(next);
                setFieldErrors({});
              }}
              onNext={toConfirmStep}
            />
          )}
          {step === 4 && detail && strategy && form && parsed && (
            <ConfirmStep
              detail={detail}
              strategy={strategy}
              period={{ start_date: form.start_date, end_date: form.end_date }}
              params={parsed}
              engines={meta?.engines ?? []}
              engine={engine}
              onEngineChange={setEngine}
              running={running}
              error={runError}
              onRun={run}
            />
          )}
          {step === 5 && result && (
            <ResultView
              key={`${result.symbol.id}-${result.period.start_date}-${result.params.short_window}-${result.params.long_window}-${result.elapsed_ms}`}
              result={result}
              detail={detail}
              animate
              onEditParams={() => goTo(3)}
              onRestart={() => goTo(1)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

/** 左側の「条件票」。ここまでに決めた内容をいつでも見られるようにする。 */
function ConditionSlip({
  symbol,
  strategy,
  form,
  params,
  onJump,
}: {
  symbol: SymbolSummary | null;
  strategy: Strategy | null;
  form: FormState | null;
  params: Params | null;
  onJump: (step: StepId) => void;
}) {
  const rows: { step: StepId; label: string; value: string | null }[] = [
    { step: 1, label: "銘柄", value: symbol ? `${symbol.name}\n${symbol.id}` : null },
    { step: 2, label: "売買ルール", value: strategy?.name ?? null },
    {
      step: 3,
      label: "期間",
      value: form ? `${formatDate(form.start_date)}〜\n${formatDate(form.end_date)}` : null,
    },
    {
      step: 3,
      label: "移動平均",
      value: params ? `短期${params.short_window}日・長期${params.long_window}日` : null,
    },
    {
      step: 3,
      label: "費用",
      value: params ? `手数料${params.fee_rate_pct}%・スリッページ${params.slippage_rate_pct}%` : null,
    },
    { step: 3, label: "初期資金", value: params ? describeYen(params.initial_cash) : null },
  ];
  return (
    <aside aria-label="ここまでの条件" className="hidden lg:block">
      <div className="sticky top-24 rounded-md border border-rule bg-surface">
        <p className="border-b border-rule px-4 py-2.5 text-[13px] font-bold text-ink">条件票</p>
        <dl className="divide-y divide-rule">
          {rows.map((row) => (
            <div key={row.label} className="px-4 py-2.5">
              <dt className="text-[12px] text-ink-3">{row.label}</dt>
              <dd className="whitespace-pre-line text-[14px] leading-6 text-ink">
                {row.value ?? (
                  <button type="button" onClick={() => onJump(row.step)} className="text-ink-3 hover:text-ink">
                    まだ決めていません
                  </button>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </aside>
  );
}
