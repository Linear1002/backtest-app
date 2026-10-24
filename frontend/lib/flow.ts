// 画面の手順(銘柄 → 戦略 → 条件 → 確認 → 結果)の状態と、その移り変わり。
//
// React の部品から切り離した「純粋な関数」(reducer)にしてある。理由は2つ:
// - 古い応答(先に選んだ銘柄の詳細・前の実行の結果)を捨てるといった決まりを、1か所にまとめて書ける
// - node --test で、画面を開かずに確かめられる(lib/flow.test.ts)
//
// 決まりごと
// - 問い合わせには番号を付け、いちばん新しい番号の応答だけを受け取る(銘柄の詳細・バックテストの実行・総当たり)
// - 結果の画面(手順5)に行けるのは、いまの条件がその結果を出した条件と同じときだけ。条件を変えたら、もう一度実行する
// - 実行中は、手順の移動も条件の変更も受け付けない(送ったリクエストと記録する条件がずれないように)
// - 条件の画面で「1組で試す」と「総当たりで比べる」(docs/sweep.md)を切り替える。結果はそれぞれ別に覚えておく

import {
  ApiError,
  errorMessage,
  type BacktestRequest,
  type BacktestResult,
  type CostKey,
  type Meta,
  type ParamSpec,
  type Strategy,
  type SweepEngineInfo,
  type SweepRequest,
  type SweepResult,
  type SymbolDetail,
  type SymbolSummary,
} from "./api.ts";
import {
  defaultForm,
  parseParams,
  validatePeriod,
  type FieldErrors,
  type FieldKey,
  type FormState,
  type RunMode,
} from "./form.ts";
import { GRID_KEYS, holdoutStart, parseSweepGrid, validateHoldout } from "./sweep.ts";

export type StepId = 1 | 2 | 3 | 4 | 5;

/** 実行して出た結果と、そのときの条件。 */
export type RunRecord = {
  id: number;
  request: BacktestRequest;
  result: BacktestResult;
};

/** 総当たりの結果と、そのときの条件。 */
export type SweepRecord = {
  id: number;
  request: SweepRequest;
  result: SweepResult;
  /** 計算にかかった時間(ミリ秒) */
  elapsedMs: number | null;
};

/** 実行中のもの。総当たりは、API のジョブの id と途中経過(終わった組み合わせの数)も持つ */
export type Running =
  | { id: number; kind: "single"; request: BacktestRequest }
  | { id: number; kind: "sweep"; request: SweepRequest; jobId: string | null; done: number; total: number };

/** フォーカスを移す先。手順が変わったら見出し、入力に誤りがあれば最初の誤りの欄。 */
export type FocusRequest = { target: "heading" | "error"; seq: number };

export type FlowState = {
  step: StepId;
  /** いちばん先まで進んだ手順 */
  visited: StepId;
  catalog: { meta: Meta; strategies: Strategy[] } | null;
  catalogError: string | null;

  symbol: SymbolSummary | null;
  /** symbol の詳細。symbol と同じ銘柄の応答だけを入れる */
  detail: SymbolDetail | null;
  /** いちばん新しい「銘柄の詳細」の問い合わせの番号 */
  detailRequest: number;
  detailError: string | null;

  strategyId: string | null;
  form: FormState | null;
  fieldErrors: FieldErrors;
  engine: string;
  /** 総当たりに使うエンジン(GET /api/meta の sweep_engines) */
  sweepEngine: string;

  running: Running | null;
  runError: string | null;
  /** 総当たりを中止したところ(確認の画面に、エラーではない知らせとして出す) */
  sweepCancelled: boolean;
  last: RunRecord | null;
  lastSweep: SweepRecord | null;
  /** 結果が出たときの動きを再生し終えた結果の番号(戻ってきたときに、もう一度再生しないため) */
  animated: number | null;

  focus: FocusRequest;
};

export type FlowAction =
  | { type: "catalogLoaded"; meta: Meta; strategies: Strategy[] }
  | { type: "catalogFailed"; message: string }
  | { type: "catalogRetry" }
  | { type: "selectSymbol"; symbol: SymbolSummary; request: number }
  | { type: "detailLoaded"; request: number; detail: SymbolDetail }
  | { type: "detailFailed"; request: number; message: string }
  | { type: "selectStrategy"; id: string }
  | { type: "goTo"; step: StepId }
  | { type: "advance" }
  | { type: "editForm"; form: FormState }
  | { type: "setMode"; mode: RunMode }
  | { type: "submitParams" }
  | { type: "selectEngine"; id: string }
  | { type: "selectSweepEngine"; id: string }
  | { type: "runStarted"; id: number; request: BacktestRequest }
  | { type: "runSucceeded"; id: number; result: BacktestResult }
  /** message:確認の画面(欄の誤りがあるときは条件の画面)に出す文。欄に出せる誤りだけのときは null */
  | { type: "runFailed"; id: number; message: string | null; fieldErrors: FieldErrors }
  | { type: "sweepStarted"; id: number; request: SweepRequest }
  /** 総当たりのジョブの途中経過(jobId は、API が受け付けたときに届く) */
  | { type: "sweepProgress"; id: number; jobId: string; done: number; total: number }
  | { type: "sweepSucceeded"; id: number; result: SweepResult; elapsedMs: number | null }
  | { type: "sweepFailed"; id: number; message: string | null; fieldErrors: FieldErrors }
  | { type: "sweepCancelled"; id: number }
  /** 総当たりの結果から、1つの組み合わせを通常のバックテストで詳しく見る */
  | { type: "inspectCombo"; short: number; long: number }
  /** 1組の結果から、総当たりの結果に戻る */
  | { type: "showSweep" }
  | { type: "resultAnimated"; id: number };

export const initialFlow: FlowState = {
  step: 1,
  visited: 1,
  catalog: null,
  catalogError: null,
  symbol: null,
  detail: null,
  detailRequest: 0,
  detailError: null,
  strategyId: "ma_cross",
  form: null,
  fieldErrors: {},
  engine: "python",
  sweepEngine: "python",
  running: null,
  runError: null,
  sweepCancelled: false,
  last: null,
  lastSweep: null,
  animated: null,
  focus: { target: "heading", seq: 0 },
};

/** 総当たりでは、日数は格子で決めるので、条件の入力欄のうち費用と資金だけを使う */
export const COST_KEYS: readonly CostKey[] = ["fee_rate_pct", "slippage_rate_pct", "initial_cash"];

// --- 読み取り用の関数(selector) ------------------------------------------------

export function selectedStrategy(state: FlowState): Strategy | null {
  return state.catalog?.strategies.find((s) => s.id === state.strategyId) ?? null;
}

/** 選んでいる戦略が計算に使えるなら、その戦略(「今後追加予定」の戦略は null)。 */
function usableStrategy(state: FlowState): Strategy | null {
  const strategy = selectedStrategy(state);
  return strategy?.available ? strategy : null;
}

function specsOf(state: FlowState): ParamSpec[] | null {
  return selectedStrategy(state)?.params ?? null;
}

/** いまの実行のしかた(1組 / 総当たり)。入力欄がまだなければ 1組。 */
export function runMode(state: FlowState): RunMode {
  return state.form?.mode ?? "single";
}

/** 総当たりに使うエンジン。一覧がまだない・知らないエンジンなら null。 */
export function sweepEngineInfo(state: FlowState): SweepEngineInfo | null {
  return state.catalog?.meta.sweep_engines.find((e) => e.id === state.sweepEngine) ?? null;
}

/**
 * 条件の画面(手順3)に入れる状態か。銘柄の詳細があり、使える戦略を選んでいて、入力欄があること。
 * 「この売買ルールで進む」(advance)と、手順の表示から移るとき(canVisit)の両方がこれを使う。
 */
function paramsReady(state: FlowState): boolean {
  return state.detail !== null && usableStrategy(state) !== null && state.form !== null;
}

/** 銘柄を選んだときに、詳細を読みにいく必要があるか(同じ銘柄の選び直しは、失敗していたときだけ読み直す)。 */
export function needsSymbolLoad(state: FlowState, symbol: SymbolSummary): boolean {
  return symbol.id !== state.symbol?.id || state.detailError !== null;
}

/** 総当たりの検証期間の開始日(なしなら null)。 */
export function holdoutOf(form: FormState): string | null {
  return holdoutStart(form, form.sweep.holdout, form.sweep.holdout_date);
}

/** いまの入力の誤り(パラメータと期間。総当たりなら格子と検証期間も)。誤りがなければ空。 */
export function formErrors(state: FlowState): FieldErrors {
  const specs = specsOf(state);
  const form = state.form;
  if (!form || !state.detail || !specs) return {};
  const period = validatePeriod(form, state.detail.range);
  if (form.mode === "single") return { ...parseParams(form, specs).errors, ...period };
  const errors: FieldErrors = {
    ...parseSweepGrid(form.sweep, sweepEngineInfo(state)?.max_pairs ?? null).errors,
    ...parseParams(form, specs, COST_KEYS).errors,
    ...period,
  };
  // 期間が正しいときだけ、検証期間の開始日を確かめる(期間の誤りを先に直してもらう)
  if (Object.keys(period).length === 0) {
    const holdoutError = validateHoldout(form, holdoutOf(form));
    if (holdoutError) errors.holdout_start_date = holdoutError;
  }
  return errors;
}

/** いまの条件で1組のバックテストを実行するときのリクエスト。条件がそろっていない・誤りがあるときは null。 */
export function currentRequest(state: FlowState): BacktestRequest | null {
  const strategy = usableStrategy(state);
  if (!state.form || !state.detail || !strategy || state.form.mode !== "single") return null;
  const { params } = parseParams(state.form, strategy.params);
  if (!params || Object.keys(validatePeriod(state.form, state.detail.range)).length > 0) return null;
  return {
    symbol_id: state.detail.symbol.id,
    strategy_id: strategy.id,
    engine: state.engine,
    start_date: state.form.start_date,
    end_date: state.form.end_date,
    params,
  };
}

/** いまの条件で総当たりを実行するときのリクエスト。条件がそろっていない・誤りがあるときは null。 */
export function currentSweepRequest(state: FlowState): SweepRequest | null {
  const strategy = usableStrategy(state);
  const form = state.form;
  if (!form || !state.detail || !strategy || form.mode !== "sweep") return null;
  if (Object.keys(formErrors(state)).length > 0) return null;
  const { grid } = parseSweepGrid(form.sweep, sweepEngineInfo(state)?.max_pairs ?? null);
  const { params } = parseParams(form, strategy.params, COST_KEYS);
  if (!grid || !params) return null;
  return {
    symbol_id: state.detail.symbol.id,
    strategy_id: strategy.id,
    engine: state.sweepEngine,
    start_date: form.start_date,
    end_date: form.end_date,
    holdout_start_date: holdoutOf(form),
    grid,
    params: {
      fee_rate_pct: params.fee_rate_pct,
      slippage_rate_pct: params.slippage_rate_pct,
      initial_cash: params.initial_cash,
    },
  };
}

export function sameRequest(a: BacktestRequest | null, b: BacktestRequest | null): boolean {
  if (!a || !b) return false;
  if (
    a.symbol_id !== b.symbol_id ||
    a.strategy_id !== b.strategy_id ||
    a.engine !== b.engine ||
    a.start_date !== b.start_date ||
    a.end_date !== b.end_date
  ) {
    return false;
  }
  const keys = new Set([...Object.keys(a.params), ...Object.keys(b.params)]) as Set<keyof BacktestRequest["params"]>;
  for (const key of keys) if (a.params[key] !== b.params[key]) return false;
  return true;
}

export function sameSweepRequest(a: SweepRequest | null, b: SweepRequest | null): boolean {
  if (!a || !b) return false;
  return (
    a.symbol_id === b.symbol_id &&
    a.strategy_id === b.strategy_id &&
    a.engine === b.engine &&
    a.start_date === b.start_date &&
    a.end_date === b.end_date &&
    a.holdout_start_date === b.holdout_start_date &&
    GRID_KEYS.every((key) => a.grid[key] === b.grid[key]) &&
    COST_KEYS.every((key) => a.params[key] === b.params[key])
  );
}

/** いまの実行のしかたで、実行できる条件がそろっているか。 */
function readyToRun(state: FlowState): boolean {
  return runMode(state) === "sweep" ? currentSweepRequest(state) !== null : currentRequest(state) !== null;
}

/** いまの条件で出した結果があるか(1組なら last、総当たりなら lastSweep)。 */
function hasCurrentResult(state: FlowState): boolean {
  if (runMode(state) === "sweep") {
    return state.lastSweep !== null && sameSweepRequest(state.lastSweep.request, currentSweepRequest(state));
  }
  return state.last !== null && sameRequest(state.last.request, currentRequest(state));
}

/** その手順に移れるか(手順の表示・条件票から移るときに使う)。実行中は、いまの手順以外には移れない。 */
export function canVisit(state: FlowState, step: StepId): boolean {
  if (state.running && step !== state.step) return false;
  switch (step) {
    case 1:
      return true;
    case 2:
      return state.detail !== null;
    case 3:
      return paramsReady(state) && state.visited >= 3;
    case 4:
      return paramsReady(state) && state.visited >= 4 && readyToRun(state);
    case 5:
      return hasCurrentResult(state);
  }
}

/** いまの条件は、前に出した結果の条件と違うか(確認の画面で「もう一度実行すると新しい結果になる」と伝える)。 */
export function resultIsOutdated(state: FlowState): boolean {
  const previous = runMode(state) === "sweep" ? state.lastSweep : state.last;
  return previous !== null && !hasCurrentResult(state);
}

/** 1組の結果を見ているときに、同じ条件の総当たりの結果へ戻れるか。 */
export function canShowSweep(state: FlowState): boolean {
  if (state.running || !state.form || !state.lastSweep) return false;
  const asSweep = { ...state, form: { ...state.form, mode: "sweep" as const } };
  return sameSweepRequest(state.lastSweep.request, currentSweepRequest(asSweep));
}

// --- 実行のエラーの振り分け ---------------------------------------------------------

/** 入力欄のある項目(条件の項目と期間。総当たりなら格子と検証期間も)。API のエラーのうち、これに当たるものは欄に出す。 */
function formFields(request: BacktestRequest | SweepRequest): Set<string> {
  if ("grid" in request) {
    return new Set<string>([...GRID_KEYS, "grid", "holdout_start_date", ...COST_KEYS, "start_date", "end_date"]);
  }
  return new Set([...Object.keys(request.params), "start_date", "end_date"]);
}

/** API のエラーのうち、入力欄に出せるものだけを取り出す。ApiError 以外は空。 */
export function fieldErrorsFrom(error: unknown, request: BacktestRequest | SweepRequest): FieldErrors {
  if (!(error instanceof ApiError)) return {};
  const known = formFields(request);
  const picked: FieldErrors = {};
  for (const [field, message] of Object.entries(error.fieldErrors())) {
    if (known.has(field) && message) picked[field as FieldKey] = message;
  }
  return picked;
}

/**
 * 確認の画面に出す実行のエラーの文。入力欄に出せない項目(銘柄・戦略・エンジンなど)のエラーは、
 * 何を直せばよいかが分かるように、その説明を添える(例:「入力内容を確認してください(この戦略はまだ使えません)」)。
 */
export function runErrorMessage(
  error: unknown,
  request: BacktestRequest | SweepRequest,
  fallback = "バックテストを実行できませんでした",
): string {
  const base = errorMessage(error, fallback);
  if (!(error instanceof ApiError)) return base;
  const known = formFields(request);
  const extras = [
    ...new Set(
      error.errors
        .filter((e) => (e.field === null || !known.has(e.field)) && e.message && e.message !== base)
        .map((e) => e.message),
    ),
  ];
  return extras.length ? `${base}(${extras.join("・")})` : base;
}

/**
 * 欄に出せる誤りと一緒に返ってきた、欄に出せない誤り(戦略・エンジンなど)の文。なければ null。
 * 条件の画面に戻るときに、欄の誤りとは別に画面の上に出す。
 */
export function unplacedErrorMessage(error: unknown, request: BacktestRequest | SweepRequest): string | null {
  if (!(error instanceof ApiError)) return null;
  const known = formFields(request);
  const hasUnplaced = error.errors.some((e) => e.field !== null && !known.has(e.field) && e.message);
  return hasUnplaced ? runErrorMessage(error, request) : null;
}

// --- 状態の移り変わり(reducer) ---------------------------------------------------

function focus(state: FlowState, target: FocusRequest["target"]): FocusRequest {
  return { target, seq: state.focus.seq + 1 };
}

function moveTo(state: FlowState, step: StepId): FlowState {
  if (step === state.step) return state;
  return {
    ...state,
    step,
    visited: step > state.visited ? step : state.visited,
    focus: focus(state, "heading"),
  };
}

/**
 * 誤りがどの入力に左右されるか(自分の欄のほか)。2つ以上の欄にまたがる誤り
 * (「短期は長期より小さく」「開始日は終了日より前」「最小は最大以下」「組み合わせがない」など)のため。
 */
const DEPENDS_ON: Partial<Record<FieldKey, readonly string[]>> = {
  short_window: ["long_window"],
  long_window: ["short_window"],
  start_date: ["end_date"],
  end_date: ["start_date"],
  short_min: ["short_max"],
  long_min: ["long_max"],
  grid: GRID_KEYS,
  holdout_start_date: ["start_date", "end_date"],
};

/** 誤りを左右する入力の値(変わったかどうかを比べるためだけに使う)。 */
function fieldValue(form: FormState | null, key: string): string | undefined {
  if (!form) return undefined;
  if (key === "start_date" || key === "end_date") return form[key];
  if (key === "holdout_start_date") return `${form.sweep.holdout}|${form.sweep.holdout_date}`;
  // 「組み合わせがない・多すぎる」は、どの欄のものでもない。格子のどれかが変わったら、もう一度確かめて決める(DEPENDS_ON)
  if (key === "grid") return "";
  const gridKey = GRID_KEYS.find((k) => k === key);
  if (gridKey) return form.sweep[gridKey];
  return form.params[key as keyof FormState["params"]];
}

/**
 * 入力が変わったときに、もう当てはまらないエラーを消す(まだ当てはまるものは、直すまで残す)。
 * - その欄の入力が変わったら、その欄のエラーは消す
 * - 誤りを左右するほかの欄が変わったら、いまの入力でもう一度確かめて、同じ誤りが出なければ消す
 *   (例:長期を長くして「短期 < 長期」になったら、短期の欄の「短期は長期より小さく」を消す)
 */
function clearChangedErrors(
  errors: FieldErrors,
  before: FormState | null,
  after: FormState,
  recheck: FieldErrors,
): FieldErrors {
  const next: FieldErrors = { ...errors };
  for (const key of Object.keys(next) as FieldKey[]) {
    if (fieldValue(before, key) !== fieldValue(after, key)) {
      delete next[key];
      continue;
    }
    const others = DEPENDS_ON[key] ?? [];
    if (others.some((other) => fieldValue(before, other) !== fieldValue(after, other)) && recheck[key] !== next[key]) {
      delete next[key];
    }
  }
  return next;
}

/** 実行が失敗したとき(1組・総当たり共通)。 */
function failRun(state: FlowState, message: string | null, fieldErrors: FieldErrors): FlowState {
  const stopped = { ...state, running: null };
  if (Object.keys(fieldErrors).length > 0) {
    // 条件の入力に問題があれば、条件の画面に戻ってその場所に表示する。
    // 欄に出せない誤りも一緒に返ってきたら、その文(message)を条件の画面の上に出す
    const back = moveTo(stopped, 3);
    return { ...back, fieldErrors, runError: message, focus: focus(back, "error") };
  }
  return { ...stopped, runError: message ?? "実行できませんでした" };
}

/** 実行中は受け付けない action(条件や手順を変えるもの)。 */
const BLOCKED_WHILE_RUNNING = new Set<FlowAction["type"]>([
  "selectSymbol",
  "selectStrategy",
  "goTo",
  "advance",
  "editForm",
  "setMode",
  "submitParams",
  "selectEngine",
  "selectSweepEngine",
  "inspectCombo",
  "showSweep",
]);

export function flowReducer(state: FlowState, action: FlowAction): FlowState {
  if (state.running && BLOCKED_WHILE_RUNNING.has(action.type)) return state;
  switch (action.type) {
    case "catalogLoaded": {
      const next = { ...state, catalog: { meta: action.meta, strategies: action.strategies }, catalogError: null };
      // 実行中は、選んでいる戦略や入力欄を変えない(送ったリクエストと画面の条件をずらさないため)
      if (state.running) return next;
      // 選んでいた戦略が一覧にない・使えない(一覧が変わった)ときは、最初の使える戦略にする。
      // 戦略が変わったらパラメータの項目も変わるので、期間だけを残して入力欄を作り直す
      if (!usableStrategy(next)) {
        next.strategyId = action.strategies.find((s) => s.available)?.id ?? null;
        const nextSpecs = specsOf(next);
        if (next.strategyId !== state.strategyId && state.form && nextSpecs) {
          next.form = defaultForm(nextSpecs, { first_date: state.form.start_date, last_date: state.form.end_date });
          next.fieldErrors = {};
        }
      }
      // 総当たりのエンジンが一覧にない・使えないときは、最初の使えるものにする
      if (!action.meta.sweep_engines.some((e) => e.id === next.sweepEngine && e.available)) {
        next.sweepEngine = action.meta.sweep_engines.find((e) => e.available)?.id ?? next.sweepEngine;
      }
      // 詳細を先に受け取っていたら、ここで入力欄の初期値を作る
      const specs = specsOf(next);
      if (!next.form && next.detail && specs) next.form = defaultForm(specs, next.detail.range);
      return next;
    }

    case "catalogFailed":
      return { ...state, catalogError: action.message };

    case "catalogRetry":
      return { ...state, catalogError: null };

    case "selectSymbol": {
      if (!needsSymbolLoad(state, action.symbol)) return state;
      return {
        ...state,
        symbol: action.symbol,
        detail: null,
        detailRequest: action.request,
        detailError: null,
        // 前の銘柄の入力エラー・実行エラーは、新しい銘柄には当てはまらない
        fieldErrors: {},
        runError: null,
        sweepCancelled: false,
      };
    }

    case "detailLoaded": {
      // 遅れて届いた古い応答(先に選んだ別の銘柄のもの)は捨てる
      if (action.request !== state.detailRequest || action.detail.symbol.id !== state.symbol?.id) return state;
      const range = action.detail.range;
      const specs = specsOf(state);
      // 日数・費用・初期資金・総当たりの格子はそのまま残し、期間だけを新しい銘柄のデータの範囲にする
      const form = state.form
        ? { ...state.form, start_date: range.first_date, end_date: range.last_date }
        : specs
          ? defaultForm(specs, range)
          : null;
      return { ...state, detail: action.detail, detailError: null, form, fieldErrors: {} };
    }

    case "detailFailed":
      if (action.request !== state.detailRequest) return state;
      return { ...state, detailError: action.message };

    case "selectStrategy": {
      if (action.id === state.strategyId) return state;
      const next = { ...state, strategyId: action.id, fieldErrors: {} };
      const specs = specsOf(next);
      // 戦略が変わったらパラメータの項目も変わるので、期間だけを残して既定値にする
      if (state.form && specs) {
        next.form = defaultForm(specs, { first_date: state.form.start_date, last_date: state.form.end_date });
      }
      return next;
    }

    case "goTo": {
      if (!canVisit(state, action.step)) return state;
      return moveTo(state, action.step);
    }

    case "advance": {
      // 「この銘柄で進む」「この売買ルールで進む」(条件 → 確認は submitParams、確認 → 結果は実行)
      if (state.step === 1) return state.detail ? moveTo(state, 2) : state;
      if (state.step === 2) {
        const specs = specsOf(state);
        if (!state.detail || !specs) return state;
        const next = { ...state, form: state.form ?? defaultForm(specs, state.detail.range) };
        return paramsReady(next) ? moveTo(next, 3) : state;
      }
      return state;
    }

    case "editForm": {
      const next = { ...state, form: action.form };
      return {
        ...next,
        fieldErrors: clearChangedErrors(state.fieldErrors, state.form, action.form, formErrors(next)),
        runError: null,
        sweepCancelled: false,
      };
    }

    case "setMode": {
      if (!state.form || state.form.mode === action.mode) return state;
      // 実行のしかたを変えたら、もう一方の入力欄の誤りは関係なくなる
      return {
        ...state,
        form: { ...state.form, mode: action.mode },
        fieldErrors: {},
        runError: null,
        sweepCancelled: false,
      };
    }

    case "submitParams": {
      if (!paramsReady(state)) return state;
      const errors = formErrors(state);
      if (Object.keys(errors).length > 0) {
        return { ...state, fieldErrors: errors, focus: focus(state, "error") };
      }
      return moveTo({ ...state, fieldErrors: {}, runError: null, sweepCancelled: false }, 4);
    }

    case "selectEngine":
      return { ...state, engine: action.id, runError: null };

    case "selectSweepEngine":
      return { ...state, sweepEngine: action.id, runError: null };

    case "runStarted": {
      // 送るリクエストが、いまの条件と同じときだけ実行中にする(記録するのは送ったリクエストそのもの)
      if (state.running || !sameRequest(action.request, currentRequest(state))) return state;
      return { ...state, running: { id: action.id, kind: "single", request: action.request }, runError: null };
    }

    case "runSucceeded": {
      // いま実行中のもの(番号が同じ)以外の応答は捨てる
      if (state.running?.kind !== "single" || state.running.id !== action.id) return state;
      const last: RunRecord = { id: action.id, request: state.running.request, result: action.result };
      return moveTo({ ...state, running: null, last }, 5);
    }

    case "runFailed": {
      if (state.running?.kind !== "single" || state.running.id !== action.id) return state;
      return failRun(state, action.message, action.fieldErrors);
    }

    case "sweepStarted": {
      if (state.running || !sameSweepRequest(action.request, currentSweepRequest(state))) return state;
      return {
        ...state,
        running: { id: action.id, kind: "sweep", request: action.request, jobId: null, done: 0, total: 0 },
        runError: null,
        sweepCancelled: false,
      };
    }

    case "sweepProgress": {
      if (state.running?.kind !== "sweep" || state.running.id !== action.id) return state;
      return { ...state, running: { ...state.running, jobId: action.jobId, done: action.done, total: action.total } };
    }

    case "sweepSucceeded": {
      if (state.running?.kind !== "sweep" || state.running.id !== action.id) return state;
      const lastSweep: SweepRecord = {
        id: action.id,
        request: state.running.request,
        result: action.result,
        elapsedMs: action.elapsedMs,
      };
      return moveTo({ ...state, running: null, lastSweep }, 5);
    }

    case "sweepFailed": {
      if (state.running?.kind !== "sweep" || state.running.id !== action.id) return state;
      return failRun(state, action.message, action.fieldErrors);
    }

    case "sweepCancelled": {
      if (state.running?.kind !== "sweep" || state.running.id !== action.id) return state;
      return { ...state, running: null, sweepCancelled: true };
    }

    case "inspectCombo": {
      if (!state.form) return state;
      // 1組のバックテストにして、その組み合わせの日数を入れる(期間・費用・資金はそのまま)。確認の画面へ
      const form: FormState = {
        ...state.form,
        mode: "single",
        params: { ...state.form.params, short_window: String(action.short), long_window: String(action.long) },
      };
      const next = { ...state, form, fieldErrors: {}, runError: null };
      return currentRequest(next) ? moveTo(next, 4) : moveTo(next, 3);
    }

    case "showSweep": {
      if (!canShowSweep(state) || !state.form) return state;
      return moveTo({ ...state, form: { ...state.form, mode: "sweep" }, fieldErrors: {}, runError: null }, 5);
    }

    case "resultAnimated":
      return { ...state, animated: action.id };
  }
}
