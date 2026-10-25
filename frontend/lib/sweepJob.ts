// 総当たりのジョブを動かす(docs/sweep.md 10章):POST で始め、終わるまで GET で途中経過を問い合わせる。
// 画面の部品から切り離して、API の呼び出しと待ち時間を差し替えられるようにしてある(lib/sweepJob.test.ts)。
//
// 決まりごと
// - 問い合わせ(GET)が失敗しても、すぐに失敗にしない。待つ時間を倍にしながら数回やり直す(一時的な通信の切れ目のため)
// - やり直しても失敗するときや、画面を閉じて問い合わせをやめるときは、ジョブの中止(DELETE)を頼む。
//   止めないと、API はそのジョブを最大60秒計算し続け、同時に計算できる2つの枠の1つを使ってしまう
// - ジョブが見つからない(404。API を起動し直した・30分たった)ときは、やり直さない

import { ApiError, type SweepRequest, type SweepStatus } from "./api.ts";

export type SweepJobApi = {
  startSweep: (request: SweepRequest) => Promise<SweepStatus>;
  sweepStatus: (id: string) => Promise<SweepStatus>;
  cancelSweep: (id: string) => Promise<SweepStatus>;
};

export type SweepJobOptions = {
  api: SweepJobApi;
  /** 待つ(テストでは待たずにすぐ返す) */
  wait: (ms: number) => Promise<void>;
  /** まだこのジョブの結果を待っているか(画面を閉じた・別の実行を始めたら false) */
  isCurrent: () => boolean;
  /** 途中経過を受け取るたびに呼ぶ */
  onProgress: (status: SweepStatus) => void;
  /** 問い合わせの間隔(ミリ秒) */
  pollMs?: number;
  /** 問い合わせが続けて失敗したときに、やり直す回数 */
  retries?: number;
};

export type SweepJobOutcome =
  | { kind: "done"; status: SweepStatus }
  | { kind: "cancelled" }
  /** API がジョブの失敗を返した(計算の途中のデータの異常など) */
  | { kind: "failed"; message: string }
  /** 始められなかった・問い合わせられなかった(入力の誤り・通信の失敗など) */
  | { kind: "error"; error: unknown }
  /** 画面のほうで待つのをやめた */
  | { kind: "stopped" };

export const POLL_MS = 400;
export const RETRIES = 3;

/** やり直しても意味がない失敗か(ジョブがもうない)。 */
function isFatal(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** ジョブの中止を頼む(失敗しても気にしない。API は問い合わせが来なくなったジョブを60秒で打ち切る)。 */
function cancelQuietly(api: SweepJobApi, id: string): void {
  api.cancelSweep(id).catch(() => undefined);
}

export async function runSweepJob(request: SweepRequest, options: SweepJobOptions): Promise<SweepJobOutcome> {
  const { api, wait, isCurrent, onProgress, pollMs = POLL_MS, retries = RETRIES } = options;
  let status: SweepStatus;
  try {
    status = await api.startSweep(request);
  } catch (error) {
    return { kind: "error", error };
  }
  let failures = 0;
  while (status.status === "running") {
    onProgress(status);
    // 失敗が続くときは、待つ時間を倍にしていく(400ms → 800ms → 1.6秒 → 3.2秒)
    await wait(pollMs * 2 ** failures);
    if (!isCurrent()) {
      cancelQuietly(api, status.id);
      return { kind: "stopped" };
    }
    try {
      status = await api.sweepStatus(status.id);
      failures = 0;
    } catch (error) {
      failures += 1;
      if (isFatal(error) || failures > retries) {
        cancelQuietly(api, status.id);
        return { kind: "error", error };
      }
    }
  }
  if (status.status === "done" && status.result) return { kind: "done", status };
  if (status.status === "cancelled") return { kind: "cancelled" };
  return { kind: "failed", message: status.error?.detail ?? "総当たりを実行できませんでした" };
}
