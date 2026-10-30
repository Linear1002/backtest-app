// 手順の表示(銘柄 → 戦略 → 条件 → 確認 → 結果)。移れる手順はクリックで移れる。
// 移れるかどうかは lib/flow.ts の canVisit が決める(結果の画面は、いまの条件で出した結果があるときだけ)。

import type { StepId } from "@/lib/flow.ts";

export const STEPS = [
  { id: 1, label: "銘柄" },
  { id: 2, label: "戦略" },
  { id: 3, label: "条件" },
  { id: 4, label: "確認" },
  { id: 5, label: "結果" },
] as const satisfies readonly { id: StepId; label: string }[];

export function Stepper({
  current,
  isAvailable,
  locked,
  onSelect,
}: {
  current: StepId;
  isAvailable: (step: StepId) => boolean;
  /** 計算中など、手順を移れないとき */
  locked: boolean;
  onSelect: (step: StepId) => void;
}) {
  return (
    <nav aria-label="手順">
      <ol className="flex items-center gap-1 sm:gap-2">
        {STEPS.map((step, index) => {
          const isCurrent = step.id === current;
          const available = !locked && !isCurrent && isAvailable(step.id);
          // 済んだ手順:いまより前の手順か、いまより先でも移れる(前に進んだことがある)手順
          const isDone = !isCurrent && (step.id < current || available);
          const circle = isCurrent
            ? "bg-ink text-paper"
            : isDone
              ? "bg-surface text-ink ring-1 ring-ink-2"
              : "bg-transparent text-ink-3 ring-1 ring-rule-strong";
          const content = (
            <>
              <span
                className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-[13px] font-bold tabular ${circle}`}
                aria-hidden="true"
              >
                {isDone ? "✓" : step.id}
              </span>
              {/* 狭い画面では、いまの手順以外の名前を隠す(読み上げには残す) */}
              <span
                className={`text-[14px] ${isCurrent ? "font-bold text-ink" : isDone ? "text-ink-2" : "text-ink-3"} ${isCurrent ? "" : "sr-only sm:not-sr-only"}`}
              >
                {step.label}
              </span>
            </>
          );
          return (
            <li key={step.id} className="flex h-9 items-center gap-1 sm:gap-2">
              {available ? (
                <button
                  type="button"
                  onClick={() => onSelect(step.id)}
                  className="flex h-9 items-center gap-2 rounded-full pr-2 leading-none hover:bg-surface"
                  aria-label={`${step.id}. ${step.label}${step.id < current ? "に戻る" : "へ進む"}`}
                >
                  {content}
                </button>
              ) : (
                <span className="flex h-9 items-center gap-2 pr-2 leading-none" aria-current={isCurrent ? "step" : undefined}>
                  {content}
                </span>
              )}
              {index < STEPS.length - 1 && <span className="h-px w-3 bg-rule-strong sm:w-6" aria-hidden="true" />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
