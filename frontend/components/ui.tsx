// 画面のあちこちで使う小さな部品。

export function StepHeading({
  id,
  step,
  title,
  children,
}: {
  id: string;
  step: number;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <header>
      {/* 手順が変わったら、ここにフォーカスを移す(BacktestApp)。読み上げで今の手順が分かるようにするため */}
      <h2 id={id} data-step-heading tabIndex={-1} className="text-[22px] font-bold text-ink outline-none sm:text-[26px]">
        <span className="sr-only">手順{step}:</span>
        {title}
      </h2>
      {children && <p className="mt-1 max-w-[40em] text-[15px] text-ink-2">{children}</p>}
    </header>
  );
}

export function SecondaryButton({
  children,
  onClick,
  disabled,
  describedBy,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  /** 押す前に読んでほしい説明の要素の id(aria-describedby) */
  describedBy?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-describedby={describedBy}
      className="inline-flex items-center rounded-md px-4 py-2.5 text-[15px] text-ink-2 ring-1 ring-rule-strong hover:bg-surface hover:text-ink disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/**
 * 入力欄の下に出す誤り。role="alert" にはしない:確認へ進もうとしたときは最初の誤りの欄にフォーカスが移り、
 * aria-describedby でこの文が読み上げられる(全部の欄の誤りを一斉に読み上げると、かえって分かりにくいため)。
 */
export function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="mt-1 text-[13px] leading-6 text-shu">
      {message}
    </p>
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 rounded-md bg-ink px-5 py-2.5 text-[15px] font-bold text-paper hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/**
 * 横・縦にスクロールする枠(表など)。
 * - キーボードだけでもスクロールできるように、フォーカスを受け取れるようにして名前を付ける(WCAG 2.1.1。axe の scrollable-region-focusable)
 * - relative:読み上げ用に隠した文字(sr-only は position: absolute)を枠の中にとどめる。ないと、スマートフォンでページ全体が横にはみ出す
 */
export function ScrollRegion({
  label,
  className = "",
  children,
}: {
  /** 読み上げで伝える枠の名前(例:「日々の数値の表」) */
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className={`relative focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink ${className}`}
    >
      {children}
    </div>
  );
}
