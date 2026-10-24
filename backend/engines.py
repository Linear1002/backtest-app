"""計算エンジンの切り替え口。

- python:Python リファレンス実装(engine/reference)。いつでも使える「正解」
- cpp:開発者が書く C++ CPU 版(engine/cpp)を pybind11 でつないだもの。ビルドされるまでは使えない

C++ 版の Python モジュール名と、返す値の形は docs/cpp/contract.md の「pybind11 から呼ぶとき」に決めてある。
ここではその形を受け取り、リファレンス実装と同じ BacktestResult に変換する。
"""

from __future__ import annotations

import datetime as dt
import importlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from engine.reference import (
    BacktestResult,
    Bar,
    EngineDataError,
    EngineInputError,
    MaCrossParams,
    run_backtest,
)
from engine.reference.metrics import compute_metrics
from engine.reference.types import (
    CorporateActionEvent,
    DailyRecord,
    Fill,
    Metrics,
    Notes,
    Signal,
    SkippedOrder,
    Trade,
    WarmupInfo,
)

CPP_MODULE_NAME = "backtest_cpp"

logger = logging.getLogger("backend.engines")


class EngineUnavailableError(RuntimeError):
    """指定したエンジンが使えない(C++ 版がまだビルドされていない など)。"""


@dataclass(frozen=True)
class EngineInfo:
    id: str
    label: str
    available: bool
    note: str


RunFunction = Callable[[Sequence[Bar], dt.date, dt.date, MaCrossParams], BacktestResult]


NOT_BUILT = "まだビルドされていません(docs/cpp/README.md)"
LOAD_FAILED = (
    "ビルドされていますが、読み込めませんでした(Python のバージョン違い・足りないライブラリなど)。"
    "API サーバーのターミナルに出ているエラーを確認してください"
)


def _load_cpp_module() -> tuple[Any | None, str]:
    """C++ 版のモジュールと、使えないときの理由。

    - まだビルドされていない(モジュールそのものが見つからない):ふつうの状態
    - ビルドはされているが読み込めない(依存ライブラリがない・Python のバージョン違いなど):詳しい中身はログに出す
    """
    try:
        return importlib.import_module(CPP_MODULE_NAME), "ビルド済み"
    except ModuleNotFoundError as error:
        if error.name == CPP_MODULE_NAME:
            return None, NOT_BUILT
        logger.exception("C++ 版のモジュール %s を読み込めませんでした", CPP_MODULE_NAME)
        return None, LOAD_FAILED
    except ImportError:
        logger.exception("C++ 版のモジュール %s を読み込めませんでした", CPP_MODULE_NAME)
        return None, LOAD_FAILED


def list_engines() -> list[EngineInfo]:
    cpp, note = _load_cpp_module()
    return [
        EngineInfo("python", "Python リファレンス実装", True, "仕様どおりに計算する正解の実装"),
        EngineInfo("cpp", "C++ CPU 版", cpp is not None, note),
    ]


# --- 総当たり(docs/sweep.md)に使うエンジン -------------------------------------------

PYTHON_SWEEP_MAX_PAIRS = 2_000  # docs/sweep.md 9章
FAST_SWEEP_MAX_PAIRS = 20_000


@dataclass(frozen=True)
class SweepEngineInfo:
    id: str
    label: str
    available: bool
    note: str
    max_pairs: int


def list_sweep_engines(workers: int) -> list[SweepEngineInfo]:
    """総当たりに使えるエンジン。C++ 版・CUDA 版の総当たりは、開発者が書いたらここでつなぐ(docs/gpu-plan.md)。"""
    return [
        SweepEngineInfo(
            "python",
            "Python リファレンス実装",
            True,
            f"{workers}個のプロセスで並列に計算します。1つの組み合わせに数十ミリ秒かかります",
            PYTHON_SWEEP_MAX_PAIRS,
        ),
        SweepEngineInfo(
            "cpp",
            "C++ CPU 版",
            False,
            "まだありません(docs/gpu-plan.md の G2)",
            FAST_SWEEP_MAX_PAIRS,
        ),
        SweepEngineInfo(
            "cuda",
            "CUDA 版(GPU)",
            False,
            "まだありません(docs/gpu-plan.md の G3〜G6)",
            FAST_SWEEP_MAX_PAIRS,
        ),
    ]


def get_sweep_engine(engine_id: str, workers: int) -> SweepEngineInfo:
    """総当たりに使うエンジン。知らない・使えないエンジンなら EngineUnavailableError。"""
    for engine in list_sweep_engines(workers):
        if engine.id == engine_id:
            if not engine.available:
                raise EngineUnavailableError(
                    f"総当たりでは {engine.label} はまだ使えません。{engine.note}"
                )
            return engine
    raise EngineUnavailableError(f"知らないエンジンです: {engine_id}")


def get_engine(engine_id: str) -> RunFunction:
    if engine_id == "python":
        return run_backtest
    if engine_id == "cpp":
        module, note = _load_cpp_module()
        if module is None:
            raise EngineUnavailableError(f"C++ 版のエンジンは使えません。{note}")
        return lambda bars, start, end, params: run_cpp(module, bars, start, end, params)
    raise EngineUnavailableError(f"知らないエンジンです: {engine_id}")


# --- C++ 版の結果を BacktestResult に変換する ---------------------------------------


def _date(value: str | None) -> dt.date | None:
    return None if value in (None, "") else dt.date.fromisoformat(value)


def run_cpp(
    module: Any, bars: Sequence[Bar], start: dt.date, end: dt.date, params: MaCrossParams
) -> BacktestResult:
    """pybind11 モジュールの run_ma_cross を呼び、結果を BacktestResult に変換する。

    C++ 側の InputError / DataError は、リファレンスと同じ EngineInputError / EngineDataError に読み替える。
    """
    input_error = getattr(module, "InputError", None)
    data_error = getattr(module, "DataError", None)
    try:
        raw = _call_cpp(module, bars, start, end, params)
    except Exception as error:
        if input_error is not None and isinstance(error, input_error):
            raise EngineInputError(str(error)) from None
        if data_error is not None and isinstance(error, data_error):
            raise EngineDataError(str(error)) from None
        raise
    return convert_cpp_result(raw, start, end, params)


def _call_cpp(
    module: Any, bars: Sequence[Bar], start: dt.date, end: dt.date, params: MaCrossParams
) -> dict[str, Any]:
    return module.run_ma_cross(
        [
            (
                bar.date.isoformat(),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.adj_factor,
                bar.ex_rt,
            )
            for bar in bars
        ],
        start.isoformat(),
        end.isoformat(),
        {
            "short_window": params.short_window,
            "long_window": params.long_window,
            "fee_rate": params.fee_rate,
            "slippage_rate": params.slippage_rate,
            "initial_cash": params.initial_cash,
            "lot_size": params.lot_size,
            "trading_days_per_year": params.trading_days_per_year,
        },
    )


def convert_cpp_result(
    raw: dict[str, Any], start: dt.date, end: dt.date, params: MaCrossParams
) -> BacktestResult:
    daily = tuple(
        DailyRecord(
            date=dt.date.fromisoformat(r["date"]),
            close=r["close"],
            short_ma=r["short_ma"],
            long_ma=r["long_ma"],
            cash=r["cash"],
            shares=int(r["shares"]),
            valuation_price=r["valuation_price"],
            equity=r["equity"],
        )
        for r in raw["daily"]
    )
    signals = tuple(
        Signal(dt.date.fromisoformat(s["date"]), s["side"], s["action"]) for s in raw["signals"]
    )
    fills = tuple(
        Fill(
            date=dt.date.fromisoformat(f["date"]),
            signal_date=dt.date.fromisoformat(f["signal_date"]),
            side=f["side"],
            open_price=f["open_price"],
            fill_price=f["fill_price"],
            shares=int(f["shares"]),
            notional=f["notional"],
            fee=f["fee"],
            cash_after=f["cash_after"],
        )
        for f in raw["fills"]
    )
    skipped = tuple(
        SkippedOrder(
            date=dt.date.fromisoformat(s["date"]),
            signal_date=dt.date.fromisoformat(s["signal_date"]),
            open_price=s["open_price"],
            fill_price=s["fill_price"],
            cash=s["cash"],
        )
        for s in raw["skipped_orders"]
    )
    events = tuple(
        CorporateActionEvent(
            date=dt.date.fromisoformat(e["date"]),
            ex_rt=int(e["ex_rt"]),
            adj_factor=e["adj_factor"],
            ratio_numerator=int(e["p"]),
            ratio_denominator=int(e["q"]),
            shares_before=int(e["shares_before"]),
            shares_after=int(e["shares_after"]),
            fraction_shares=e["fraction_shares"],
            fraction_cash=e["fraction_cash"],
            closed_position=bool(e["closed_position"]),
        )
        for e in raw["events"]
    )
    trades = tuple(
        Trade(
            entry_date=dt.date.fromisoformat(t["entry_date"]),
            entry_price=t["entry_price"],
            entry_shares=int(t["entry_shares"]),
            buy_cost=t["buy_cost"],
            exit_date=_date(t.get("exit_date")),
            exit_price=t.get("exit_price"),
            exit_shares=None if t.get("exit_shares") is None else int(t["exit_shares"]),
            sell_proceeds=t.get("sell_proceeds"),
            fraction_cash=t["fraction_cash"],
            pnl=t.get("pnl"),
            closed_by=t.get("closed_by"),
        )
        for t in raw["trades"]
    )
    w = raw["warmup"]
    warmup = WarmupInfo(
        first_date=_date(w.get("first_date")),
        last_date=_date(w.get("last_date")),
        valid_days=int(w["valid_days"]),
        sufficient=bool(w["sufficient"]),
        signals_unavailable_until=_date(w.get("signals_unavailable_until")),
    )
    # 指標は C++ 版が返した値を使う(一致テストは docs/cpp/contract.md の基準で別に行う)
    m = raw.get("metrics")
    metrics = (
        compute_metrics(
            [d.equity for d in daily], params.initial_cash, trades, params.trading_days_per_year
        )
        if m is None
        else _metrics_from_raw(m)
    )
    return BacktestResult(
        params=params,
        start=start,
        end=end,
        daily=daily,
        signals=signals,
        fills=fills,
        skipped_orders=skipped,
        events=events,
        trades=trades,
        metrics=metrics,
        warmup=warmup,
        notes=Notes(
            open_position_at_end=daily[-1].shares > 0,
            annualized_is_reference=metrics.return_count < params.trading_days_per_year,
        ),
    )


def _metrics_from_raw(m: dict[str, Any]) -> Metrics:
    return Metrics(
        total_return=m["total_return"],
        annualized_return=m.get("annualized_return"),
        max_drawdown=m["max_drawdown"],
        sharpe_ratio=m.get("sharpe_ratio"),
        win_rate=m.get("win_rate"),
        trade_count=int(m["trade_count"]),
        winning_trades=int(m["winning_trades"]),
        return_count=int(m["return_count"]),
    )
