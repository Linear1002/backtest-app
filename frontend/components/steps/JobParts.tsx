"use client";

// 総当たり・ウォークフォワード分析の確認の画面で共通の部品:計算エンジンの選択・途中経過と中止・実行のボタン。
// どちらも同じジョブの仕組み(lib/sweepJob.ts)で動く。

import type { SweepEngineInfo } from "@/lib/api.ts";

import { Seal } from "../Seal.tsx";
import { SecondaryButton } from "../ui.tsx";

const count = new Intl.NumberFormat("ja-JP");

/** 読み上げで知らせる区切り(途中経過の数字が変わるたびには読み上げない)。 */
const MILESTONES = ["計算を始めました", "4分の1まで終わりました", "半分まで終わりました", "4分の3まで終わりました"];

export function EngineChoice({
  engines,
  selected,
  running,
  onChange,
}: {
  engines: SweepEngineInfo[];
  selected: string;
  running: boolean;
  onChange: (id: string) => void;
}) {
  return (
    <fieldset className="mt-8">
      <legend className="text-[15px] font-bold text-ink">計算エンジン</legend>
      <div className="mt-2 flex flex-wrap gap-3">
        {engines.map((e) => (
          <label
            key={e.id}
            className={`flex min-w-[15rem] items-start gap-2 rounded-md border px-3 py-2 text-[14px] ${
              e.available ? "cursor-pointer border-rule bg-surface" : "cursor-not-allowed border-dashed border-rule text-ink-3"
            } ${selected === e.id ? "border-ink" : ""}`}
          >
            <input
              type="radio"
              name="sweep-engine"
              value={e.id}
              checked={selected === e.id}
              disabled={!e.available || running}
              onChange={() => onChange(e.id)}
              className="mt-1.5 accent-[var(--ink)]"
            />
            <span>
              <span className={`block ${e.available ? "text-ink" : ""}`}>{e.label}</span>
              <span className="block text-[12px] text-ink-3">{e.note}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * 実行の前後の知らせ(条件が前の結果と違う・中止した・エラー)と、実行中の途中経過・中止のボタン、実行のボタン。
 * name は「総当たり」「ウォークフォワード分析」。
 */
export function JobStatusAndRun({
  name,
  runLabel,
  running,
  progress,
  cancelled,
  cancelError,
  error,
  outdated,
  onRun,
  onCancel,
}: {
  name: string;
  runLabel: string;
  running: boolean;
  /** 実行中の途中経過(API が受け付ける前は null)。数は組み合わせの数 */
  progress: { done: number; total: number } | null;
  cancelled: boolean;
  cancelError: string | null;
  error: string | null;
  outdated: boolean;
  onRun: () => void;
  onCancel: () => void;
}) {
  const ratio = progress && progress.total > 0 ? progress.done / progress.total : 0;
  const milestone = MILESTONES[Math.min(MILESTONES.length - 1, Math.floor(ratio * 4))];
  return (
    <>
      {outdated && !running && (
        <p className="mt-6 text-[13px] leading-6 text-ink-2">
          ※ 前に出した{name}の結果とは条件が違います。実行すると、この条件の新しい結果になります。
        </p>
      )}

      {cancelled && !running && (
        // 押した「中止する」ボタンは消えるので、フォーカスをこの知らせに移す(lib/flow.ts の jobCancelled)
        <p className="mt-6 text-[14px] text-ink-2 outline-none" role="status" tabIndex={-1} data-focus-notice>
          {name}を中止しました。条件を変えるか、もう一度実行してください。
        </p>
      )}

      {error && (
        <p role="alert" className="mt-6 rounded-md border border-shu px-4 py-3 text-[14px] text-shu">
          {error}
        </p>
      )}

      {/* 読み上げは区切り(始め・4分の1・半分・4分の3)だけ。数字は見た目の文とバーで伝える。
          読み上げの領域は実行していないときも置いておく(実行と同時に作ると、最初の区切りが読まれにくいため) */}
      <p className="sr-only" aria-live="polite">
        {running ? `${name}の${milestone}` : ""}
      </p>
      {running && (
        <div className="mt-8 rounded-md border border-rule bg-surface px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[14px] text-ink" aria-hidden="true">
              {progress && progress.total > 0
                ? `計算しています(${count.format(progress.done)} / ${count.format(progress.total)}通り)`
                : "計算を始めています…"}
            </p>
            <SecondaryButton onClick={onCancel} disabled={!progress}>
              中止する
            </SecondaryButton>
          </div>
          {cancelError && (
            <p role="alert" className="mt-2 text-[13px] text-shu">
              {cancelError}
            </p>
          )}
          <div
            role="progressbar"
            aria-label={`${name}の進み具合`}
            aria-valuemin={0}
            aria-valuemax={progress?.total || 1}
            aria-valuenow={progress?.done ?? 0}
            className="mt-3 h-2 overflow-hidden rounded-full bg-paper"
          >
            <div className="h-full rounded-full bg-ink transition-[width] duration-300" style={{ width: `${Math.round(ratio * 100)}%` }} />
          </div>
        </div>
      )}

      <div className="mt-8 flex justify-end border-t border-rule pt-6">
        <button
          type="button"
          onClick={onRun}
          disabled={running}
          className="inline-flex items-center gap-3 rounded-md bg-ink py-2.5 pl-3 pr-6 text-[16px] font-bold text-paper hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
        >
          <Seal kind="check" size={26} decorative />
          {running ? "計算しています…" : runLabel}
        </button>
      </div>
    </>
  );
}
