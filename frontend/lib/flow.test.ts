import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError } from "./api.ts";
import {
  canShowSweep,
  canVisit,
  currentRequest,
  currentSweepRequest,
  fieldErrorsFrom,
  flowReducer,
  initialFlow,
  needsSymbolLoad,
  resultIsOutdated,
  runErrorMessage,
  sweepOrigin,
  unplacedErrorMessage,
  type FlowAction,
  type FlowState,
} from "./flow.ts";
import type { SweepForm } from "./sweep.ts";
import { detail, META, result, STRATEGIES, sweepResult, symbol } from "./testing.ts";

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

test("2つの欄にまたがる誤りは、相手の欄を直しても消える(まだ当てはまる誤りは残る)", () => {
  // 「短期は長期より小さく」は短期の欄に出る。長期を長くして直したら消える
  const crossed = flowReducer(edit(atParams(), { short_window: "30" }), { type: "submitParams" });
  assert.equal(crossed.fieldErrors.short_window, "短期の日数は長期の日数より小さくしてください");
  assert.equal(edit(crossed, { long_window: "60" }).fieldErrors.short_window, undefined);
  // 長期を変えても、まだ短期 ≥ 長期なら残る
  assert.equal(edit(crossed, { long_window: "29" }).fieldErrors.short_window, "短期の日数は長期の日数より小さくしてください");
  // 短期の欄だけの誤り(整数でない)は、長期を変えても残る
  const own = flowReducer(edit(atParams(), { short_window: "2.5" }), { type: "submitParams" });
  assert.equal(edit(own, { long_window: "30" }).fieldErrors.short_window, "日数は1以上の整数で入力してください");
  // 開始日の欄に出た「開始日は終了日より前」は、終了日を直したら消える
  const reversed = flowReducer(edit(atParams(), {}, { start_date: "2025-06-02", end_date: "2025-01-06" }), {
    type: "submitParams",
  });
  assert.equal(reversed.fieldErrors.start_date, "開始日は終了日より前の日付にしてください");
  assert.equal(edit(reversed, {}, { end_date: "2025-12-30" }).fieldErrors.start_date, undefined);
  // API だけが確かめる誤り(営業日が3日未満)は、終了日を変えたら消す(次の実行でもう一度確かめる)
  const running = started(atConfirm(), 9);
  const short = flowReducer(running, {
    type: "runFailed",
    id: 9,
    message: null,
    fieldErrors: { start_date: "期間が短すぎます。営業日が3日以上になるように指定してください" },
  });
  assert.ok(short.fieldErrors.start_date);
  assert.equal(edit(short, {}, { end_date: "2025-12-29" }).fieldErrors.start_date, undefined);
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
    { type: "runStarted", id: 8, request: currentRequest(atConfirm())! },
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
    message: null,
    fieldErrors: { start_date: "期間が短すぎます。営業日が3日以上になるように指定してください" },
  });
  assert.equal(fieldFail.step, 3);
  assert.equal(fieldFail.running, null);
  assert.equal(fieldFail.focus.target, "error");
  assert.match(fieldFail.fieldErrors.start_date ?? "", /期間が短すぎます/);

  assert.equal(fieldFail.runError, null); // 欄に出せる誤りだけのときは、画面の上には何も出さない

  // 欄に出せない誤り(戦略など)も一緒なら、その文を条件の画面の上に出す
  const mixed = flowReducer(running, {
    type: "runFailed",
    id: 7,
    message: "入力内容を確認してください(この戦略はまだ使えません)",
    fieldErrors: { fee_rate_pct: "手数料率とスリッページ率は0以上で入力してください" },
  });
  assert.equal(mixed.step, 3);
  assert.equal(mixed.runError, "入力内容を確認してください(この戦略はまだ使えません)");

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
  // 欄に出せない誤りだけの文(条件の画面に戻るときに、画面の上に出す)
  assert.equal(unplacedErrorMessage(error, request), runErrorMessage(error, request));
  const onlyFields = new ApiError(422, "入力内容を確認してください", [
    { field: "fee_rate_pct", message: "手数料率とスリッページ率は0以上で入力してください" },
  ]);
  assert.equal(unplacedErrorMessage(onlyFields, request), null);
  assert.equal(unplacedErrorMessage(new Error("boom"), request), null);
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

test("一覧を読み直して戦略が使えなくなったら、戦略を替え、入力欄も新しい戦略の既定値で作り直す", () => {
  const s = edit(atParams(), { short_window: "7" }, { start_date: "2024-06-03" });
  const renamed = STRATEGIES.map((st) => (st.id === "ma_cross" ? { ...st, id: "ma_cross_v2" } : st));
  const next = flowReducer(s, { type: "catalogLoaded", meta: META, strategies: renamed });
  assert.equal(next.strategyId, "ma_cross_v2");
  assert.equal(next.form?.start_date, "2024-06-03");
  assert.equal(next.form?.params.short_window, "5");
});

test("実行中に一覧が届いても、選んでいる戦略と入力欄は変えない", () => {
  const running = started(atConfirm(), 5);
  const renamed = STRATEGIES.map((st) => (st.id === "ma_cross" ? { ...st, id: "ma_cross_v2" } : st));
  const next = flowReducer(running, { type: "catalogLoaded", meta: META, strategies: renamed });
  assert.equal(next.strategyId, "ma_cross");
  assert.equal(next.form, running.form);
  assert.equal(next.catalog?.strategies[0].id, "ma_cross_v2");
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

// --- 総当たり(docs/sweep.md) -----------------------------------------------------------

function sweepMode(state: FlowState = atParams()): FlowState {
  return flowReducer(state, { type: "setMode", mode: "sweep" });
}

function editSweep(state: FlowState, changes: Partial<SweepForm>): FlowState {
  const form = state.form!;
  return flowReducer(state, { type: "editForm", form: { ...form, sweep: { ...form.sweep, ...changes } } });
}

/** 総当たりを始めた状態(番号 id)。 */
function sweepStarted(state: FlowState, id: number): FlowState {
  const request = currentSweepRequest(state);
  assert.ok(request, "総当たりを実行できる条件のはず");
  return flowReducer(state, { type: "sweepStarted", id, request });
}

/** 総当たりの結果(手順5)まで進んだ状態。 */
function atSweepResult(): FlowState {
  const confirm = flowReducer(sweepMode(), { type: "submitParams" });
  const running = sweepStarted(confirm, 11);
  return flowReducer(running, { type: "sweepSucceeded", id: 11, result: sweepResult("DEMO:1001"), elapsedMs: 1700 });
}

test("総当たりに切り替えると、1組のリクエストではなく総当たりのリクエストになる", () => {
  const s = sweepMode();
  assert.equal(currentRequest(s), null);
  // 期間 2024-01-04〜2025-12-30(726日)の最後の3割:開始日から round(726 × 0.7) = 508 日後
  assert.deepEqual(currentSweepRequest(s), {
    symbol_id: "DEMO:1001",
    strategy_id: "ma_cross",
    engine: "python",
    start_date: "2024-01-04",
    end_date: "2025-12-30",
    holdout_start_date: "2025-05-26",
    grid: { short_min: 3, short_max: 30, short_step: 3, long_min: 20, long_max: 120, long_step: 10 },
    params: { fee_rate_pct: 0.1, slippage_rate_pct: 0.05, initial_cash: 1_000_000 },
  });
  // 日数の欄(1組で試すときの欄)が誤っていても、総当たりには関係ない
  const odd = edit(s, { short_window: "abc" });
  assert.ok(currentSweepRequest(odd));
  assert.equal(flowReducer(odd, { type: "submitParams" }).step, 4);
  // 検証期間なし
  assert.equal(currentSweepRequest(editSweep(s, { holdout: "none" }))?.holdout_start_date, null);
});

test("総当たりの入力の誤りは、その欄に出て確認へ進めない(組み合わせの数の上限はエンジンごと)", () => {
  const bad = flowReducer(editSweep(sweepMode(), { short_min: "0" }), { type: "submitParams" });
  assert.equal(bad.step, 3);
  assert.equal(bad.fieldErrors.short_min, "日数と刻みは1以上の整数で入力してください");
  assert.equal(bad.focus.target, "error");

  const many = editSweep(sweepMode(), { short_min: "1", short_max: "100", short_step: "1", long_min: "2", long_max: "200", long_step: "1" });
  const tooMany = flowReducer(many, { type: "submitParams" });
  assert.ok(tooMany.fieldErrors.grid?.startsWith("組み合わせが多すぎます(14,950通り)。このエンジンでは2,000通りまで"));

  const early = flowReducer(editSweep(sweepMode(), { holdout: "custom", holdout_date: "2023-01-01" }), { type: "submitParams" });
  assert.equal(early.fieldErrors.holdout_start_date, "検証期間の開始日は、期間の開始日より後、終了日以前の日付にしてください");
});

test("格子の誤りも、相手の欄を直したら消える(最小 > 最大、組み合わせがない)", () => {
  const reversed = flowReducer(editSweep(sweepMode(), { short_min: "40", short_max: "30" }), { type: "submitParams" });
  assert.equal(reversed.fieldErrors.short_min, "短期の日数の範囲は、最小を最大以下にしてください");
  assert.equal(editSweep(reversed, { short_max: "50" }).fieldErrors.short_min, undefined);

  const none = flowReducer(editSweep(sweepMode(), { short_min: "150", short_max: "160" }), { type: "submitParams" });
  assert.match(none.fieldErrors.grid ?? "", /組み合わせがありません/);
  assert.equal(editSweep(none, { long_max: "200" }).fieldErrors.grid, undefined);
  // まだ組み合わせがなければ残る
  assert.ok(editSweep(none, { long_max: "130" }).fieldErrors.grid);
});

test("総当たりの実行:途中経過 → 結果の画面。条件を変えたら前の結果には戻れない", () => {
  const confirm = flowReducer(sweepMode(), { type: "submitParams" });
  assert.equal(confirm.step, 4);
  const running = sweepStarted(confirm, 11);
  assert.equal(running.running?.kind, "sweep");
  const progress = flowReducer(running, { type: "sweepProgress", id: 11, jobId: "job-1", done: 40, total: 105 });
  assert.deepEqual(
    progress.running && progress.running.kind === "sweep" && [progress.running.jobId, progress.running.done, progress.running.total],
    ["job-1", 40, 105],
  );
  // 番号の違う応答・1組の応答は捨てる
  assert.equal(flowReducer(progress, { type: "sweepProgress", id: 99, jobId: "x", done: 1, total: 1 }), progress);
  assert.equal(flowReducer(progress, { type: "runSucceeded", id: 11, result: result("DEMO:1001") }), progress);
  const done = flowReducer(progress, { type: "sweepSucceeded", id: 11, result: sweepResult("DEMO:1001"), elapsedMs: 1700 });
  assert.equal(done.step, 5);
  assert.equal(done.running, null);
  assert.equal(done.lastSweep?.elapsedMs, 1700);
  assert.ok(canVisit(done, 5));
  const changed = editSweep(done, { long_step: "20" });
  assert.equal(canVisit(changed, 5), false);
  assert.ok(resultIsOutdated(changed));
  assert.ok(canVisit(editSweep(changed, { long_step: "10" }), 5));
});

test("1組の結果と総当たりの結果は別々に覚えていて、切り替えるとそれぞれに戻れる", () => {
  const single = atResult();
  const sweep = atSweepResultFrom(single);
  assert.equal(sweep.last?.id, 2);
  assert.equal(sweep.lastSweep?.id, 12);
  const backToSingle = flowReducer(sweep, { type: "setMode", mode: "single" });
  assert.ok(canVisit(backToSingle, 5));
  assert.ok(canVisit(flowReducer(backToSingle, { type: "setMode", mode: "sweep" }), 5));
});

function atSweepResultFrom(state: FlowState): FlowState {
  const sweep = flowReducer(flowReducer(state, { type: "goTo", step: 3 }), { type: "setMode", mode: "sweep" });
  const confirm = flowReducer(sweep, { type: "submitParams" });
  const running = sweepStarted(confirm, 12);
  return flowReducer(running, { type: "sweepSucceeded", id: 12, result: sweepResult("DEMO:1001"), elapsedMs: 10 });
}

test("総当たりの1マスを詳しく見る:その期間だけの1組にして確認の画面へ(数字は総当たりのその行と同じ計算)", () => {
  const sweep = atSweepResult();
  const inspect = flowReducer(sweep, { type: "inspectCombo", short: 6, long: 20, segment: "in_sample" });
  assert.equal(inspect.step, 4);
  assert.equal(inspect.form?.mode, "single");
  const request = currentRequest(inspect)!;
  assert.deepEqual([request.params.short_window, request.params.long_window], [6, 20]);
  // 選ぶ期間(始まりをそろえたあとの日)〜 検証期間の前日
  assert.deepEqual([request.start_date, request.end_date], ["2024-02-01", "2025-06-30"]);
  assert.deepEqual(sweepOrigin(inspect.lastSweep, request), { segment: sweep.lastSweep!.result.segments[0], trials: 4 });
  const oos = currentRequest(flowReducer(sweep, { type: "inspectCombo", short: 6, long: 20, segment: "out_of_sample" }))!;
  assert.deepEqual([oos.start_date, oos.end_date], ["2025-07-01", "2025-12-30"]);
  assert.equal(sweepOrigin(inspect.lastSweep, oos)?.segment.name, "out_of_sample");
  // 日数を格子にない値に変えたら、総当たりから選んだものではなくなる
  assert.equal(sweepOrigin(inspect.lastSweep, currentRequest(edit(inspect, { short_window: "7" }))!), null);
});

test("総当たりの結果に戻る:確認の画面からも戻れて、総当たりを実行したときの条件と画面の見方に戻る", () => {
  const sweep = atSweepResult();
  assert.equal(sweep.sweepView.selected, 3); // 新しい結果は、シャープレシオの1位を選んだところから
  const viewed = flowReducer(sweep, { type: "sweepView", view: { objective: "total_return", segment: "out_of_sample", selected: 1 } });
  const inspect = flowReducer(viewed, { type: "inspectCombo", short: 3, long: 20, segment: "out_of_sample" });
  // 確認の画面で、費用まで変えてから戻っても
  const changed = edit(inspect, { fee_rate_pct: "0.2" });
  assert.ok(canShowSweep(changed));
  const back = flowReducer(changed, { type: "showSweep" });
  assert.equal(back.step, 5);
  assert.deepEqual(back.form, sweep.lastSweep!.form); // 総当たりを実行したときの入力欄
  assert.ok(canVisit(back, 5));
  assert.deepEqual(back.sweepView, { objective: "total_return", segment: "out_of_sample", selected: 1 });
  // 実行中・総当たりの結果がないときは戻れない
  assert.equal(canShowSweep(atResult()), false);
});

test("総当たりを中止すると、確認の画面のまま知らせを出す。入力を変えたら知らせは消える", () => {
  const running = sweepStarted(flowReducer(sweepMode(), { type: "submitParams" }), 13);
  const cancelled = flowReducer(running, { type: "sweepCancelled", id: 13 });
  assert.equal(cancelled.running, null);
  assert.equal(cancelled.step, 4);
  assert.equal(cancelled.sweepCancelled, true);
  assert.equal(cancelled.runError, null);
  // 押した「中止する」は消えるので、知らせにフォーカスを移す
  assert.equal(cancelled.focus.target, "notice");
  assert.ok(cancelled.focus.seq > running.focus.seq);
  assert.equal(editSweep(cancelled, { short_step: "3" }).sweepCancelled, false);
});

test("総当たりの実行中は、切り替え・詳しく見る・エンジンの変更を受け付けない", () => {
  const running = sweepStarted(flowReducer(sweepMode(), { type: "submitParams" }), 14);
  for (const action of [
    { type: "setMode", mode: "single" },
    { type: "inspectCombo", short: 3, long: 20, segment: "in_sample" },
    { type: "showSweep" },
    { type: "selectSweepEngine", id: "cuda" },
    { type: "goTo", step: 3 },
  ] as FlowAction[]) {
    assert.equal(flowReducer(running, action), running, action.type);
  }
  // 1組の実行も始めない
  assert.equal(currentRequest(running), null);
});

test("総当たりの失敗:欄に出せる誤りは条件の画面のその欄へ、ほかは確認の画面に文で出す", () => {
  const running = sweepStarted(flowReducer(sweepMode(), { type: "submitParams" }), 15);
  const field = flowReducer(running, {
    type: "sweepFailed",
    id: 15,
    message: null,
    fieldErrors: { holdout_start_date: "検証期間の営業日が3日未満です。検証期間の開始日を早くしてください" },
  });
  assert.equal(field.step, 3);
  assert.match(field.fieldErrors.holdout_start_date ?? "", /検証期間の営業日/);
  const other = flowReducer(running, { type: "sweepFailed", id: 15, message: "データに異常があるため計算できません", fieldErrors: {} });
  assert.equal(other.step, 4);
  assert.equal(other.runError, "データに異常があるため計算できません");
});

test("総当たりの API のエラーの振り分け:格子・検証期間・費用の欄は欄に、エンジンなどは文に", () => {
  const request = currentSweepRequest(sweepMode())!;
  const error = new ApiError(422, "入力内容を確認してください", [
    { field: "short_min", message: "日数と刻みは1以上の整数で入力してください" },
    { field: "grid", message: "組み合わせが多すぎます" },
    { field: "holdout_start_date", message: "検証期間の営業日が3日未満です" },
    { field: "fee_rate_pct", message: "手数料率とスリッページ率は0以上で入力してください" },
    { field: "engine", message: "総当たりでは CUDA 版はまだ使えません" },
  ]);
  assert.deepEqual(Object.keys(fieldErrorsFrom(error, request)).sort(), ["fee_rate_pct", "grid", "holdout_start_date", "short_min"]);
  assert.equal(unplacedErrorMessage(error, request), "入力内容を確認してください(総当たりでは CUDA 版はまだ使えません)");
  assert.equal(runErrorMessage(new Error("boom"), request, "総当たりを実行できませんでした"), "総当たりを実行できませんでした。ページを再読み込みして、もう一度試してください");
});

test("総当たりのエンジンが使えないものなら、一覧を受け取ったときに使えるものにする", () => {
  const s = flowReducer({ ...initialFlow, sweepEngine: "cuda" }, loaded);
  assert.equal(s.sweepEngine, "python");
});
