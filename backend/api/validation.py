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

from backend.api.schemas import ErrorItem, MaCrossParamsIn, SweepCostsIn, SweepGridIn
from backend.marketdata.models import DailyBar, DateRange, MarketConfig
from backend.strategies import MA_CROSS_PARAMS, ParamSpec
from engine.reference import MaCrossParams
from engine.reference.sweep import GRID_FIELDS, SweepCosts, SweepGrid
from engine.reference.types import MAX_WINDOW

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


def _number_text(value: float) -> str:
    """1000.0 → "1000"、1e9 → "10億" のように、メッセージに入れる数値を短く書く。"""
    if value >= 1e8 and value % 1e8 == 0:
        return f"{int(value // 1e8)}億"
    return f"{int(value)}" if float(value).is_integer() else f"{value}"


def _exceeded_maximum(spec: ParamSpec, value: float) -> float | None:
    """上限を超えていれば、その上限を返す(上限がない・超えていないときは None)。"""
    if spec.maximum is None:
        return None
    over = value >= spec.maximum if spec.exclusive_maximum else value > spec.maximum
    return spec.maximum if over else None


def check_param(spec: ParamSpec, value: float) -> str | None:
    """1つのパラメータを ParamSpec の範囲で確かめる。誤りがあればメッセージ(仕様 4.3 の文)を返す。

    画面の入力チェック(frontend/lib/form.ts の checkSpec)と、同じ判定・同じ文にする。
    両方が同じ答えを返すことは tests/fixtures/param_messages.json で確かめている。
    """
    maximum = _exceeded_maximum(spec, value)
    if spec.kind == "integer":
        if not _is_whole(value) or value < spec.minimum:
            return f"日数は{_number_text(spec.minimum)}以上の整数で入力してください"
        if maximum is not None:
            return f"日数は{_number_text(maximum)}以下で入力してください"
        return None
    if spec.kind == "percent":
        if not math.isfinite(value) or value < spec.minimum:
            return f"手数料率とスリッページ率は{_number_text(spec.minimum)}以上で入力してください"
        if maximum is not None:
            bound = "未満" if spec.exclusive_maximum else "以下"
            return f"手数料率とスリッページ率は{_number_text(maximum)}%{bound}で入力してください"
        return None
    if spec.kind == "yen":
        if not math.isfinite(value) or value < spec.minimum:
            return f"初期資金は{_number_text(spec.minimum)}円以上で入力してください"
        if maximum is not None:
            return f"初期資金は{_number_text(maximum)}円以下で入力してください"
        return None
    raise ValueError(f"知らないパラメータの種類です: {spec.kind}")


def validate_params(raw: MaCrossParamsIn, market: MarketConfig) -> MaCrossParams:
    errors: list[ErrorItem] = []
    for spec in MA_CROSS_PARAMS:
        message = check_param(spec, getattr(raw, spec.key))
        if message:
            errors.append(ErrorItem(field=spec.key, message=message))
    windows_ok = not any(e.field in ("short_window", "long_window") for e in errors)
    if windows_ok and raw.short_window >= raw.long_window:
        # 移動平均クロスだけの決まり。画面と同じく、短期の欄に出す
        errors.insert(
            0,
            ErrorItem(field="short_window", message="短期の日数は長期の日数より小さくしてください"),
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


# --- 総当たり(docs/sweep.md 5章) -------------------------------------------------------

COST_KEYS = ("fee_rate_pct", "slippage_rate_pct", "initial_cash")


def validate_sweep_inputs(
    grid_in: SweepGridIn, costs_in: SweepCostsIn, market: MarketConfig, max_pairs: int
) -> tuple[SweepGrid, SweepCosts]:
    """格子と費用・資金のチェック。誤りはまとめて返す(欄ごと)。組み合わせの数の上限もここで確かめる。

    組み合わせがない・多すぎるときは、どの欄の誤りとも言えないので field="grid" にする。
    """
    errors: list[ErrorItem] = []
    for key in GRID_FIELDS:
        value = getattr(grid_in, key)
        if not _is_whole(value) or value < 1:
            errors.append(ErrorItem(field=key, message="日数と刻みは1以上の整数で入力してください"))
        elif value > MAX_WINDOW:
            errors.append(
                ErrorItem(field=key, message=f"日数と刻みは{MAX_WINDOW}以下で入力してください")
            )
    bad = {e.field for e in errors}
    for kind, label in (("short", "短期"), ("long", "長期")):
        lo, hi = f"{kind}_min", f"{kind}_max"
        if lo not in bad and hi not in bad and getattr(grid_in, lo) > getattr(grid_in, hi):
            errors.append(
                ErrorItem(field=lo, message=f"{label}の日数の範囲は、最小を最大以下にしてください")
            )
    grid: SweepGrid | None = None
    if not errors:
        grid = SweepGrid(*(int(getattr(grid_in, key)) for key in GRID_FIELDS))
        count = len(grid.pairs())
        if count == 0:
            errors.append(
                ErrorItem(
                    field="grid",
                    message="短期の日数が長期の日数より小さい組み合わせがありません。範囲を見直してください",
                )
            )
        elif count > max_pairs:
            errors.append(
                ErrorItem(
                    field="grid",
                    message=(
                        f"組み合わせが多すぎます({count:,}通り)。このエンジンでは{max_pairs:,}通りまでです。"
                        "範囲を狭めるか、刻みを大きくしてください"
                    ),
                )
            )
    for spec in MA_CROSS_PARAMS:
        if spec.key in COST_KEYS:
            message = check_param(spec, getattr(costs_in, spec.key))
            if message:
                errors.append(ErrorItem(field=spec.key, message=message))
    if errors:
        raise InputValidationError(errors)
    assert grid is not None
    return grid, SweepCosts(
        fee_rate=costs_in.fee_rate_pct / 100,
        slippage_rate=costs_in.slippage_rate_pct / 100,
        initial_cash=float(costs_in.initial_cash),
        lot_size=market.lot_size,
        trading_days_per_year=market.trading_days_per_year,
    )


def validate_holdout(
    holdout: dt.date | None, period: ValidatedPeriod, bars: list[DailyBar]
) -> dt.date | None:
    """検証期間の開始日のチェック(docs/sweep.md 3章・5章)。期間のチェック(validate_period)のあとに呼ぶ。"""
    if holdout is None:
        return None
    field = "holdout_start_date"
    if not period.start < holdout <= period.end:
        raise InputValidationError(
            [
                ErrorItem(
                    field=field,
                    message="検証期間の開始日は、期間の開始日より後、終了日以前の日付にしてください",
                )
            ]
        )
    in_sample = sum(1 for bar in bars if period.start <= bar.date < holdout)
    if in_sample < MIN_BUSINESS_DAYS:
        raise InputValidationError(
            [
                ErrorItem(
                    field=field,
                    message="選ぶ期間(検証期間より前)の営業日が3日未満です。検証期間の開始日を遅くしてください",
                )
            ]
        )
    out_of_sample = sum(1 for bar in bars if holdout <= bar.date <= period.end)
    if out_of_sample < MIN_BUSINESS_DAYS:
        raise InputValidationError(
            [
                ErrorItem(
                    field=field,
                    message="検証期間の営業日が3日未満です。検証期間の開始日を早くしてください",
                )
            ]
        )
    return holdout
