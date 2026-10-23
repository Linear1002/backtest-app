// 手順の表示(銘柄 → 戦略 → 条件 → 確認 → 結果)。終わった手順はクリックで戻れる。

export const STEPS = [
  { id: 1, label: "銘柄" },
  { id: 2, label: "戦略" },
  { id: 3, label: "条件" },
  { id: 4, label: "確認" },
  { id: 5, label: "結果" },
] as const;

export type StepId = (typeof STEPS)[number]["id"];

export function Stepper({
  current,
  reached,
  onSelect,
}: {
  current: StepId;
  reached: StepId;
  onSelect: (step: StepId) => void;
}) {
  return (
    <nav aria-label="手順">
      <ol className="flex items-center gap-1 sm:gap-2">
        {STEPS.map((step, index) => {
          const isCurrent = step.id === current;
          const isDone = step.id < current || (step.id <= reached && !isCurrent);
          const clickable = step.id <= reached && !isCurrent;
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
                {isDone && !isCurrent ? "✓" : step.id}
              </span>
              <span
                className={`text-[14px] ${isCurrent ? "font-bold text-ink" : isDone ? "text-ink-2" : "text-ink-3"} ${isCurrent ? "" : "hidden sm:inline"}`}
              >
                {step.label}
              </span>
            </>
          );
          return (
            <li key={step.id} className="flex h-9 items-center gap-1 sm:gap-2">
              {clickable ? (
                <button
                  type="button"
                  onClick={() => onSelect(step.id)}
                  className="flex h-9 items-center gap-2 rounded-full pr-2 leading-none hover:bg-surface"
                  aria-label={`${step.id}. ${step.label}に戻る`}
                >
                  {content}
                </button>
              ) : (
                <span
                  className="flex h-9 items-center gap-2 pr-2 leading-none"
                  aria-current={isCurrent ? "step" : undefined}
                >
                  {content}
                </span>
              )}
              {index < STEPS.length - 1 && (
                <span className="h-px w-3 bg-rule-strong sm:w-6" aria-hidden="true" />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
