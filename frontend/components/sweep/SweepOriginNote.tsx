"use client";

// 総当たりの結果から「詳しく見る」で開いた1組のバックテストに、どこから来たものかを書く(docs/sweep.md 8章)。
// 選ぶ期間で見るときは、その期間で選んだので良く見えやすいことも書く。
// 総当たりと同じエンジン・同じデータ(取得日時)のときだけ、「総当たりの表と同じ計算です」と書く。

import { useId } from "react";

import type { SweepOrigin } from "@/lib/flow.ts";
import { formatDate } from "@/lib/format.ts";

import { SecondaryButton } from "../ui.tsx";

const count = new Intl.NumberFormat("ja-JP");

/** 出どころの期間の呼び方(検証期間がない総当たりなら「総当たりの期間」)。 */
export function originLabel(origin: SweepOrigin): string {
  if (!origin.hasHoldout) return "総当たりの期間";
  return origin.segment.name === "in_sample" ? "選ぶ期間" : "検証期間";
}

export function SweepOriginNote({
  origin,
  done,
  sameCalculation,
}: {
  origin: SweepOrigin;
  /** 計算した後(結果の画面)か */
  done: boolean;
  /** 総当たりと同じエンジン・同じデータで計算する(した)か(lib/flow.ts の sameCalculationAsSweep) */
  sameCalculation: boolean;
}) {
  const { segment, trials } = origin;
  const label = originLabel(origin);
  const period = `${formatDate(segment.first_business_day)}〜${formatDate(segment.last_business_day)}`;
  return (
    <p className="rounded-md border border-rule bg-surface-2 px-4 py-3 text-[13px] leading-6 text-ink-2">
      総当たり({count.format(trials)}通り)の中から選んだ組み合わせを、{label}({period})だけで
      {done ? "計算した結果です" : "計算します"}。
      {sameCalculation
        ? `総当たりの表の、この組み合わせの${label}の行と同じ計算です。`
        : "総当たりとは計算エンジンかデータの取得日時が違うため、総当たりの表の数字と少し違うことがあります。"}
      {segment.name === "out_of_sample"
        ? "検証期間は、選ぶのに使っていない期間です。"
        : origin.hasHoldout
          ? "選ぶ期間の成績は、この期間で選んだので良く見えやすくなっています。"
          : "この期間の成績で選んだので、良く見えやすくなっています。"}
    </p>
  );
}

/**
 * 「総当たりの結果に戻る」ボタン。押すと条件が総当たりを実行したときのものに置き換わるときは
 * (「詳しく見る」から来た条件でないとき)、ボタンの下にそう書く。
 */
export function BackToSweepButton({
  onClick,
  replacesInput,
  disabled,
}: {
  onClick: () => void;
  replacesInput: boolean;
  disabled?: boolean;
}) {
  const noteId = useId();
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <SecondaryButton onClick={onClick} disabled={disabled} describedBy={replacesInput ? noteId : undefined}>
        総当たりの結果に戻る
      </SecondaryButton>
      {replacesInput && (
        <span id={noteId} className="text-[12px] text-ink-3">
          条件は、総当たりを実行したときのものに戻ります
        </span>
      )}
    </span>
  );
}
