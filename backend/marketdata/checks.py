"""docs/mvp.md 3.1 の「要確認」を、実際の J-Quants のデータで確かめる。

公式ドキュメントに書かれていない、次の3点を調べる:
1. AdjFactor の小数の桁数(分数への戻し方と、相対誤差 1e-4 の基準が足りるか)
2. 売買不成立の日のレコードに、AdjFactor と ExRT の値が入るか
3. ExRT が 1〜3 以外の値をとるか(調整係数が 1 でないのに ExRT が無い日はないか)

分割の権利落ち日は、月末の権利確定日の前の営業日に集まりやすい。そこで、各月の「最後から2番目の営業日」の
全銘柄の日足を日付指定で取り、調整係数が 1 でないレコードを集める。
Free プランは1分間に5回までなので、24か月分で10分ほどかかる。
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.marketdata.jquants import JQuantsClient
from engine.reference.ratio import recover_split_ratio
from engine.reference.types import EngineDataError

BUSINESS_DAY_DIVISIONS = (
    "1",
    "2",
)  # 1:営業日 2:半日立会(https://jpx-jquants.com/en/spec/mkt-cal/holiday-division)


@dataclass
class AssumptionReport:
    dates: list[dt.date] = field(default_factory=list)
    records: int = 0
    adjusted: list[tuple[str, str, str, str | None, bool]] = field(default_factory=list)
    ex_rt_counts: Counter = field(default_factory=Counter)
    halted: int = 0
    halted_without_factor: int = 0
    halted_with_action: int = 0
    unrecoverable: list[tuple[str, str, str]] = field(default_factory=list)
    missing_ex_rt: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def max_decimals(self) -> int:
        return max((_decimals(text) for _, _, text, _, _ in self.adjusted), default=0)

    def lines(self) -> list[str]:
        out = [
            f"調べた日: {len(self.dates)} 日({self.dates[0] if self.dates else '-'}〜{self.dates[-1] if self.dates else '-'})",
            f"調べたレコード: {self.records} 件",
            f"調整係数が1でないレコード: {len(self.adjusted)} 件",
        ]
        samples = sorted({text for _, _, text, _, _ in self.adjusted})[:12]
        out.append(f"  係数の例: {', '.join(samples) if samples else 'なし'}")
        out.append(f"  小数の最大桁数: {self.max_decimals}")
        out.append(f"  ExRT の値と件数: {dict(self.ex_rt_counts) or 'なし'}")
        out.append(f"売買不成立のレコード: {self.halted} 件")
        out.append(f"  そのうち AdjFactor が Null: {self.halted_without_factor} 件")
        out.append(f"  そのうち権利落ちと重なった日: {self.halted_with_action} 件")
        out.append("")
        out.append("【要確認1】AdjFactor の桁数と、分数への戻し方")
        if self.unrecoverable:
            out.append(
                "  × 分数に戻せない係数がありました。docs/mvp.md 2.8 の基準を見直す必要があります:"
            )
            out.extend(
                f"    {code} {date} AdjFactor={text}"
                for code, date, text in self.unrecoverable[:20]
            )
        elif self.adjusted:
            out.append(
                f"  ○ 分割・併合の係数はすべて p/q(q ≤ 1000、相対誤差 1e-4 以下)に戻せました(最大 {self.max_decimals} 桁)"
            )
        else:
            out.append(
                "  - 調整係数が1でないレコードが見つかりませんでした。--months を増やしてください"
            )
        out.append("【要確認2】売買不成立の日の AdjFactor / ExRT")
        if self.halted == 0:
            out.append("  - 売買不成立のレコードが見つかりませんでした")
        elif self.halted_without_factor:
            out.append(
                "  × 売買不成立の日に AdjFactor が Null のレコードがあります。2.8 の「Null はエラー」を見直す必要があります"
            )
        else:
            out.append("  ○ 売買不成立の日にも AdjFactor は入っていました")
        out.append("【要確認3】ExRT の値")
        unknown = [v for v in self.ex_rt_counts if v not in ("1", "2", "3")]
        if unknown or self.missing_ex_rt:
            out.append(
                f"  × 想定外の ExRT: {unknown}、係数が1でないのに ExRT が無い: {len(self.missing_ex_rt)} 件"
            )
            out.extend(
                f"    {code} {date} AdjFactor={text}"
                for code, date, text in self.missing_ex_rt[:20]
            )
        else:
            out.append("  ○ ExRT は 1〜3 だけで、係数が1でない日には必ず ExRT がありました")
        return out


def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _is_one(text: str) -> bool:
    try:
        return float(text) == 1.0
    except ValueError:
        return False


def pick_dates(business_days: list[dt.date], months: int) -> list[dt.date]:
    """各月の最後から2番目の営業日を、新しい月から months か月分。"""
    by_month: dict[tuple[int, int], list[dt.date]] = {}
    for day in sorted(business_days):
        by_month.setdefault((day.year, day.month), []).append(day)
    picked = [days[-2] for days in by_month.values() if len(days) >= 2]
    return sorted(picked)[-months:]


def scan_assumptions(
    client: JQuantsClient, *, months: int = 24, progress: Callable[[str], None] = print
) -> AssumptionReport:
    calendar = client.get_all("/markets/calendar")
    business_days = [
        dt.date.fromisoformat(item["Date"])
        for item in calendar
        if str(item.get("HolDiv")) in BUSINESS_DAY_DIVISIONS
    ]
    report = AssumptionReport(dates=pick_dates(business_days, months))
    for n, day in enumerate(report.dates, start=1):
        progress(f"[{n}/{len(report.dates)}] {day} の全銘柄を取得しています...")
        items = client.daily_bars(date=day, parse_float=str)
        for item in items:
            inspect_record(report, item)
    return report


def inspect_record(report: AssumptionReport, item: dict) -> None:
    report.records += 1
    code, date = str(item.get("Code")), str(item.get("Date"))
    factor_raw = item.get("AdjFactor")
    factor = None if factor_raw is None else str(factor_raw)
    ex_rt = None if item.get("ExRT") in (None, "") else str(item.get("ExRT"))
    halted = all(item.get(key) is None for key in ("O", "H", "L", "C"))
    if halted:
        report.halted += 1
        if factor is None:
            report.halted_without_factor += 1
    if ex_rt is not None:
        report.ex_rt_counts[ex_rt] += 1
    if factor is None or _is_one(factor):
        return
    if halted:
        report.halted_with_action += 1
    report.adjusted.append((code, date, factor, ex_rt, halted))
    if ex_rt is None:
        report.missing_ex_rt.append((code, date, factor))
    elif ex_rt in ("1", "2"):
        try:
            recover_split_ratio(float(factor))
        except EngineDataError:
            report.unrecoverable.append((code, date, factor))
