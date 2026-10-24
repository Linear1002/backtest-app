// 画面の手順(銘柄 → 戦略 → 条件 → 確認 → 結果)の状態と、その移り変わり。
//
// React の部品から切り離した「純粋な関数」(reducer)にしてある。理由は2つ:
// - 古い応答(先に選んだ銘柄の詳細・前の実行の結果)を捨てるといった決まりを、1か所にまとめて書ける
// - node --test で、画面を開かずに確かめられる(lib/flow.test.ts)
//
// 決まりごと
// - 問い合わせには番号を付け、いちばん新しい番号の応答だけを受け取る(銘柄の詳細・バックテストの実行)
// - 結果の画面(手順5)に行けるのは、いまの条件がその結果を出した条件と同じときだけ。条件を変えたら、もう一度実行する
// - 実行中は手順を移動できない

import type {
  BacktestRequest,
  BacktestResult,
  Meta,
  ParamSpec,
  Strategy,
  SymbolDetail,
  SymbolSummary,
} from "./api.ts";
import { defaultForm, parseParams, validatePeriod, type FieldErrors, type FormState } from "./form.ts";

export type StepId = 1 | 2 | 3 | 4 | 5;

/** 実行して出た結果と、そのときの条件。 */
export type RunRecord = {
  id: number;
  request: BacktestRequest;
  result: BacktestResult;
};

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

  running: { id: number; request: BacktestRequest } | null;
  runError: string | null;
  last: RunRecord | null;
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
  | { type: "submitParams" }
  | { type: "selectEngine"; id: string }
  | { type: "runStarted"; id: number }
  | { type: "runSucceeded"; id: number; result: BacktestResult }
  | { type: "runFailed"; id: number; message: string; fieldErrors: FieldErrors }
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
  running: null,
  runError: null,
  last: null,
  animated: null,
  focus: { target: "heading", seq: 0 },
};

// --- 読み取り用の関数(selector) ------------------------------------------------

export function selectedStrategy(state: FlowState): Strategy | null {
  return state.catalog?.strategies.find((s) => s.id === state.strategyId) ?? null;
}

function specsOf(state: FlowState): ParamSpec[] | null {
  return selectedStrategy(state)?.params ?? null;
}

/** いまの入力の誤り(パラメータと期間)。誤りがなければ空。 */
export function formErrors(state: FlowState): FieldErrors {
  const specs = specsOf(state);
  if (!state.form || !state.detail || !specs) return {};
  return { ...parseParams(state.form, specs).errors, ...validatePeriod(state.form, state.detail.range) };
}

/** いまの条件で実行するときのリクエスト。条件がそろっていない・誤りがあるときは null。 */
export function currentRequest(state: FlowState): BacktestRequest | null {
  const strategy = selectedStrategy(state);
  if (!state.form || !state.detail || !strategy) return null;
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

/** その手順に移れるか(手順の表示・条件票から移るときに使う)。 */
export function canVisit(state: FlowState, step: StepId): boolean {
  if (state.running && step !== state.step) return false;
  switch (step) {
    case 1:
      return true;
    case 2:
      return state.detail !== null;
    case 3:
      return state.detail !== null && selectedStrategy(state) !== null && state.form !== null && state.visited >= 3;
    case 4:
      return canVisit(state, 3) && state.visited >= 4 && currentRequest(state) !== null;
    case 5:
      return state.last !== null && sameRequest(state.last.request, currentRequest(state));
  }
}

/** いまの条件は、前に出した結果の条件と違うか(確認の画面で「もう一度実行すると新しい結果になる」と伝える)。 */
export function resultIsOutdated(state: FlowState): boolean {
  return state.last !== null && !sameRequest(state.last.request, currentRequest(state));
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

export function flowReducer(state: FlowState, action: FlowAction): FlowState {
  switch (action.type) {
    case "catalogLoaded": {
      const next = { ...state, catalog: { meta: action.meta, strategies: action.strategies }, catalogError: null };
      // 選んでいた戦略がない(一覧が変わった)ときは、最初の使える戦略にする
      if (!selectedStrategy(next)) {
        next.strategyId = action.strategies.find((s) => s.available)?.id ?? null;
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
      // 同じ銘柄を選び直しても何もしない(読み込みに失敗していたときだけ、読み直す)
      if (action.symbol.id === state.symbol?.id && state.detailError === null) return state;
      return {
        ...state,
        symbol: action.symbol,
        detail: null,
        detailRequest: action.request,
        detailError: null,
        // 前の銘柄の入力エラー・実行エラーは、新しい銘柄には当てはまらない
        fieldErrors: {},
        runError: null,
      };
    }

    case "detailLoaded": {
      // 遅れて届いた古い応答(先に選んだ別の銘柄のもの)は捨てる
      if (action.request !== state.detailRequest || action.detail.symbol.id !== state.symbol?.id) return state;
      const range = action.detail.range;
      const specs = specsOf(state);
      // 日数・費用・初期資金はそのまま残し、期間だけを新しい銘柄のデータの範囲にする
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
        const fresh = defaultForm(specs, { first_date: state.form.start_date, last_date: state.form.end_date });
        next.form = fresh;
      }
      return next;
    }

    case "goTo": {
      if (!canVisit(state, action.step)) return state;
      return moveTo(state, action.step);
    }

    case "advance": {
      // 「この銘柄で進む」「この売買ルールで進む」(条件 → 確認は submitParams、確認 → 結果は実行)
      if (state.running) return state;
      if (state.step === 1) return state.detail ? moveTo(state, 2) : state;
      if (state.step === 2) {
        const specs = specsOf(state);
        if (!state.detail || !specs || !selectedStrategy(state)?.available) return state;
        return moveTo({ ...state, form: state.form ?? defaultForm(specs, state.detail.range) }, 3);
      }
      return state;
    }

    case "editForm":
      return { ...state, form: action.form, fieldErrors: {}, runError: null };

    case "submitParams": {
      if (!state.form || !state.detail || !specsOf(state)) return state;
      const errors = formErrors(state);
      if (Object.keys(errors).length > 0) {
        return { ...state, fieldErrors: errors, focus: focus(state, "error") };
      }
      return moveTo({ ...state, fieldErrors: {}, runError: null }, 4);
    }

    case "selectEngine":
      return { ...state, engine: action.id, runError: null };

    case "runStarted": {
      const request = currentRequest(state);
      if (state.running || !request) return state;
      return { ...state, running: { id: action.id, request }, runError: null };
    }

    case "runSucceeded": {
      // 取り消された・新しい実行に置きかわった実行の結果は捨てる
      if (!state.running || state.running.id !== action.id) return state;
      const last: RunRecord = { id: action.id, request: state.running.request, result: action.result };
      return moveTo({ ...state, running: null, last }, 5);
    }

    case "runFailed": {
      if (!state.running || state.running.id !== action.id) return state;
      const stopped = { ...state, running: null };
      if (Object.keys(action.fieldErrors).length > 0) {
        // 条件の入力に問題があれば、条件の画面に戻ってその場所に表示する
        const back = moveTo(stopped, 3);
        return { ...back, fieldErrors: action.fieldErrors, focus: focus(back, "error") };
      }
      return { ...stopped, runError: action.message };
    }

    case "resultAnimated":
      return { ...state, animated: action.id };
  }
}
