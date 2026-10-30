"use client";

import { useId } from "react";

import type { ParamKey, ParamSpec, SymbolDetail } from "@/lib/api.ts";
import { describeYen, formatDate } from "@/lib/format.ts";
import { presetPeriod, toNumber, type FieldErrors, type FormState } from "@/lib/form.ts";

import { FieldError, PrimaryButton, StepHeading } from "../ui.tsx";

const WINDOW_PRESETS = [
  { short: 5, long: 25, label: "5日と25日" },
  { short: 25, long: 75, label: "25日と75日" },
];

const PERIOD_PRESETS: { years: number | null; label: string }[] = [
  { years: null, label: "全期間" },
  { years: 2, label: "直近2年" },
  { years: 1, label: "直近1年" },
];

export function ParamsStep({
  detail,
  specs,
  form,
  errors,
  notice = null,
  onChange,
  onNext,
}: {
  detail: SymbolDetail;
  specs: ParamSpec[];
  form: FormState;
  errors: FieldErrors;
  /** 実行したときの、入力欄に出せない誤り(戦略・エンジンなど)の文 */
  notice?: string | null;
  onChange: (next: FormState) => void;
  onNext: () => void;
}) {
  const headingId = useId();
  const spec = (key: ParamKey) => specs.find((s) => s.key === key) ?? null;
  const setParam = (key: ParamKey, value: string) =>
    onChange({ ...form, params: { ...form.params, [key]: value } });
  const range = detail.range;
  const field = (key: ParamKey, unit: string, hint?: string) => {
    const s = spec(key);
    // 戦略の定義に項目がなければ出さない(戦略ごとに項目が違うため)
    if (!s) return null;
    return (
      <NumberField
        spec={s}
        value={form.params[key] ?? ""}
        unit={unit}
        error={errors[key]}
        hint={hint}
        onChange={(v) => setParam(key, v)}
      />
    );
  };
  const cash = toNumber(form.params.initial_cash ?? "");

  return (
    <section aria-labelledby={headingId}>
      <StepHeading id={headingId} step={3} title="条件を決める">
        期間と移動平均の日数、売買にかかる費用を決めます。迷ったら、そのまま進んで大丈夫です。
      </StepHeading>

      {notice && (
        <p role="alert" className="mt-6 rounded-md border border-shu px-4 py-3 text-[14px] text-shu">
          {notice}
        </p>
      )}

      <form
        className="mt-6 space-y-8"
        onSubmit={(e) => {
          e.preventDefault();
          onNext();
        }}
        noValidate
      >
        <Group title="期間" note={`データの期間:${formatDate(range.first_date)}〜${formatDate(range.last_date)}`}>
          <div className="flex flex-wrap gap-2">
            {PERIOD_PRESETS.map((preset, index) => {
              const value = presetPeriod(range, preset.years);
              const same = (a: { start_date: string; end_date: string }) =>
                a.start_date === value.start_date && a.end_date === value.end_date;
              // データが2年に満たないと「直近2年」は「全期間」と同じ期間になる。同じ期間のチップは出さない
              if (PERIOD_PRESETS.slice(0, index).some((p) => same(presetPeriod(range, p.years)))) return null;
              return (
                <Chip key={preset.label} active={same(form)} onClick={() => onChange({ ...form, ...value })}>
                  {preset.label}
                </Chip>
              );
            })}
          </div>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <DateField
              label="開始日"
              value={form.start_date}
              min={range.first_date}
              max={range.last_date}
              error={errors.start_date}
              onChange={(v) => onChange({ ...form, start_date: v })}
            />
            <DateField
              label="終了日"
              value={form.end_date}
              min={range.first_date}
              max={range.last_date}
              error={errors.end_date}
              onChange={(v) => onChange({ ...form, end_date: v })}
            />
          </div>
          <p className="mt-2 text-[13px] leading-6 text-ink-3">
            開始日より前のデータがあれば、移動平均の計算に使います(ウォームアップ)。開始日・終了日は休場日でもかまいません。
          </p>
        </Group>

        <Group title="移動平均の日数" note="短期線が長期線を上に抜けたら買い、下に抜けたら売り">
          <div className="flex flex-wrap gap-2">
            {WINDOW_PRESETS.map((p) => (
              <Chip
                key={p.label}
                active={form.params.short_window === String(p.short) && form.params.long_window === String(p.long)}
                onClick={() =>
                  onChange({
                    ...form,
                    params: { ...form.params, short_window: String(p.short), long_window: String(p.long) },
                  })
                }
              >
                {p.label}
              </Chip>
            ))}
          </div>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {field("short_window", "日")}
            {field("long_window", "日")}
          </div>
        </Group>

        <Group title="売買の費用" note="売りと買いの両方にかかります。0 にすると実際より良い結果になりやすいので注意">
          <div className="grid gap-4 sm:grid-cols-2">
            {field("fee_rate_pct", "%")}
            {field("slippage_rate_pct", "%")}
          </div>
        </Group>

        <Group title="初期資金" note={`売買単位は${detail.market.lot_size}株。資金が${detail.market.lot_size}株分に足りないときは買いません`}>
          {field("initial_cash", "円", cash !== null ? describeYen(cash) : undefined)}
        </Group>

        <div className="flex justify-end border-t border-rule pt-6">
          <PrimaryButton type="submit">確認へ進む</PrimaryButton>
        </div>
      </form>
    </section>
  );
}

function Group({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <fieldset>
      <legend className="text-[16px] font-bold text-ink">{title}</legend>
      {note && <p className="mb-3 text-[13px] leading-6 text-ink-3">{note}</p>}
      {children}
    </fieldset>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-3 py-1 text-[13px] ${
        active ? "bg-ink text-paper" : "text-ink-2 ring-1 ring-rule-strong hover:bg-surface"
      }`}
    >
      {children}
    </button>
  );
}

function DateField({
  label,
  value,
  min,
  max,
  error,
  onChange,
}: {
  label: string;
  value: string;
  min: string;
  max: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-[14px] text-ink-2">
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`mt-1 w-full rounded-md border bg-surface px-3 py-2 tabular text-ink ${error ? "border-shu" : "border-field"}`}
      />
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}

function NumberField({
  spec,
  value,
  unit,
  error,
  hint,
  onChange,
}: {
  spec: ParamSpec;
  value: string;
  unit: string;
  error?: string;
  hint?: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-[14px] text-ink-2">
        {spec.label}
      </label>
      <div className="mt-1 flex items-center gap-2">
        <input
          id={id}
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={`${id}-help${error ? ` ${id}-error` : ""}`}
          className={`w-full rounded-md border bg-surface px-3 py-2 text-right tabular text-ink ${error ? "border-shu" : "border-field"}`}
        />
        <span className="w-6 shrink-0 text-[14px] text-ink-2">{unit}</span>
      </div>
      <p id={`${id}-help`} className="mt-1 text-[13px] leading-6 text-ink-3">
        {hint ? `${hint}。` : ""}
        {spec.help}
      </p>
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}
