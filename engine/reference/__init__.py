"""Python リファレンス実装(CLAUDE.md の「正しさの基準」1)。

C++ 版・CUDA 版は、このリファレンスと結果が一致することをテストで確かめる。
仕様は docs/mvp.md。各ファイルの役割:

- types.py       入力(Bar・MaCrossParams)と出力(BacktestResult など)の型
- indicators.py  時点 t 基準の調整済み終値、移動平均の和、クロス判定の値 D(t)
- ratio.py       調整係数から分割比率 p/q を戻す
- metrics.py     成績表の指標
- backtest.py    1日の処理の順番(分割→約定→評価→シグナル)と全体の流れ
- sweep.py       総当たり(移動平均の日数の組み合わせをすべて試す。docs/sweep.md)
"""

from engine.reference.backtest import run_backtest, select_load_range
from engine.reference.types import (
    BacktestResult,
    Bar,
    EngineDataError,
    EngineInputError,
    MaCrossParams,
)

__all__ = [
    "BacktestResult",
    "Bar",
    "EngineDataError",
    "EngineInputError",
    "MaCrossParams",
    "run_backtest",
    "select_load_range",
]
