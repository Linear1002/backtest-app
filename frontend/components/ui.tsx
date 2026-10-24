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
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center rounded-md px-4 py-2.5 text-[15px] text-ink-2 ring-1 ring-rule-strong hover:bg-surface hover:text-ink disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="mt-1 text-[13px] leading-6 text-shu" role="alert">
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
