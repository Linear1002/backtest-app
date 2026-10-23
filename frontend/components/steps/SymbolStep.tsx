"use client";

import { useEffect, useId, useState } from "react";

import { api, ApiError, type Meta, type SymbolDetail, type SymbolSummary } from "@/lib/api.ts";
import { formatDate } from "@/lib/format.ts";

import { PrimaryButton, StepHeading } from "../ui.tsx";

export function SymbolStep({
  meta,
  selected,
  detail,
  onSelect,
  onNext,
}: {
  meta: Meta | null;
  selected: SymbolSummary | null;
  detail: SymbolDetail | null;
  onSelect: (symbol: SymbolSummary) => void;
  onNext: () => void;
}) {
  const inputId = useId();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<SymbolSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(
      () => {
        setLoading(true);
        api
          .searchSymbols(query, 30)
          .then((found) => {
            if (cancelled) return;
            setItems(found);
            setError(null);
          })
          .catch((e: unknown) => {
            if (!cancelled) setError(e instanceof ApiError ? e.message : "銘柄を検索できませんでした");
          })
          .finally(() => {
            if (!cancelled) setLoading(false);
          });
      },
      query ? 180 : 0,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  const jquants = meta?.data_sources.find((s) => s.id === "jquants");

  return (
    <section aria-labelledby={`${inputId}-heading`}>
      <StepHeading id={`${inputId}-heading`} step={1} title="銘柄を選ぶ">
        過去の株価で売買ルールを試す銘柄を1つ選びます。
      </StepHeading>

      {!jquants && (
        <p className="mt-4 rounded-md border border-rule bg-surface px-4 py-3 text-[14px] text-ink-2">
          いま使えるのは架空データ(DEMO)の12銘柄です。東証の銘柄を使うには、<code className="text-ink">.env</code>{" "}
          に J-Quants の APIキーを書いて、API サーバーを起動し直してください(docs/data.md)。
        </p>
      )}

      <div className="mt-6">
        <label htmlFor={inputId} className="block text-[14px] font-bold text-ink">
          銘柄コードまたは銘柄名
        </label>
        <input
          id={inputId}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="例:1003、ゆうなぎ"
          autoComplete="off"
          className="mt-2 w-full rounded-md border border-rule-strong bg-surface px-4 py-3 text-[17px] text-ink placeholder:text-ink-3 focus:border-ink"
        />
      </div>

      {error && (
        <p role="alert" className="mt-4 text-[14px] text-shu">
          {error}
        </p>
      )}

      <div className="mt-4" aria-live="polite" aria-busy={loading}>
        {!error && !loading && items.length === 0 && (
          <p className="py-6 text-[14px] text-ink-2">
            「{query}」に当てはまる銘柄はありません。4桁のコードか、銘柄名の一部で探してください。
          </p>
        )}
        <ul className="divide-y divide-rule border-y border-rule">
          {items.map((item) => {
            const isSelected = selected?.id === item.id;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onSelect(item)}
                  aria-pressed={isSelected}
                  className={`grid w-full grid-cols-[4.5rem_1fr] gap-x-4 px-3 py-3 text-left sm:grid-cols-[5rem_1fr_auto] ${
                    isSelected ? "bg-surface outline-2 -outline-offset-2 outline-ink" : "hover:bg-surface"
                  }`}
                >
                  <span className="tabular text-[15px] font-bold text-ink">{item.code}</span>
                  <span className="min-w-0">
                    <span className="block text-[15px] text-ink">{item.name}</span>
                    {item.description && (
                      <span className="block text-[13px] leading-6 text-ink-3">{item.description}</span>
                    )}
                  </span>
                  <span className="col-start-2 text-[13px] text-ink-3 sm:col-start-auto sm:text-right">
                    {[item.market, item.sector].filter(Boolean).join("/")}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {selected && (
        <div className="mt-6 rounded-md border border-rule bg-surface p-4 sm:p-5">
          <p className="text-[13px] text-ink-3">選んだ銘柄</p>
          <p className="mt-1 text-[18px] font-bold text-ink">
            {selected.name}
            <span className="ml-2 tabular text-[14px] font-normal text-ink-2">{selected.id}</span>
          </p>
          {detail && detail.symbol.id === selected.id ? (
            <dl className="mt-3 grid grid-cols-[7rem_1fr] gap-y-1 text-[14px]">
              <dt className="text-ink-3">データの期間</dt>
              <dd className="tabular text-ink">
                {formatDate(detail.range.first_date)}〜{formatDate(detail.range.last_date)}(
                {detail.range.business_days.toLocaleString("ja-JP")}営業日)
              </dd>
              <dt className="text-ink-3">権利落ち</dt>
              <dd className="text-ink">
                {detail.corporate_actions.length === 0
                  ? "なし"
                  : detail.corporate_actions
                      .map((a) => `${formatDate(a.date)} ${a.label}(係数 ${a.adj_factor})`)
                      .join("、")}
              </dd>
              <dt className="text-ink-3">売買不成立</dt>
              <dd className="text-ink">{detail.halted_days === 0 ? "なし" : `${detail.halted_days}日`}</dd>
              <dt className="text-ink-3">データ</dt>
              <dd className="text-ink-2">
                {detail.data_info.source_label}。{detail.data_info.license_note}
              </dd>
            </dl>
          ) : (
            <p className="mt-3 text-[14px] text-ink-3">データの期間を確かめています…</p>
          )}
          <div className="mt-5 flex justify-end">
            <PrimaryButton onClick={onNext} disabled={!detail || detail.symbol.id !== selected.id}>
              この銘柄で進む
            </PrimaryButton>
          </div>
        </div>
      )}
    </section>
  );
}
