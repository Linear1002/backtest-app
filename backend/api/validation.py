"""バックテストの入力チェック(docs/mvp.md 4.3)。

エラーはまとめて返す(1つ直すたびに次のエラーが出ると使いにくいため)。メッセージは仕様の表のとおり。
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from backend.api.schemas import ErrorItem, MaCrossParamsIn
from backend.marketdata.models import DailyBar, DateRange
from engine.reference import MaCrossParams

MAX_RATE_PCT = 10.0
MAX_INITIAL_CASH = 1_000_000_000
MIN_BUSINESS_DAYS = 3


class InputValidationError(Exception):
    def __init__(self, errors: list[ErrorItem]) -> None:
        super().__init__("入力内容を確認してください")
        self.errors = errors


@dataclass(frozen=True)
class ValidatedPeriod:
    start: dt.date
    end: dt.date


def _is_whole(value: float) -> bool:
    return math.isfinite(value) and float(value).is_integer()


def validate_params(raw: MaCrossParamsIn, lot_size: int) -> MaCrossParams:
    errors: list[ErrorItem] = []
    windows_ok = True
    for key in ("short_window", "long_window"):
        value = getattr(raw, key)
        if not _is_whole(value) or value < 1:
            errors.append(ErrorItem(field=key, message="日数は1以上の整数で入力してください"))
            windows_ok = False
    if windows_ok and raw.short_window >= raw.long_window:
        errors.append(
            ErrorItem(field="short_window", message="短期の日数は長期の日数より小さくしてください")
        )
    for key in ("fee_rate_pct", "slippage_rate_pct"):
        value = getattr(raw, key)
        if not math.isfinite(value) or value < 0:
            errors.append(
                ErrorItem(field=key, message="手数料率とスリッページ率は0以上で入力してください")
            )
        elif value >= MAX_RATE_PCT:
            errors.append(
                ErrorItem(field=key, message="手数料率とスリッページ率は10%未満で入力してください")
            )
    if not math.isfinite(raw.initial_cash) or raw.initial_cash <= 0:
        errors.append(
            ErrorItem(field="initial_cash", message="初期資金は1円以上で入力してください")
        )
    elif raw.initial_cash > MAX_INITIAL_CASH:
        errors.append(
            ErrorItem(field="initial_cash", message="初期資金は10億円以下で入力してください")
        )
    if errors:
        raise InputValidationError(errors)
    return MaCrossParams(
        short_window=int(raw.short_window),
        long_window=int(raw.long_window),
        # 画面とのやり取りは %。エンジンには割合を渡す(4.2)
        fee_rate=raw.fee_rate_pct / 100,
        slippage_rate=raw.slippage_rate_pct / 100,
        initial_cash=float(raw.initial_cash),
        lot_size=lot_size,
    )


def validate_period(
    start: dt.date | None,
    end: dt.date | None,
    available: DateRange,
    bars: list[DailyBar],
) -> ValidatedPeriod:
    """期間のチェック。省略された端は、その銘柄のデータの端にする(4.2)。"""
    start = start or available.first
    end = end or available.last
    if start > end:
        raise InputValidationError(
            [ErrorItem(field="start_date", message="開始日は終了日より前の日付にしてください")]
        )
    if start < available.first or end > available.last:
        raise InputValidationError(
            [
                ErrorItem(
                    field="start_date" if start < available.first else "end_date",
                    message=(
                        "指定した期間のデータがありません"
                        f"(取得可能:{available.first.isoformat()}〜{available.last.isoformat()})"
                    ),
                )
            ]
        )
    business_days = sum(1 for bar in bars if start <= bar.date <= end)
    if business_days < MIN_BUSINESS_DAYS:
        raise InputValidationError(
            [
                ErrorItem(
                    field="start_date",
                    message="期間が短すぎます。営業日が3日以上になるように指定してください",
                )
            ]
        )
    return ValidatedPeriod(start, end)
