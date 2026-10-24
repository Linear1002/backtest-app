import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError } from "./api.ts";
import {
  canVisit,
  currentRequest,
  fieldErrorsFrom,
  flowReducer,
  initialFlow,
  needsSymbolLoad,
  resultIsOutdated,
  runErrorMessage,
  type FlowAction,
  type FlowState,
} from "./flow.ts";
import { detail, META, result, STRATEGIES, symbol } from "./testing.ts";

function run(actions: FlowAction[], start: FlowState = initialFlow): FlowState {
  return actions.reduce(flowReducer, start);
}

const loaded: FlowAction = { type: "catalogLoaded", meta: META, strategies: STRATEGIES };

/** 銘柄 A を選んで条件の画面(手順3)まで進んだ状態。 */
function atParams(): FlowState {
  return run([
    loaded,
    { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 1 },
    { type: "detailLoaded", request: 1, detail: detail("DEMO:1001") },
    { type: "advance" },
    { type: "advance" },
  ]);
}

/** 確認の画面(手順4)まで進んだ状態。 */
function atConfirm(): FlowState {
  return flowReducer(atParams(), { type: "submitParams" });
}

/** いまの条件で実行を始めた状態。 */
function started(state: FlowState, id: number): FlowState {
  const request = currentRequest(state);
  assert.ok(request, "実行できる条件のはず");
  return flowReducer(state, { type: "runStarted", id, request });
}

/** 手順5(結果)まで進んだ状態。 */
function atResult(): FlowState {
  return flowReducer(started(atConfirm(), 2), { type: "runSucceeded", id: 2, result: result("DEMO:1001") });
}

function edit(state: FlowState, params: Partial<NonNullable<FlowState["form"]>["params"]>, period = {}): FlowState {
  const form = state.form!;
  return flowReducer(state, { type: "editForm", form: { ...form, ...period, params: { ...form.params, ...params } } });
}

test("はじめから結果まで進める", () => {
  const s = atParams();
  assert.equal(s.step, 3);
  assert.equal(s.form?.start_date, "2024-01-04");
  assert.equal(s.form?.params.short_window, "5");
  const done = atResult();
  assert.equal(done.step, 5);
  assert.equal(done.last?.id, 2);
  assert.equal(done.last?.request.symbol_id, "DEMO:1001");
  assert.equal(done.running, null);
  assert.ok(canVisit(done, 5));
});

test("遅れて届いた別の銘柄の詳細は捨てる(A を押してすぐ B を押した)", () => {
  const s = run([
    loaded,
    { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 1 },
    { type: "selectSymbol", symbol: symbol("DEMO:1002"), request: 2 },
    { type: "detailLoaded", request: 2, detail: detail("DEMO:1002", "2024-06-03") },
    // A の応答が後から届く
    { type: "detailLoaded", request: 1, detail: detail("DEMO:1001", "2023-01-04") },
  ]);
  assert.equal(s.symbol?.id, "DEMO:1002");
  assert.equal(s.detail?.symbol.id, "DEMO:1002");
  assert.equal(s.form?.start_date, "2024-06-03");
  // A の失敗が後から届いても、B のエラーにはしない
  const t = flowReducer(s, { type: "detailFailed", request: 1, message: "見つかりません" });
  assert.equal(t.detailError, null);
});

test("番号が合っていても、いま選んでいない銘柄の詳細は受け取らない", () => {
  const s = run([
    loaded,
    { type: "selectSymbol", symbol: symbol("DEMO:1002"), request: 5 },
    { type: "detailLoaded", request: 5, detail: detail("DEMO:9999") },
  ]);
  assert.equal(s.detail, null);
});

test("詳細の読み込みに失敗したら、選んだ銘柄のところにエラーを出し、選び直すと読み直す", () => {
  const failed = run([
    loaded,
    { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 1 },
    { type: "detailFailed", request: 1, message: "API サーバーに接続できません" },
  ]);
  assert.equal(failed.detailError, "API サーバーに接続できません");
  assert.equal(canVisit(failed, 2), false);
  assert.equal(needsSymbolLoad(failed, symbol("DEMO:1001")), true);
  const retry = flowReducer(failed, { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 2 });
  assert.equal(retry.detailRequest, 2);
  assert.equal(retry.detailError, null);
});

test("同じ銘柄を選び直しても、結果も条件も消えない", () => {
  const done = atResult();
  assert.equal(needsSymbolLoad(done, symbol("DEMO:1001")), false);
  const again = flowReducer(done, { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 9 });
  assert.equal(again, done);
});

test("銘柄を変えると入力エラーが消え、期間だけが新しい銘柄の範囲になる", () => {
  const s = flowReducer(edit(atParams(), { short_window: "7", initial_cash: "abc" }), { type: "submitParams" });
  assert.equal(s.fieldErrors.initial_cash, "数値で入力してください");
  const changed = run(
    [
      { type: "selectSymbol", symbol: symbol("DEMO:1002"), request: 3 },
      { type: "detailLoaded", request: 3, detail: detail("DEMO:1002", "2024-06-03", "2025-11-28") },
    ],
    s,
  );
  assert.deepEqual(changed.fieldErrors, {});
  assert.equal(changed.form?.start_date, "2024-06-03");
  assert.equal(changed.form?.end_date, "2025-11-28");
  assert.equal(changed.form?.params.short_window, "7"); // 日数などはそのまま
});

test("実行に失敗したあとで別の銘柄を選ぶと、実行のエラーが消える", () => {
  const failed = flowReducer(started(atConfirm(), 7), {
    type: "runFailed",
    id: 7,
    message: "API サーバーに接続できません",
    fieldErrors: {},
  });
  assert.equal(failed.runError, "API サーバーに接続できません");
  const moved = run(
    [
      { type: "goTo", step: 1 },
      { type: "selectSymbol", symbol: symbol("DEMO:1002"), request: 8 },
    ],
    failed,
  );
  assert.equal(moved.runError, null);
});

test("入力に誤りがあると確認へ進まず、誤りの欄へのフォーカスを頼む", () => {
  const s = atParams();
  const bad = flowReducer(edit(s, { fee_rate_pct: "-1" }), { type: "submitParams" });
  assert.equal(bad.step, 3);
  assert.equal(bad.fieldErrors.fee_rate_pct, "手数料率とスリッページ率は0以上で入力してください");
  assert.equal(bad.focus.target, "error");
  assert.ok(bad.focus.seq > s.focus.seq);
});

test("入力を直すと、直した欄の誤りだけが消える(ほかの欄の誤りは残る)", () => {
  const bad = flowReducer(edit(atParams(), { fee_rate_pct: "-1", initial_cash: "0" }), { type: "submitParams" });
  assert.deepEqual(Object.keys(bad.fieldErrors).sort(), ["fee_rate_pct", "initial_cash"]);
  const fixed = edit(bad, { fee_rate_pct: "0.1" });
  assert.deepEqual(Object.keys(fixed.fieldErrors), ["initial_cash"]);
  const period = flowReducer(edit(atParams(), {}, { start_date: "2020-01-01" }), { type: "submitParams" });
  assert.ok(period.fieldErrors.start_date);
  assert.equal(edit(period, {}, { start_date: "2024-01-04" }).fieldErrors.start_date, undefined);
});

test("一度確認まで進んだあとに条件を誤りのある値にすると、確認の手順には移れない", () => {
  const confirmed = atConfirm();
  assert.equal(confirmed.step, 4);
  const back = flowReducer(confirmed, { type: "goTo", step: 3 });
  const bad = edit(back, { initial_cash: "" });
  assert.equal(canVisit(bad, 4), false);
  assert.equal(flowReducer(bad, { type: "goTo", step: 4 }).step, 3);
  // 期間だけがおかしい場合も同じ
  const badPeriod = edit(back, {}, { start_date: "2020-01-01" });
  assert.equal(canVisit(badPeriod, 4), false);
});

test("条件を変えたら、前の結果の画面には戻れない(元に戻せば、また見られる)", () => {
  const back = flowReducer(atResult(), { type: "goTo", step: 3 });
  const edited = edit(back, { fee_rate_pct: "0.2" });
  assert.equal(canVisit(edited, 5), false);
  assert.equal(resultIsOutdated(edited), true);
  assert.equal(flowReducer(edited, { type: "goTo", step: 5 }).step, 3);
  const reverted = edit(edited, { fee_rate_pct: "0.1" });
  assert.equal(canVisit(reverted, 5), true);
  assert.equal(resultIsOutdated(reverted), false);
  // 数値として同じなら同じ条件(0.10 と 0.1)
  assert.equal(canVisit(edit(edited, { fee_rate_pct: "0.10" }), 5), true);
});

test("計算エンジンを変えても、前の結果とは別の条件になる", () => {
  const other = flowReducer(atResult(), { type: "selectEngine", id: "cpp" });
  assert.equal(canVisit(other, 5), false);
});

test("実行中は手順も条件も変えられず、二重に実行しない", () => {
  const running = started(atConfirm(), 7);
  assert.equal(running.running?.id, 7);
  for (const step of [1, 2, 3, 5] as const) {
    assert.equal(canVisit(running, step), false);
    assert.equal(flowReducer(running, { type: "goTo", step }).step, 4);
  }
  // 実行中の手順そのものには「移れる」(いまいる手順)
  assert.equal(canVisit(running, 4), true);
  const blocked: FlowAction[] = [
    { type: "selectEngine", id: "cpp" },
    { type: "editForm", form: { ...running.form!, start_date: "2024-06-03" } },
    { type: "selectSymbol", symbol: symbol("DEMO:1002"), request: 9 },
    { type: "selectStrategy", id: "rsi_reversal" },
    { type: "submitParams" },
    { type: "advance" },
    { type: "runStarted", id: 8, request: running.running!.request },
  ];
  for (const action of blocked) assert.equal(flowReducer(running, action), running, action.type);
});

test("いまの条件と違うリクエストでは、実行を始めない(送るものと記録するものをそろえる)", () => {
  const confirmed = atConfirm();
  const request = currentRequest(confirmed)!;
  const other = { ...request, params: { ...request.params, fee_rate_pct: 0.2 } };
  assert.equal(flowReducer(confirmed, { type: "runStarted", id: 3, request: other }), confirmed);
  // 条件がそろっていないとき(入力に誤りがある)も始めない
  const bad = edit(flowReducer(confirmed, { type: "goTo", step: 3 }), { initial_cash: "abc" });
  assert.equal(currentRequest(bad), null);
  assert.equal(flowReducer(bad, { type: "runStarted", id: 3, request }), bad);
});

test("いま実行中のもの(番号)と違う応答は捨てる", () => {
  const confirmed = atConfirm();
  const running = started(confirmed, 7);
  assert.equal(flowReducer(running, { type: "runSucceeded", id: 6, result: result("DEMO:1001") }), running);
  assert.equal(flowReducer(running, { type: "runFailed", id: 6, message: "x", fieldErrors: {} }), running);
  // 実行していないときに届いた応答も捨てる
  assert.equal(flowReducer(confirmed, { type: "runSucceeded", id: 7, result: result("DEMO:1001") }), confirmed);
});

test("実行の失敗:入力の誤りなら条件の画面に戻り、それ以外は確認の画面にエラーを出す", () => {
  const running = started(atConfirm(), 7);
  const fieldFail = flowReducer(running, {
    type: "runFailed",
    id: 7,
    message: "入力内容を確認してください",
    fieldErrors: { start_date: "期間が短すぎます。営業日が3日以上になるように指定してください" },
  });
  assert.equal(fieldFail.step, 3);
  assert.equal(fieldFail.running, null);
  assert.equal(fieldFail.focus.target, "error");
  assert.match(fieldFail.fieldErrors.start_date ?? "", /期間が短すぎます/);

  const otherFail = flowReducer(running, { type: "runFailed", id: 7, message: "API サーバーに接続できません", fieldErrors: {} });
  assert.equal(otherFail.step, 4);
  assert.equal(otherFail.runError, "API サーバーに接続できません");
  // 入力を直したらエラーは消える
  assert.equal(flowReducer(otherFail, { type: "editForm", form: otherFail.form! }).runError, null);
});

test("実行のリクエストは、確認の画面に出ている銘柄(詳細を読んだ銘柄)のもの", () => {
  const confirmed = atConfirm();
  assert.deepEqual(currentRequest(confirmed), {
    symbol_id: "DEMO:1001",
    strategy_id: "ma_cross",
    engine: "python",
    start_date: "2024-01-04",
    end_date: "2025-12-30",
    params: { short_window: 5, long_window: 25, fee_rate_pct: 0.1, slippage_rate_pct: 0.05, initial_cash: 1_000_000 },
  });
  // 別の銘柄を選んだ直後(詳細がまだ届いていない)は、実行できない
  const switching = flowReducer(confirmed, { type: "selectSymbol", symbol: symbol("DEMO:1002"), request: 4 });
  assert.equal(currentRequest(switching), null);
});

test("API のエラーの振り分け:入力欄のある項目だけを欄に出し、ほかは確認の画面の文に添える", () => {
  const request = currentRequest(atConfirm())!;
  const error = new ApiError(422, "入力内容を確認してください", [
    { field: "fee_rate_pct", message: "手数料率とスリッページ率は0以上で入力してください" },
    { field: "start_date", message: "期間が短すぎます。営業日が3日以上になるように指定してください" },
    { field: "strategy_id", message: "この戦略はまだ使えません" },
    { field: "engine", message: "C++ 版はまだビルドされていません" },
    { field: null, message: "入力内容を確認してください" },
  ]);
  assert.deepEqual(fieldErrorsFrom(error, request), {
    fee_rate_pct: "手数料率とスリッページ率は0以上で入力してください",
    start_date: "期間が短すぎます。営業日が3日以上になるように指定してください",
  });
  assert.equal(
    runErrorMessage(error, request),
    "入力内容を確認してください(この戦略はまだ使えません・C++ 版はまだビルドされていません)",
  );
  // ApiError 以外は、欄に出すものはなく、次にすることを添えた予備の文
  assert.deepEqual(fieldErrorsFrom(new Error("boom"), request), {});
  assert.match(runErrorMessage(new Error("boom"), request), /バックテストを実行できませんでした。ページを再読み込み/);
  assert.equal(runErrorMessage(new ApiError(0, "API サーバーに接続できません"), request), "API サーバーに接続できません");
});

test("結果の動きは一度だけ(戻ってきたときは再生しない)", () => {
  const done = atResult();
  assert.notEqual(done.animated, done.last?.id);
  const played = flowReducer(done, { type: "resultAnimated", id: 2 });
  assert.equal(played.animated, 2);
  const again = run([{ type: "goTo", step: 3 }, { type: "goTo", step: 5 }], played);
  assert.equal(again.step, 5);
  assert.equal(again.animated, again.last?.id);
});

test("手順を移ると見出しへのフォーカスを頼む。同じ手順への移動では頼まない", () => {
  const s = atParams();
  const moved = flowReducer(s, { type: "goTo", step: 1 });
  assert.equal(moved.focus.target, "heading");
  assert.ok(moved.focus.seq > s.focus.seq);
  assert.equal(flowReducer(moved, { type: "goTo", step: 1 }), moved);
});

test("戦略の一覧が詳細より後に届いても、入力欄の初期値を作る。読み込みの失敗は読み直せる", () => {
  const s = run([
    { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 1 },
    { type: "detailLoaded", request: 1, detail: detail("DEMO:1001") },
  ]);
  assert.equal(s.form, null);
  const t = flowReducer(s, loaded);
  assert.equal(t.form?.params.long_window, "25");
  const failed = flowReducer(initialFlow, { type: "catalogFailed", message: "接続できません" });
  assert.equal(failed.catalogError, "接続できません");
  assert.equal(flowReducer(failed, { type: "catalogRetry" }).catalogError, null);
});

test("選んでいた戦略が一覧にない・使えないときは、最初の使える戦略に替える", () => {
  const missing = flowReducer({ ...initialFlow, strategyId: "gone" }, loaded);
  assert.equal(missing.strategyId, "ma_cross");
  const unavailable = flowReducer({ ...initialFlow, strategyId: "rsi_reversal" }, loaded);
  assert.equal(unavailable.strategyId, "ma_cross");
});

test("戦略を変えると、期間は残し、パラメータは新しい戦略の既定値にする", () => {
  const s = edit(atParams(), { short_window: "7" }, { start_date: "2024-06-03" });
  const other = flowReducer(s, { type: "selectStrategy", id: "rsi_reversal" });
  assert.equal(other.form?.start_date, "2024-06-03");
  assert.deepEqual(other.form?.params, {}); // RSI 逆張りはまだパラメータを持たない(今後追加予定)
});

test("使えない戦略では先に進めず、手順の表示からも条件・確認の手順に移れない", () => {
  const atStrategy = run([
    loaded,
    { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 1 },
    { type: "detailLoaded", request: 1, detail: detail("DEMO:1001") },
    { type: "advance" },
    { type: "selectStrategy", id: "rsi_reversal" },
    { type: "advance" },
  ]);
  assert.equal(atStrategy.step, 2);
  // 一度確認まで進んだあとで、使えない戦略に替えた場合
  const switched = run(
    [
      { type: "goTo", step: 2 },
      { type: "selectStrategy", id: "rsi_reversal" },
    ],
    atConfirm(),
  );
  assert.equal(canVisit(switched, 3), false);
  assert.equal(canVisit(switched, 4), false);
  assert.equal(currentRequest(switched), null);
  assert.equal(flowReducer(switched, { type: "goTo", step: 4 }).step, 2);
});
