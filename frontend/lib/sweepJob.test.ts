import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, type SweepRequest, type SweepStatus } from "./api.ts";
import { runSweepJob, type SweepJobApi } from "./sweepJob.ts";
import { sweepResult } from "./testing.ts";

const REQUEST = { symbol_id: "DEMO:1001" } as SweepRequest;

function status(state: SweepStatus["status"], done = 0, extra: Partial<SweepStatus> = {}): SweepStatus {
  return { id: "job-1", status: state, done, total: 4, elapsed_ms: null, result: null, error: null, ...extra };
}

/** 決めた順に応答を返す API。Error を入れた位置では、その例外を投げる。DELETE の回数も数える。 */
function scripted(start: SweepStatus | Error, polls: (SweepStatus | Error)[]) {
  const calls = { polls: 0, cancels: 0 };
  const api: SweepJobApi = {
    startSweep: async () => {
      if (start instanceof Error) throw start;
      return start;
    },
    sweepStatus: async () => {
      const next = polls[calls.polls];
      calls.polls += 1;
      if (next === undefined) throw new Error("問い合わせが多すぎます");
      if (next instanceof Error) throw next;
      return next;
    },
    cancelSweep: async () => {
      calls.cancels += 1;
      return status("cancelled");
    },
  };
  return { api, calls };
}

function options(api: SweepJobApi, waits: number[] = [], isCurrent = () => true) {
  const progress: number[] = [];
  return {
    progress,
    opts: {
      api,
      wait: async (ms: number) => {
        waits.push(ms);
      },
      isCurrent,
      onProgress: (s: SweepStatus) => progress.push(s.done),
    },
  };
}

test("終わるまで問い合わせ、途中経過を伝えて、結果を返す", async () => {
  const done = status("done", 4, { result: sweepResult("DEMO:1001"), elapsed_ms: 1200 });
  const { api, calls } = scripted(status("running"), [status("running", 2), done]);
  const { opts, progress } = options(api);
  const outcome = await runSweepJob(REQUEST, opts);
  assert.equal(outcome.kind, "done");
  assert.deepEqual(progress, [0, 2]);
  assert.equal(calls.polls, 2);
  assert.equal(calls.cancels, 0);
});

test("問い合わせの一時的な失敗は、待つ時間を倍にしながらやり直す", async () => {
  const offline = new ApiError(500, "API サーバーに接続できません");
  const done = status("done", 4, { result: sweepResult("DEMO:1001") });
  const { api, calls } = scripted(status("running"), [offline, offline, status("running", 3), done]);
  const waits: number[] = [];
  const { opts } = options(api, waits);
  const outcome = await runSweepJob(REQUEST, opts);
  assert.equal(outcome.kind, "done");
  assert.deepEqual(waits, [400, 800, 1600, 400]); // 成功したら元の間隔に戻る
  assert.equal(calls.cancels, 0);
});

test("やり直しても失敗するときは、ジョブの中止を頼んでから失敗にする", async () => {
  const offline = new ApiError(500, "API サーバーに接続できません");
  const { api, calls } = scripted(status("running"), [offline, offline, offline, offline]);
  const { opts } = options(api);
  const outcome = await runSweepJob(REQUEST, opts);
  assert.equal(outcome.kind, "error");
  assert.equal(calls.polls, 4); // 1回目 + やり直し3回
  assert.equal(calls.cancels, 1);
});

test("ジョブが見つからない(404)ときは、やり直さない", async () => {
  const gone = new ApiError(404, "その総当たりは見つかりません");
  const { api, calls } = scripted(status("running"), [gone]);
  const outcome = await runSweepJob(REQUEST, options(api).opts);
  assert.equal(outcome.kind, "error");
  assert.equal(calls.polls, 1);
});

test("画面を閉じたら問い合わせをやめて、ジョブの中止を頼む", async () => {
  const { api, calls } = scripted(status("running"), [status("running", 1)]);
  let current = true;
  const { opts } = options(api, [], () => current);
  opts.wait = async () => {
    current = false; // 待っているあいだに画面を閉じた
  };
  const outcome = await runSweepJob(REQUEST, opts);
  assert.equal(outcome.kind, "stopped");
  assert.equal(calls.polls, 0);
  assert.equal(calls.cancels, 1);
});

test("中止・ジョブの失敗・始められないとき", async () => {
  const cancelled = await runSweepJob(REQUEST, options(scripted(status("running"), [status("cancelled", 2)]).api).opts);
  assert.equal(cancelled.kind, "cancelled");

  const failedStatus = status("failed", 2, { error: { detail: "データに異常があるため計算できません:株数が大きすぎて計算できません", errors: [] } });
  const failed = await runSweepJob(REQUEST, options(scripted(status("running"), [failedStatus]).api).opts);
  assert.deepEqual(failed, { kind: "failed", message: "データに異常があるため計算できません:株数が大きすぎて計算できません" });

  const rejected = new ApiError(422, "入力内容を確認してください", [{ field: "grid", message: "組み合わせが多すぎます" }]);
  const { api, calls } = scripted(rejected, []);
  const start = await runSweepJob(REQUEST, options(api).opts);
  assert.equal(start.kind, "error");
  assert.equal(start.kind === "error" && start.error, rejected);
  assert.equal(calls.cancels, 0); // ジョブはできていない
});
