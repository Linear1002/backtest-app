import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, createApi, errorMessage, UNREACHABLE } from "./api.ts";

/** fetch の代わり:決まった応答を返し、呼ばれたアドレスと中身を記録する。 */
function stub(status: number, body: string, contentType = "application/json") {
  const calls: { path: string; init?: RequestInit }[] = [];
  const fetchImpl = async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return new Response(body, { status, headers: { "Content-Type": contentType } });
  };
  return { api: createApi(fetchImpl), calls };
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    assert.ok(e instanceof ApiError, `ApiError ではない: ${String(e)}`);
    return e;
  }
  throw new Error("失敗するはずの呼び出しが成功した");
}

test("200:本文の JSON を返す", async () => {
  const { api, calls } = stub(200, JSON.stringify({ items: [{ id: "ma_cross" }] }));
  const items = await api.strategies();
  assert.deepEqual(items, [{ id: "ma_cross" }]);
  assert.equal(calls[0].path, "/api/strategies");
});

test("422:日本語のメッセージと、項目ごとのエラーを受け取る", async () => {
  const { api } = stub(
    422,
    JSON.stringify({
      detail: "入力内容を確認してください",
      errors: [
        { field: "fee_rate_pct", message: "手数料率とスリッページ率は0以上で入力してください" },
        { field: null, message: "全体のエラー" },
      ],
    }),
  );
  const e = await failure(api.runBacktest({} as never));
  assert.equal(e.status, 422);
  assert.equal(e.message, "入力内容を確認してください");
  assert.deepEqual(e.fieldErrors(), { fee_rate_pct: "手数料率とスリッページ率は0以上で入力してください" });
});

test("JSON の 500:サーバーの中のエラーとして、サーバーのメッセージをそのまま出す", async () => {
  const detail = "サーバーの中で想定していないエラーが起きました。API サーバーのターミナルに出ているエラーを確認してください";
  const { api } = stub(500, JSON.stringify({ detail, errors: [] }));
  const e = await failure(api.meta());
  assert.equal(e.message, detail);
  assert.notEqual(e.message, UNREACHABLE);
});

test("JSON でない 500(Next.js の中継が API につながらない):起動の案内を出す", async () => {
  const { api } = stub(500, "Internal Server Error", "text/plain");
  const e = await failure(api.meta());
  assert.equal(e.message, UNREACHABLE);
  for (const status of [502, 503, 504]) {
    const r = stub(status, "<html>Bad Gateway</html>", "text/html");
    assert.equal((await failure(r.api.meta())).message, UNREACHABLE);
  }
});

test("通信そのものの失敗:起動の案内を出す", async () => {
  const api = createApi(async () => {
    throw new TypeError("fetch failed");
  });
  const e = await failure(api.symbol("DEMO:1001"));
  assert.equal(e.status, 0);
  assert.equal(e.message, UNREACHABLE);
});

test("JSON でない 404 や、読めない 200 には、次にすることを添える", async () => {
  const notFound = await failure(stub(404, "<html>not found</html>", "text/html").api.meta());
  assert.match(notFound.message, /HTTP 404/);
  assert.match(notFound.message, /再読み込み/);
  const unreadable = await failure(stub(200, "{broken", "application/json").api.meta());
  assert.match(unreadable.message, /読み取れませんでした/);
});

test("detail がない JSON のエラーにも、次にすることを添える", async () => {
  const e = await failure(stub(418, JSON.stringify({ something: 1 })).api.meta());
  assert.match(e.message, /HTTP 418/);
  assert.match(e.message, /ターミナル/);
  assert.deepEqual(e.errors, []);
});

test("銘柄IDはアドレスに入れる前にエスケープする", async () => {
  const { api, calls } = stub(200, "{}");
  await api.symbol("TSE:186A");
  assert.equal(calls[0].path, "/api/symbols/TSE%3A186A");
  await api.searchSymbols("ゆうなぎ&x", 30);
  assert.equal(calls[1].path, `/api/symbols?q=${encodeURIComponent("ゆうなぎ&x")}&limit=30`);
});

test("バックテストの実行は POST で、本文は JSON", async () => {
  const { api, calls } = stub(200, "{}");
  await api.runBacktest({
    symbol_id: "DEMO:1001",
    strategy_id: "ma_cross",
    engine: "python",
    start_date: null,
    end_date: null,
    params: { short_window: 5, long_window: 25, fee_rate_pct: 0.1, slippage_rate_pct: 0.05, initial_cash: 1_000_000 },
  });
  assert.equal(calls[0].init?.method, "POST");
  assert.equal(JSON.parse(String(calls[0].init?.body)).symbol_id, "DEMO:1001");
});

test("ApiError 以外の失敗は、次にすることを添えた予備の文にする", () => {
  assert.equal(errorMessage(new ApiError(422, "入力内容を確認してください"), "x"), "入力内容を確認してください");
  assert.equal(errorMessage(new Error("boom"), "銘柄を検索できませんでした"), "銘柄を検索できませんでした。ページを再読み込みして、もう一度試してください");
});
