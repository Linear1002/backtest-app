"""バックテストの入力チェック(docs/mvp.md 4.3)。

- パラメータの誤りは、まとめて返す(1つ直すたびに次のエラーが出ると使いにくいため)
- 期間のチェックはデータを読んでから行うので、パラメータに誤りがあるときは、そこまで進まない
- 範囲の数値は backend/strategies.py の ParamSpec が正(画面の入力チェックも同じ定義を使う)
- メッセージは仕様の表のとおり
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from backend.api.schemas import ErrorItem, MaCrossParamsIn
from backend.marketdata.models import DailyBar, DateRange, MarketConfig
from backend.strategies import MA_CROSS_PARAMS, ParamSpec
from engine.reference import MaCrossParams

MIN_BUSINESS_DAYS = 3

SPECS: dict[str, ParamSpec] = {spec.key: spec for spec in MA_CROSS_PARAMS}


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


def _number_text(value: float) -> str:
    """1000.0 → "1000"、1e9 → "10億" のように、メッセージに入れる数値を短く書く。"""
    if value >= 1e8 and value % 1e8 == 0:
        return f"{int(value // 1e8)}億"
    return f"{int(value)}" if float(value).is_integer() else f"{value}"


def _check_window(key: str, value: float) -> str | None:
    spec = SPECS[key]
    if not _is_whole(value) or value < spec.minimum:
        return f"日数は{_number_text(spec.minimum)}以上の整数で入力してください"
    if spec.maximum is not None and value > spec.maximum:
        return f"日数は{_number_text(spec.maximum)}以下で入力してください"
    return None


def _check_rate(key: str, value: float) -> str | None:
    spec = SPECS[key]
    if not math.isfinite(value) or value < spec.minimum:
        return f"手数料率とスリッページ率は{_number_text(spec.minimum)}以上で入力してください"
    if spec.maximum is not None and (
        value >= spec.maximum if spec.exclusive_maximum else value > spec.maximum
    ):
        return f"手数料率とスリッページ率は{_number_text(spec.maximum)}%未満で入力してください"
    return None


def _check_cash(value: float) -> str | None:
    spec = SPECS["initial_cash"]
    if not math.isfinite(value) or value < spec.minimum:
        return f"初期資金は{_number_text(spec.minimum)}円以上で入力してください"
    if spec.maximum is not None and value > spec.maximum:
        return f"初期資金は{_number_text(spec.maximum)}円以下で入力してください"
    return None


def validate_params(raw: MaCrossParamsIn, market: MarketConfig) -> MaCrossParams:
    errors: list[ErrorItem] = []
    windows_ok = True
    for key in ("short_window", "long_window"):
        message = _check_window(key, getattr(raw, key))
        if message:
            errors.append(ErrorItem(field=key, message=message))
            windows_ok = False
    if windows_ok and raw.short_window >= raw.long_window:
        errors.append(
            ErrorItem(field="short_window", message="短期の日数は長期の日数より小さくしてください")
        )
    for key in ("fee_rate_pct", "slippage_rate_pct"):
        message = _check_rate(key, getattr(raw, key))
        if message:
            errors.append(ErrorItem(field=key, message=message))
    message = _check_cash(raw.initial_cash)
    if message:
        errors.append(ErrorItem(field="initial_cash", message=message))
    if errors:
        raise InputValidationError(errors)
    return MaCrossParams(
        short_window=int(raw.short_window),
        long_window=int(raw.long_window),
        # 画面とのやり取りは %。エンジンには割合を渡す(4.2)
        fee_rate=raw.fee_rate_pct / 100,
        slippage_rate=raw.slippage_rate_pct / 100,
        initial_cash=float(raw.initial_cash),
        lot_size=market.lot_size,
        trading_days_per_year=market.trading_days_per_year,
    )


def validate_period(
    start: dt.date | None,
    end: dt.date | None,
    available: DateRange,
    bars: list[DailyBar],
) -> ValidatedPeriod:
    """期間のチェック。省略された端は、その銘柄のデータの端にする(4.2)。

    データの範囲のチェックはここ(API)だけで行う。計算エンジンは銘柄本来の範囲を知らないため(4.3)。
    """
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
