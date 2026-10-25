// 総当たりの結果から「詳しく見る」で開いた1組のバックテストに、どこから来たものかを書く(docs/sweep.md 8章)。
// 選ぶ期間で見るときは、その期間で選んだので良く見えやすいことも書く。

import type { SweepSegment } from "@/lib/api.ts";
import { formatDate } from "@/lib/format.ts";

const count = new Intl.NumberFormat("ja-JP");

export type SweepOrigin = { segment: SweepSegment; trials: number };

export function SweepOriginNote({ origin, done }: { origin: SweepOrigin; /** 計算した後(結果の画面)か */ done: boolean }) {
  const { segment, trials } = origin;
  const label = segment.name === "in_sample" ? "選ぶ期間" : "検証期間";
  const period = `${formatDate(segment.first_business_day)}〜${formatDate(segment.last_business_day)}`;
  return (
    <p className="rounded-md border border-rule bg-surface-2 px-4 py-3 text-[13px] leading-6 text-ink-2">
      総当たり({count.format(trials)}通り)の中から選んだ組み合わせを、{label}({period})だけで
      {done ? "計算した結果です" : "計算します"}。総当たりの表の、この組み合わせの{label}の行と同じ計算です。
      {segment.name === "in_sample"
        ? "選ぶ期間の成績は、この期間で選んだので良く見えやすくなっています。"
        : "検証期間は、選ぶのに使っていない期間です。"}
    </p>
  );
}
