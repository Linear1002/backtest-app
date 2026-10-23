"""画面に出す戦略の一覧と、パラメータの定義(既定値・範囲・説明)。

MVP で実際に計算できるのは移動平均クロスだけ。ほかは「今後追加予定」として一覧にだけ出す。
既定値と範囲は docs/mvp.md 4.2・4.3 に合わせる。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    kind: str  # "integer" / "percent" / "yen"
    default: float
    minimum: float
    maximum: float | None
    step: float
    help: str
    exclusive_maximum: bool = False


@dataclass(frozen=True)
class StrategySpec:
    id: str
    name: str
    summary: str
    description: str
    available: bool
    params: tuple[ParamSpec, ...] = ()


MA_CROSS_PARAMS = (
    ParamSpec(
        key="short_window",
        label="短期移動平均の日数",
        kind="integer",
        default=5,
        minimum=1,
        maximum=None,
        step=1,
        help="直近何営業日の終値で短期線を作るか。長期の日数より小さくする",
    ),
    ParamSpec(
        key="long_window",
        label="長期移動平均の日数",
        kind="integer",
        default=25,
        minimum=2,
        maximum=None,
        step=1,
        help="直近何営業日の終値で長期線を作るか",
    ),
    ParamSpec(
        key="fee_rate_pct",
        label="手数料率",
        kind="percent",
        default=0.1,
        minimum=0,
        maximum=10,
        step=0.01,
        help="約定代金に対する割合。売りと買いの両方にかかる",
        exclusive_maximum=True,
    ),
    ParamSpec(
        key="slippage_rate_pct",
        label="スリッページ率",
        kind="percent",
        default=0.05,
        minimum=0,
        maximum=10,
        step=0.01,
        help="始値からどれだけ不利な価格で約定するとみなすか。買いは高く、売りは安くなる",
        exclusive_maximum=True,
    ),
    ParamSpec(
        key="initial_cash",
        label="初期資金",
        kind="yen",
        default=1_000_000,
        minimum=1,
        maximum=1_000_000_000,
        step=10_000,
        help="最初に持っている現金。1円以上、10億円以下",
    ),
)

STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec(
        id="ma_cross",
        name="移動平均クロス",
        summary="短期線が長期線を上に抜けたら買い、下に抜けたら売る",
        description=(
            "当日の終値で、短期移動平均が長期移動平均を上抜けたら翌営業日の始値で買い、"
            "下抜けたら翌営業日の始値で全株を売ります。買いのみ(空売りはしません)。"
            "移動平均は、分割などの影響をその日までに分かる情報だけで調整した終値で計算します。"
        ),
        available=True,
        params=MA_CROSS_PARAMS,
    ),
    StrategySpec(
        id="rsi_reversal",
        name="RSI 逆張り",
        summary="売られすぎで買い、買われすぎで売る",
        description="今後追加予定です。",
        available=False,
    ),
    StrategySpec(
        id="bollinger_breakout",
        name="ボリンジャーバンド・ブレイクアウト",
        summary="バンドを上に抜けたら買う",
        description="今後追加予定です。",
        available=False,
    ),
    StrategySpec(
        id="momentum",
        name="モメンタム(過去リターン順)",
        summary="過去の値上がりが大きい銘柄を持つ",
        description="今後追加予定です(複数銘柄の同時実行が必要)。",
        available=False,
    ),
)

STRATEGIES_BY_ID = {strategy.id: strategy for strategy in STRATEGIES}
