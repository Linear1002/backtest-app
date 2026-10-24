"use client";

import { useId } from "react";

import type { ParamKey, ParamSpec, SweepGridKey, SymbolDetail } from "@/lib/api.ts";
import { describeYen, formatDate } from "@/lib/format.ts";
import { presetPeriod, toNumber, type FieldErrors, type FormState, type RunMode } from "@/lib/form.ts";
import { holdoutOf } from "@/lib/flow.ts";
import { dayBefore, holdoutStart, parseSweepGrid, validateHoldout, type HoldoutChoice } from "@/lib/sweep.ts";

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

const MODES: { mode: RunMode; label: string; help: string }[] = [
  { mode: "single", label: "1組で試す", help: "短期と長期の日数を1組決めて、売買の記録まで詳しく見る" },
  { mode: "sweep", label: "総当たりで比べる", help: "日数の組み合わせをすべて試して、ヒートマップで比べる" },
];

const HOLDOUT_CHOICES: { choice: HoldoutChoice; label: string }[] = [
  { choice: "last30", label: "最後の3割" },
  { choice: "last20", label: "最後の2割" },
  { choice: "last1y", label: "最後の1年" },
  { choice: "custom", label: "日付を指定" },
  { choice: "none", label: "使わない" },
];

const count = new Intl.NumberFormat("ja-JP");

export function ParamsStep({
  detail,
  specs,
  form,
  errors,
  notice = null,
  sweepMaxPairs = null,
  onChange,
  onModeChange,
  onNext,
}: {
  detail: SymbolDetail;
  specs: ParamSpec[];
  form: FormState;
  errors: FieldErrors;
  /** 実行したときの、入力欄に出せない誤り(戦略・エンジンなど)の文 */
  notice?: string | null;
  /** 総当たりのエンジンの、組み合わせの数の上限(エンジンの一覧がまだなければ null) */
  sweepMaxPairs?: number | null;
  onChange: (next: FormState) => void;
  onModeChange: (mode: RunMode) => void;
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
  const sweep = form.mode === "sweep";

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
          <ModeSwitch mode={form.mode} onChange={onModeChange} />
          {sweep ? (
            <SweepGridFields form={form} errors={errors} maxPairs={sweepMaxPairs} onChange={onChange} />
          ) : (
            <>
              <div className="mt-4 flex flex-wrap gap-2">
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
            </>
          )}
        </Group>

        {sweep && <HoldoutFields form={form} error={errors.holdout_start_date} onChange={onChange} />}

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

/** 「1組で試す」と「総当たりで比べる」の切り替え(ラジオボタンの組)。 */
function ModeSwitch({ mode, onChange }: { mode: RunMode; onChange: (mode: RunMode) => void }) {
  const name = useId();
  return (
    <div role="radiogroup" aria-label="試し方" className="grid gap-2 sm:grid-cols-2">
      {MODES.map((m) => (
        <label
          key={m.mode}
          className={`flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2 text-[14px] ${
            mode === m.mode ? "border-ink bg-surface" : "border-rule hover:bg-surface"
          }`}
        >
          <input
            type="radio"
            name={name}
            value={m.mode}
            checked={mode === m.mode}
            onChange={() => onChange(m.mode)}
            className="mt-1.5 accent-[var(--ink)]"
          />
          <span>
            <span className="block font-bold text-ink">{m.label}</span>
            <span className="block text-[12px] leading-5 text-ink-3">{m.help}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

const GRID_ROWS: { label: string; keys: [SweepGridKey, SweepGridKey, SweepGridKey] }[] = [
  { label: "短期の日数", keys: ["short_min", "short_max", "short_step"] },
  { label: "長期の日数", keys: ["long_min", "long_max", "long_step"] },
];
const GRID_PARTS = ["最小", "最大", "刻み"];

/** 総当たりの格子(短期・長期それぞれ最小・最大・刻み)と、組み合わせの数。 */
function SweepGridFields({
  form,
  errors,
  maxPairs,
  onChange,
}: {
  form: FormState;
  errors: FieldErrors;
  maxPairs: number | null;
  onChange: (next: FormState) => void;
}) {
  const summaryId = useId();
  // 入力のたびに数えて見せる(上限を超えたら、確認へ進む前に分かるように)
  const parsed = parseSweepGrid(form.sweep, maxPairs);
  const gridError = errors.grid;
  return (
    <div className="mt-4 space-y-4">
      {GRID_ROWS.map((row) => (
        <fieldset key={row.label}>
          <legend className="text-[14px] text-ink-2">{row.label}</legend>
          <div className="mt-1 grid grid-cols-3 gap-3">
            {row.keys.map((key, i) => (
              <SmallNumberField
                key={key}
                label={`${row.label}の${GRID_PARTS[i]}`}
                visibleLabel={GRID_PARTS[i]}
                value={form.sweep[key]}
                unit="日"
                error={errors[key]}
                describedBy={summaryId}
                onChange={(v) => onChange({ ...form, sweep: { ...form.sweep, [key]: v } })}
              />
            ))}
          </div>
        </fieldset>
      ))}
      <p
        id={summaryId}
        // 「組み合わせがない・多すぎる」はどの欄のものでもないので、確認へ進もうとしたときはここにフォーカスを移す
        data-invalid-anchor={gridError ? "true" : undefined}
        tabIndex={gridError ? -1 : undefined}
        className={`text-[14px] leading-6 outline-none ${gridError ? "text-shu" : "text-ink-2"}`}
      >
        {gridError ??
          (parsed.pairs !== null
            ? `組み合わせ:${count.format(parsed.pairs)}通り(短期の日数が長期の日数より小さい組だけ)`
            : "組み合わせの数は、入力を直すと表示します")}
      </p>
      <p className="text-[13px] leading-6 text-ink-3">
        組み合わせごとに、選ぶ期間と検証期間を別々にバックテストします。
        {maxPairs !== null && `このエンジンでは${count.format(maxPairs)}通りまで計算できます。`}
      </p>
    </div>
  );
}

/** 検証期間(アウトオブサンプル)の決め方。 */
function HoldoutFields({
  form,
  error,
  onChange,
}: {
  form: FormState;
  error?: string;
  onChange: (next: FormState) => void;
}) {
  const dateId = useId();
  const choice = form.sweep.holdout;
  const holdout = holdoutOf(form);
  const setChoice = (next: HoldoutChoice) => {
    // 「日付を指定」に切り替えたときは、いまの開始日を入れておく(そこから直せるように)
    const current = holdoutOf(form);
    const holdoutDate = next === "custom" && !form.sweep.holdout_date && current ? current : form.sweep.holdout_date;
    onChange({ ...form, sweep: { ...form.sweep, holdout: next, holdout_date: holdoutDate } });
  };
  // 期間に対して決められない決め方(期間が1年以下のときの「最後の1年」など)は出さない
  const usable = HOLDOUT_CHOICES.filter(
    (c) => c.choice === "none" || c.choice === "custom" || c.choice === choice || validateHoldout(form, holdoutStart(form, c.choice, "")) === null,
  );
  const valid = holdout !== null && validateHoldout(form, holdout) === null;
  return (
    <Group
      title="検証期間(アウトオブサンプル)"
      note="期間の最後の部分を「検証期間」として取っておき、組み合わせを選ぶのには使いません。選んだ組み合わせが、選ぶのに使っていない期間でも通用するかを確かめるためです"
    >
      <div
        role="group"
        aria-label="検証期間の決め方"
        data-invalid-anchor={error && choice !== "custom" ? "true" : undefined}
        tabIndex={error && choice !== "custom" ? -1 : undefined}
        className="flex flex-wrap gap-2 outline-none"
      >
        {usable.map((c) => (
          <Chip key={c.choice} active={choice === c.choice} onClick={() => setChoice(c.choice)}>
            {c.label}
          </Chip>
        ))}
      </div>
      {choice === "custom" && (
        <div className="mt-3 max-w-[20rem]">
          <label htmlFor={dateId} className="block text-[14px] text-ink-2">
            検証期間の開始日
          </label>
          <input
            id={dateId}
            type="date"
            value={form.sweep.holdout_date}
            min={form.start_date}
            max={form.end_date}
            onChange={(e) => onChange({ ...form, sweep: { ...form.sweep, holdout_date: e.target.value } })}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? `${dateId}-error` : undefined}
            className={`mt-1 w-full rounded-md border bg-surface px-3 py-2 tabular text-ink ${error ? "border-shu" : "border-field"}`}
          />
        </div>
      )}
      <FieldError id={`${dateId}-error`} message={error} />
      <p className="mt-2 text-[13px] leading-6 text-ink-2">
        {choice === "none"
          ? "検証期間なし:期間全体で選びます。選んだ組み合わせが、ほかの期間でも通用するかは確かめられません"
          : valid && holdout
            ? `選ぶ期間 ${formatDate(form.start_date)}〜${formatDate(dayBefore(holdout))} ・ 検証期間 ${formatDate(holdout)}〜${formatDate(form.end_date)}`
            : ""}
      </p>
    </Group>
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

/** 総当たりの格子の小さな入力欄(見出しは「最小」など短く、読み上げでは「短期の日数の最小」と伝える)。 */
function SmallNumberField({
  label,
  visibleLabel,
  value,
  unit,
  error,
  describedBy,
  onChange,
}: {
  label: string;
  visibleLabel: string;
  value: string;
  unit: string;
  error?: string;
  describedBy: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-[13px] text-ink-3">
        <span aria-hidden="true">{visibleLabel}</span>
        <span className="sr-only">{label}</span>
      </label>
      <div className="mt-1 flex items-center gap-1.5">
        <input
          id={id}
          inputMode="numeric"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={`${error ? `${id}-error ` : ""}${describedBy}`}
          className={`w-full min-w-0 rounded-md border bg-surface px-2 py-2 text-right tabular text-ink ${error ? "border-shu" : "border-field"}`}
        />
        <span className="shrink-0 text-[14px] text-ink-2">{unit}</span>
      </div>
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}
