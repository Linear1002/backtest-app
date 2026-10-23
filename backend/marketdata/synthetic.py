"""架空データ(デモ用)のデータソース。

実在の銘柄・株価ではない「本物っぽい架空の株価」を、決まった乱数の種から毎回同じように作る。
目的は3つ:
- APIキーがなくても、アプリ全体をすぐ動かせるようにする
- 公開デモに使える(J-Quants のデータは私的使用のみで、公開できないため。docs/mvp.md 3.2)
- 分割・併合・株主割当増資・売買停止・資金不足など、仕様の境界ケースを画面で確かめられるようにする

銘柄は「DEMO:」市場に置き、名前に必ず「(架空)」を付けて、実在の銘柄と混同しないようにする。
"""

from __future__ import annotations

import datetime as dt
import math
import random
from dataclasses import dataclass, field
from functools import cache, lru_cache

from backend.marketdata.models import (
    DailyBar,
    DataInfo,
    DateRange,
    SymbolId,
    SymbolInfo,
)
from backend.marketdata.source import SymbolNotFoundError, filter_bars

SOURCE_ID = "demo"
SOURCE_LABEL = "架空データ(デモ用)"
LICENSE_NOTE = "実在の銘柄・株価ではありません。動作確認とデモのための架空データです。"

# 架空市場のデータ期間
CALENDAR_START = dt.date(2022, 1, 4)
CALENDAR_END = dt.date(2026, 7, 31)

TRADING_DAYS_PER_YEAR = 245


# --- 取引カレンダー ------------------------------------------------------------------


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """year 年 month 月の第 n 週の weekday 曜日(月曜=0)。"""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def _holidays(year: int) -> set[dt.date]:
    """架空市場の休場日。日本の祝日に近い日を休みにする(春分・秋分は固定日で近似)。"""
    # 年末年始の休場日(祝日ではないので、振替休日の対象にしない)
    year_end = {
        dt.date(year, 1, 2),
        dt.date(year, 1, 3),
        dt.date(year, 12, 31),
    }
    # 日付が決まっている祝日
    fixed = {
        dt.date(year, 1, 1),
        dt.date(year, 2, 11),
        dt.date(year, 2, 23),
        dt.date(year, 3, 20),
        dt.date(year, 4, 29),
        dt.date(year, 5, 3),
        dt.date(year, 5, 4),
        dt.date(year, 5, 5),
        dt.date(year, 8, 11),
        dt.date(year, 9, 23),
        dt.date(year, 11, 3),
        dt.date(year, 11, 23),
    }
    happy_mondays = {
        _nth_weekday(year, 1, 0, 2),  # 成人の日
        _nth_weekday(year, 7, 0, 3),  # 海の日
        _nth_weekday(year, 9, 0, 3),  # 敬老の日
        _nth_weekday(year, 10, 0, 2),  # スポーツの日
    }
    holidays = year_end | fixed | happy_mondays
    # 日曜日の祝日は、次の平日(祝日でない日)を振替休日にする
    for day in sorted(fixed):
        if day.weekday() == 6:
            substitute = day + dt.timedelta(days=1)
            while substitute in fixed | happy_mondays:
                substitute += dt.timedelta(days=1)
            holidays.add(substitute)
    return holidays


@lru_cache(maxsize=1)
def business_days() -> tuple[dt.date, ...]:
    """架空市場の営業日(土日と休場日を除く)。"""
    holidays: set[dt.date] = set()
    for year in range(CALENDAR_START.year, CALENDAR_END.year + 1):
        holidays |= _holidays(year)
    days = []
    day = CALENDAR_START
    while day <= CALENDAR_END:
        if day.weekday() < 5 and day not in holidays:
            days.append(day)
        day += dt.timedelta(days=1)
    return tuple(days)


# --- 銘柄の設定 ----------------------------------------------------------------------


@dataclass(frozen=True)
class Regime:
    """ある日以降の値動きの性質(年率のドリフトとボラティリティ)。"""

    start: dt.date
    drift: float
    volatility: float


@dataclass(frozen=True)
class CorporateAction:
    """権利落ち。ex_rt は 1:分割 2:併合 3:株主割当増資。"""

    date: dt.date
    ex_rt: int
    adj_factor: float


@dataclass(frozen=True)
class DemoSymbol:
    code: str
    name: str
    sector: str
    description: str  # どんな境界ケースを確かめるための銘柄か
    seed: int
    start_price: float
    regimes: tuple[Regime, ...]
    base_volume: float = 300_000
    listed_from: dt.date = CALENDAR_START
    actions: tuple[CorporateAction, ...] = ()
    halted: tuple[dt.date, ...] = field(default=())


def _d(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


DEMO_SYMBOLS: tuple[DemoSymbol, ...] = (
    DemoSymbol(
        code="1001",
        name="ほしぞら精機(架空)",
        sector="精密機器",
        description="ゆるやかな上昇トレンド。分割などはなし",
        seed=1001,
        start_price=1850,
        regimes=(Regime(CALENDAR_START, 0.18, 0.22),),
    ),
    DemoSymbol(
        code="1002",
        name="こもれび食品(架空)",
        sector="食料品",
        description="横ばいで、だましのクロスが多い",
        seed=1002,
        start_price=2400,
        regimes=(Regime(CALENDAR_START, 0.0, 0.17),),
    ),
    DemoSymbol(
        code="1003",
        name="ゆうなぎ電子(架空)",
        sector="電気機器",
        description="1:2 の株式分割(2025-04-01)",
        seed=1003,
        start_price=4200,
        regimes=(
            Regime(CALENDAR_START, 0.10, 0.28),
            Regime(_d("2024-10-01"), 0.35, 0.30),
        ),
        actions=(CorporateAction(_d("2025-04-01"), 1, 0.5),),
    ),
    DemoSymbol(
        code="1004",
        name="あさつゆ化学(架空)",
        sector="化学",
        description="1:3 の株式分割(2024-10-01)。調整係数は小数第6位までの近似値",
        seed=1004,
        start_price=6900,
        regimes=(Regime(CALENDAR_START, 0.06, 0.24),),
        actions=(CorporateAction(_d("2024-10-01"), 1, 0.333333),),
    ),
    DemoSymbol(
        code="1005",
        name="つむぎ運輸(架空)",
        sector="陸運業",
        description="2:3 の株式分割(2025-07-01)。持ち株が1.5倍になる",
        seed=1005,
        start_price=3300,
        regimes=(Regime(CALENDAR_START, 0.08, 0.20),),
        actions=(CorporateAction(_d("2025-07-01"), 1, 0.666667),),
    ),
    DemoSymbol(
        code="1006",
        name="かざぐるま重工(架空)",
        sector="機械",
        description="10:1 の株式併合(2025-01-06)。価格が10倍になる",
        seed=1006,
        start_price=180,
        regimes=(Regime(CALENDAR_START, 0.05, 0.35),),
        base_volume=3_000_000,
        actions=(CorporateAction(_d("2025-01-06"), 2, 10.0),),
    ),
    DemoSymbol(
        code="1007",
        name="せせらぎ銀行(架空)",
        sector="銀行業",
        description="株主割当増資(2025-06-02、調整係数0.97)",
        seed=1007,
        start_price=1250,
        regimes=(Regime(CALENDAR_START, 0.07, 0.19),),
        actions=(CorporateAction(_d("2025-06-02"), 3, 0.97),),
    ),
    DemoSymbol(
        code="1008",
        name="しずく製薬(架空)",
        sector="医薬品",
        description="売買停止の日がある(停止中の2025-03-12に1:2の分割)",
        seed=1008,
        start_price=5200,
        regimes=(Regime(CALENDAR_START, 0.12, 0.26),),
        actions=(CorporateAction(_d("2025-03-12"), 1, 0.5),),
        halted=(
            _d("2024-06-14"),
            _d("2025-03-10"),
            _d("2025-03-11"),
            _d("2025-03-12"),
            _d("2025-03-13"),
            _d("2025-03-14"),
            _d("2025-11-21"),
        ),
    ),
    DemoSymbol(
        code="1009",
        name="あまのがわ通信(架空)",
        sector="情報・通信業",
        description="株価が高く、初期資金100万円では100株を買えない(資金不足のスキップ)",
        seed=1009,
        start_price=26500,
        regimes=(Regime(CALENDAR_START, 0.09, 0.23),),
        base_volume=40_000,
    ),
    DemoSymbol(
        code="1010",
        name="ゆきどけ不動産(架空)",
        sector="不動産業",
        description="下落トレンド",
        seed=1010,
        start_price=3100,
        regimes=(Regime(CALENDAR_START, -0.16, 0.25),),
    ),
    DemoSymbol(
        code="1011",
        name="はなび小売(架空)",
        sector="小売業",
        description="値動きが大きく、2024年夏に急落して回復する",
        seed=1011,
        start_price=1500,
        regimes=(
            Regime(CALENDAR_START, 0.20, 0.30),
            Regime(_d("2024-07-01"), -1.60, 0.55),
            Regime(_d("2024-09-02"), 0.45, 0.40),
        ),
        base_volume=900_000,
    ),
    DemoSymbol(
        code="1012",
        name="わたぐもエネルギー(架空)",
        sector="電気・ガス業",
        description="2025-04-01 に上場。それより前のデータがない",
        seed=1012,
        start_price=980,
        regimes=(Regime(CALENDAR_START, 0.15, 0.32),),
        listed_from=_d("2025-04-01"),
    ),
)

_SYMBOLS_BY_CODE = {symbol.code: symbol for symbol in DEMO_SYMBOLS}


# --- 価格の生成 ----------------------------------------------------------------------


def _tick_size(price: float) -> float:
    """呼値の単位(架空市場の簡略版)。"""
    if price < 3_000:
        return 1.0
    if price < 5_000:
        return 5.0
    if price < 30_000:
        return 10.0
    if price < 50_000:
        return 50.0
    return 100.0


def _round_to_tick(price: float) -> float:
    tick = _tick_size(price)
    return max(tick, round(price / tick) * tick)


class _Normal:
    """標準正規乱数(Box-Muller 法)。random.random() だけを使うので、Python のバージョンが変わっても同じ列になる。"""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self._spare: float | None = None

    def uniform(self) -> float:
        return self._rng.random()

    def __call__(self) -> float:
        if self._spare is not None:
            value, self._spare = self._spare, None
            return value
        u1 = 1.0 - self._rng.random()  # (0, 1]
        u2 = self._rng.random()
        radius = math.sqrt(-2.0 * math.log(u1))
        self._spare = radius * math.sin(2.0 * math.pi * u2)
        return radius * math.cos(2.0 * math.pi * u2)


def _regime_for(symbol: DemoSymbol, day: dt.date) -> Regime:
    current = symbol.regimes[0]
    for regime in symbol.regimes:
        if regime.start <= day:
            current = regime
    return current


@cache
def generate_bars(code: str) -> tuple[DailyBar, ...]:
    """架空銘柄の日足をすべて作る。同じ code なら毎回同じ結果になる。"""
    symbol = _SYMBOLS_BY_CODE.get(code)
    if symbol is None:
        raise SymbolNotFoundError(f"架空データに銘柄 DEMO:{code} はありません")

    normal = _Normal(symbol.seed)
    actions = {action.date: action for action in symbol.actions}
    halted = set(symbol.halted)
    days = [day for day in business_days() if day >= symbol.listed_from]

    bars: list[DailyBar] = []
    economic_close = symbol.start_price  # 調整後の「経済的な」価格(分割の影響を受けない)
    cumulative_factor = 1.0  # これまでの権利落ちの調整係数の積
    for index, day in enumerate(days):
        regime = _regime_for(symbol, day)
        daily_vol = regime.volatility / math.sqrt(TRADING_DAYS_PER_YEAR)
        daily_drift = (regime.drift - 0.5 * regime.volatility**2) / TRADING_DAYS_PER_YEAR

        action = actions.get(day)
        if action is not None:
            # 権利落ち日から、未調整の価格に調整係数が掛かる(1:2 分割なら価格が半分になる)
            cumulative_factor *= action.adj_factor

        # 乱数は売買停止の日も同じ数だけ引く(停止の有無で他の日の値が変わらないように)
        gap = normal() * daily_vol * 0.35
        body = normal() * daily_vol
        wick_up = abs(normal()) * daily_vol * 0.45
        wick_down = abs(normal()) * daily_vol * 0.45
        volume_noise = normal() * 0.35

        previous_close = economic_close
        economic_open = previous_close * math.exp(gap) if index > 0 else previous_close
        economic_close = previous_close * math.exp(daily_drift + body)

        if day in halted:
            bars.append(
                DailyBar(
                    date=day,
                    open=None,
                    high=None,
                    low=None,
                    close=None,
                    volume=None,
                    turnover=None,
                    adj_factor=action.adj_factor if action else 1.0,
                    ex_rt=action.ex_rt if action else None,
                )
            )
            continue

        open_price = _round_to_tick(economic_open * cumulative_factor)
        close_price = _round_to_tick(economic_close * cumulative_factor)
        high_price = _round_to_tick(
            max(economic_open, economic_close) * math.exp(wick_up) * cumulative_factor
        )
        low_price = _round_to_tick(
            min(economic_open, economic_close) * math.exp(-wick_down) * cumulative_factor
        )
        high_price = max(high_price, open_price, close_price)
        low_price = min(low_price, open_price, close_price)
        # 分割で株数が増えると出来高も増える
        volume = float(
            round(symbol.base_volume * math.exp(volume_noise) / cumulative_factor / 100) * 100
        )
        volume = max(volume, 100.0)

        bars.append(
            DailyBar(
                date=day,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                turnover=close_price * volume,
                adj_factor=action.adj_factor if action else 1.0,
                ex_rt=action.ex_rt if action else None,
            )
        )
    return tuple(bars)


# --- データソース --------------------------------------------------------------------


class DemoDataSource:
    """架空データのデータソース。ネットワークもAPIキーも使わない。"""

    source_id = SOURCE_ID
    source_label = SOURCE_LABEL
    markets = ("DEMO",)

    def list_symbols(self) -> list[SymbolInfo]:
        return [
            SymbolInfo(
                symbol_id=SymbolId("DEMO", symbol.code),
                name=symbol.name,
                segment="デモ",
                sector=symbol.sector,
            )
            for symbol in DEMO_SYMBOLS
        ]

    def describe(self, symbol_id: SymbolId) -> str:
        """その架空銘柄で確かめられる境界ケースの説明。"""
        return self._symbol(symbol_id).description

    def get_daily_bars(
        self,
        symbol_id: SymbolId,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[DailyBar]:
        self._symbol(symbol_id)
        return filter_bars(list(generate_bars(symbol_id.code)), start, end)

    def get_available_range(self, symbol_id: SymbolId) -> DateRange:
        bars = generate_bars(self._symbol(symbol_id).code)
        return DateRange(bars[0].date, bars[-1].date)

    def get_data_info(self, symbol_id: SymbolId) -> DataInfo:
        self._symbol(symbol_id)
        return DataInfo(
            source_id=SOURCE_ID,
            source_label=SOURCE_LABEL,
            license_note=LICENSE_NOTE,
            fetched_at=None,
        )

    @staticmethod
    def _symbol(symbol_id: SymbolId) -> DemoSymbol:
        if symbol_id.market != "DEMO" or symbol_id.code not in _SYMBOLS_BY_CODE:
            raise SymbolNotFoundError(f"架空データに銘柄 {symbol_id} はありません")
        return _SYMBOLS_BY_CODE[symbol_id.code]
