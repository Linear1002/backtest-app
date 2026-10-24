import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canVisit,
  currentRequest,
  flowReducer,
  initialFlow,
  resultIsOutdated,
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

/** 手順5(結果)まで進んだ状態。 */
function atResult(): FlowState {
  return run(
    [
      { type: "submitParams" },
      { type: "runStarted", id: 2 },
      { type: "runSucceeded", id: 2, result: result("DEMO:1001") },
    ],
    atParams(),
  );
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
  const retry = flowReducer(failed, { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 2 });
  assert.equal(retry.detailRequest, 2);
  assert.equal(retry.detailError, null);
});

test("同じ銘柄を選び直しても、結果も条件も消えない", () => {
  const done = atResult();
  const again = flowReducer(done, { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 9 });
  assert.equal(again, done);
});

test("銘柄を変えると入力エラーと実行エラーが消え、期間だけが新しい銘柄の範囲になる", () => {
  const s = run(
    [
      { type: "editForm", form: { ...atParams().form!, params: { ...atParams().form!.params, short_window: "7", initial_cash: "abc" } } },
      { type: "submitParams" },
    ],
    atParams(),
  );
  assert.equal(s.fieldErrors.initial_cash, "数値で入力してください");
  const changed = run(
    [
      { type: "selectSymbol", symbol: symbol("DEMO:1002"), request: 3 },
      { type: "detailLoaded", request: 3, detail: detail("DEMO:1002", "2024-06-03", "2025-11-28") },
    ],
    s,
  );
  assert.deepEqual(changed.fieldErrors, {});
  assert.equal(changed.runError, null);
  assert.equal(changed.form?.start_date, "2024-06-03");
  assert.equal(changed.form?.end_date, "2025-11-28");
  assert.equal(changed.form?.params.short_window, "7"); // 日数などはそのまま
});

test("入力に誤りがあると確認へ進まず、最初の誤りの欄にフォーカスを移す", () => {
  const s = atParams();
  const bad = run(
    [{ type: "editForm", form: { ...s.form!, params: { ...s.form!.params, fee_rate_pct: "-1" } } }, { type: "submitParams" }],
    s,
  );
  assert.equal(bad.step, 3);
  assert.equal(bad.fieldErrors.fee_rate_pct, "手数料率とスリッページ率は0以上で入力してください");
  assert.equal(bad.focus.target, "error");
  assert.ok(bad.focus.seq > s.focus.seq);
});

test("一度確認まで進んだあとに条件を誤りのある値にすると、確認の手順には移れない", () => {
  const confirmed = flowReducer(atParams(), { type: "submitParams" });
  assert.equal(confirmed.step, 4);
  const back = flowReducer(confirmed, { type: "goTo", step: 3 });
  const bad = flowReducer(back, { type: "editForm", form: { ...back.form!, params: { ...back.form!.params, initial_cash: "" } } });
  assert.equal(canVisit(bad, 4), false);
  assert.equal(flowReducer(bad, { type: "goTo", step: 4 }).step, 3);
  // 期間だけがおかしい場合も同じ
  const badPeriod = flowReducer(back, { type: "editForm", form: { ...back.form!, start_date: "2020-01-01" } });
  assert.equal(canVisit(badPeriod, 4), false);
});

test("条件を変えたら、前の結果の画面には戻れない(元に戻せば、また見られる)", () => {
  const done = atResult();
  const back = flowReducer(done, { type: "goTo", step: 3 });
  const original = back.form!;
  const edited = flowReducer(back, { type: "editForm", form: { ...original, params: { ...original.params, fee_rate_pct: "0.2" } } });
  assert.equal(canVisit(edited, 5), false);
  assert.equal(resultIsOutdated(edited), true);
  assert.equal(flowReducer(edited, { type: "goTo", step: 5 }).step, 3);
  const reverted = flowReducer(edited, { type: "editForm", form: original });
  assert.equal(canVisit(reverted, 5), true);
  assert.equal(resultIsOutdated(reverted), false);
  // 数値として同じなら同じ条件(0.10 と 0.1)
  const same = flowReducer(edited, { type: "editForm", form: { ...original, params: { ...original.params, fee_rate_pct: "0.10" } } });
  assert.equal(canVisit(same, 5), true);
});

test("計算エンジンを変えても、前の結果とは別の条件になる", () => {
  const done = atResult();
  const other = flowReducer(done, { type: "selectEngine", id: "cpp" });
  assert.equal(canVisit(other, 5), false);
});

test("実行中は手順を移れず、二重に実行しない", () => {
  const confirmed = flowReducer(atParams(), { type: "submitParams" });
  const running = flowReducer(confirmed, { type: "runStarted", id: 7 });
  assert.equal(running.running?.id, 7);
  for (const step of [1, 2, 3] as const) {
    assert.equal(canVisit(running, step), false);
    assert.equal(flowReducer(running, { type: "goTo", step }).step, 4);
  }
  assert.equal(flowReducer(running, { type: "runStarted", id: 8 }), running);
});

test("新しい実行に置きかわった古い実行の結果・エラーは捨てる", () => {
  const confirmed = flowReducer(atParams(), { type: "submitParams" });
  const running = flowReducer(confirmed, { type: "runStarted", id: 7 });
  assert.equal(flowReducer(running, { type: "runSucceeded", id: 6, result: result("DEMO:1001") }), running);
  assert.equal(flowReducer(running, { type: "runFailed", id: 6, message: "x", fieldErrors: {} }), running);
  // 実行していないときに届いた結果も捨てる
  assert.equal(flowReducer(confirmed, { type: "runSucceeded", id: 7, result: result("DEMO:1001") }), confirmed);
});

test("実行の失敗:入力の誤りなら条件の画面に戻り、それ以外は確認の画面にエラーを出す", () => {
  const confirmed = flowReducer(atParams(), { type: "submitParams" });
  const running = flowReducer(confirmed, { type: "runStarted", id: 7 });
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
  const edited = flowReducer(otherFail, { type: "editForm", form: otherFail.form! });
  assert.equal(edited.runError, null);
});

test("実行のリクエストは、確認の画面に出ている銘柄(詳細を読んだ銘柄)のもの", () => {
  const confirmed = flowReducer(atParams(), { type: "submitParams" });
  const request = currentRequest(confirmed);
  assert.deepEqual(request, {
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

test("結果の動きは一度だけ(戻ってきたときは再生しない)", () => {
  const done = atResult();
  assert.notEqual(done.animated, done.last?.id);
  const played = flowReducer(done, { type: "resultAnimated", id: 2 });
  assert.equal(played.animated, 2);
  const again = run([{ type: "goTo", step: 3 }, { type: "goTo", step: 5 }], played);
  assert.equal(again.step, 5);
  assert.equal(again.animated, again.last?.id);
});

test("手順を移ると見出しにフォーカスを移す。同じ手順への移動では移さない", () => {
  const s = atParams();
  const moved = flowReducer(s, { type: "goTo", step: 1 });
  assert.equal(moved.focus.target, "heading");
  assert.ok(moved.focus.seq > s.focus.seq);
  assert.equal(flowReducer(moved, { type: "goTo", step: 1 }), moved);
});

test("初期データ(戦略の一覧)が詳細より後に届いても、入力欄の初期値を作る", () => {
  const s = run([
    { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 1 },
    { type: "detailLoaded", request: 1, detail: detail("DEMO:1001") },
  ]);
  assert.equal(s.form, null);
  const t = flowReducer(s, loaded);
  assert.equal(t.form?.params.long_window, "25");
  // 読み込みに失敗 → もう一度読み込む
  const failed = flowReducer(initialFlow, { type: "catalogFailed", message: "接続できません" });
  assert.equal(failed.catalogError, "接続できません");
  assert.equal(flowReducer(failed, { type: "catalogRetry" }).catalogError, null);
});

test("使えない戦略では先に進めない", () => {
  const s = run([
    loaded,
    { type: "selectSymbol", symbol: symbol("DEMO:1001"), request: 1 },
    { type: "detailLoaded", request: 1, detail: detail("DEMO:1001") },
    { type: "advance" },
    { type: "selectStrategy", id: "rsi_reversal" },
    { type: "advance" },
  ]);
  assert.equal(s.step, 2);
});
