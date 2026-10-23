"""移動平均クロス戦略のバックテスト(docs/mvp.md 2章・5章)。

このファイルが「正解」(CLAUDE.md の正しさの基準1)。速さより、仕様と1対1で対応して読みやすいことを優先している。
各処理の上に、対応する仕様の節番号を書いてある。
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass

from engine.reference.indicators import CrossState, compute_cross_states, detect_cross
from engine.reference.metrics import compute_metrics
from engine.reference.ratio import recover_split_ratio
from engine.reference.types import (
    TRADING_DAYS_PER_YEAR,
    BacktestResult,
    Bar,
    CorporateActionEvent,
    DailyRecord,
    EngineDataError,
    EngineInputError,
    Fill,
    MaCrossParams,
    Notes,
    Side,
    Signal,
    SkippedOrder,
    Trade,
    WarmupInfo,
)

MIN_PERIOD_BUSINESS_DAYS = 3  # 4.3
MAX_RATE = 0.1  # 手数料率・スリッページ率は 10% 未満(4.3)
MAX_INITIAL_CASH = 1_000_000_000  # 10億円(4.3)

SPLIT_OR_MERGER = (1, 2)  # ExRT: 1 分割、2 併合
KNOWN_EX_RT = (1, 2, 3)  # 3 は株主割当増資


# --- 入力チェック --------------------------------------------------------------------


def validate_params(params: MaCrossParams) -> None:
    """4.3 の入力チェックのうち、パラメータに関するもの。"""
    for value in (params.short_window, params.long_window):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise EngineInputError("日数は1以上の整数で入力してください")
    if params.short_window >= params.long_window:
        raise EngineInputError("短期の日数は長期の日数より小さくしてください")
    for rate in (params.fee_rate, params.slippage_rate):
        if not math.isfinite(rate) or rate < 0:
            raise EngineInputError("手数料率とスリッページ率は0以上で入力してください")
        if rate >= MAX_RATE:
            raise EngineInputError("手数料率とスリッページ率は10%未満で入力してください")
    if not math.isfinite(params.initial_cash) or params.initial_cash <= 0:
        raise EngineInputError("初期資金は1円以上で入力してください")
    if params.initial_cash > MAX_INITIAL_CASH:
        raise EngineInputError("初期資金は10億円以下で入力してください")
    if params.lot_size < 1:
        raise EngineInputError("売買単位は1以上にしてください")


def validate_bars(bars: Sequence[Bar]) -> None:
    """データの異常をはじく(2.8 最後の項目、3.1)。持ち株がない日も同じようにチェックする。"""
    for previous, current in zip(bars, bars[1:], strict=False):
        if current.date <= previous.date:
            raise EngineDataError(
                f"日足の日付が古い順に並んでいません({previous.date} の次が {current.date})"
            )
    for bar in bars:
        if bar.adj_factor is None:
            raise EngineDataError(f"{bar.date} の調整係数が Null です")
        if not (bar.adj_factor > 0 and math.isfinite(bar.adj_factor)):
            raise EngineDataError(f"{bar.date} の調整係数が正しくありません: {bar.adj_factor}")
        if bar.adj_factor != 1.0 and bar.ex_rt not in KNOWN_EX_RT:
            raise EngineDataError(
                f"{bar.date} は調整係数が {bar.adj_factor} なのに、権利落ちの種類が {bar.ex_rt} です"
            )
        if (bar.open is None) != (bar.close is None):
            raise EngineDataError(f"{bar.date} は始値と終値の片方だけが Null です")


# --- 読み込む範囲(2.2 ウォームアップ期間) --------------------------------------------


def select_load_range(
    bars: Sequence[Bar], start: dt.date, end: dt.date, long_window: int
) -> list[Bar]:
    """ウォームアップの最も古い有効日から終了日までの、すべての営業日のレコードを返す。

    開始日より前の有効日を long_window 個まで使う。足りなければあるだけを使う。
    すでにこの範囲に切り出された入力を渡しても、同じ結果になる。
    """
    period = [i for i, bar in enumerate(bars) if start <= bar.date <= end]
    if len(period) < MIN_PERIOD_BUSINESS_DAYS:
        raise EngineInputError("期間が短すぎます。営業日が3日以上になるように指定してください")
    before = [i for i, bar in enumerate(bars) if bar.date < start and bar.is_valid]
    warmup = before[-long_window:] if before else []
    first = warmup[0] if warmup else period[0]
    return list(bars[first : period[-1] + 1])


# --- 売買の部品 ---------------------------------------------------------------------


def decide_buy_shares(
    cash: float, fill_price: float, fee_rate: float, lot_size: int
) -> tuple[int, float]:
    """2.7 株数の決め方。(株数, 1株あたりの費用 unit_cost) を返す。株数0は資金不足。"""
    unit_cost = fill_price * (1 + fee_rate)
    lots = math.floor(cash / unit_cost / lot_size)
    shares = lots * lot_size
    if unit_cost * shares > cash:
        # 割り算の丸めで lots が1多くなる境目のケース
        lots -= 1
        shares = lots * lot_size
    return max(shares, 0), unit_cost


def valuation_price(bars: Sequence[Bar], index: int) -> float:
    """5章の評価価格。有効日なら未調整の終値。そうでなければ直近の有効日 u の終値に、
    u の翌営業日から t までの分割・併合(ExRT が1か2)の調整係数の積を掛ける。"""
    bar = bars[index]
    if bar.close is not None:
        return bar.close
    u = index - 1
    while u >= 0 and bars[u].close is None:
        u -= 1
    if u < 0:
        raise EngineDataError(
            f"{bar.date} より前に終値のある日がないため、評価価格を決められません"
        )
    factor = 1.0
    for d in range(u + 1, index + 1):
        if bars[d].ex_rt in SPLIT_OR_MERGER:
            adj = bars[d].adj_factor
            assert adj is not None
            factor = factor * adj
    close_u = bars[u].close
    assert close_u is not None
    return close_u * factor


@dataclass
class _OpenTrade:
    entry_date: dt.date
    entry_price: float
    entry_shares: int
    buy_cost: float
    fraction_cash: float = 0.0

    def close(
        self,
        *,
        exit_date: dt.date,
        exit_price: float | None,
        exit_shares: int | None,
        sell_proceeds: float | None,
        closed_by: str,
    ) -> Trade:
        # 5章:1往復の損益 = (売りの notional − 売りの fee + 端数を現金に換えた額) − 買いの buy_cost
        sell_term = sell_proceeds if sell_proceeds is not None else 0.0
        pnl = (sell_term + self.fraction_cash) - self.buy_cost
        return Trade(
            entry_date=self.entry_date,
            entry_price=self.entry_price,
            entry_shares=self.entry_shares,
            buy_cost=self.buy_cost,
            exit_date=exit_date,
            exit_price=exit_price,
            exit_shares=exit_shares,
            sell_proceeds=sell_proceeds,
            fraction_cash=self.fraction_cash,
            pnl=pnl,
            closed_by=closed_by,  # type: ignore[arg-type]
        )

    def as_open_trade(self) -> Trade:
        return Trade(
            entry_date=self.entry_date,
            entry_price=self.entry_price,
            entry_shares=self.entry_shares,
            buy_cost=self.buy_cost,
            exit_date=None,
            exit_price=None,
            exit_shares=None,
            sell_proceeds=None,
            fraction_cash=self.fraction_cash,
            pnl=None,
            closed_by=None,
        )


@dataclass(frozen=True)
class _Order:
    side: Side
    signal_date: dt.date


# --- 本体 ---------------------------------------------------------------------------


def run_backtest(
    bars: Sequence[Bar], start: dt.date, end: dt.date, params: MaCrossParams
) -> BacktestResult:
    """bars はその銘柄の日足(古い順)。ウォームアップに使う開始日より前のデータも含めて渡す。"""
    validate_params(params)
    if start > end:
        raise EngineInputError("開始日は終了日より前の日付にしてください")
    validate_bars(bars)
    loaded = select_load_range(bars, start, end, params.long_window)

    states = compute_cross_states(loaded, params.short_window, params.long_window)
    valid_indices = [i for i, bar in enumerate(loaded) if bar.is_valid]
    previous_valid = {
        t: (valid_indices[k - 1] if k > 0 else None) for k, t in enumerate(valid_indices)
    }
    period_indices = [i for i, bar in enumerate(loaded) if start <= bar.date <= end]
    first_period = period_indices[0]

    cash = float(params.initial_cash)
    shares = 0
    pending: _Order | None = None
    open_trade: _OpenTrade | None = None

    daily: list[DailyRecord] = []
    signals: list[Signal] = []
    fills: list[Fill] = []
    skipped: list[SkippedOrder] = []
    events: list[CorporateActionEvent] = []
    trades: list[Trade] = []
    first_judgeable: int | None = None

    for t in period_indices:
        bar = loaded[t]

        # 手順1:分割・併合の処理(2.8)
        if bar.ex_rt in SPLIT_OR_MERGER and shares > 0:
            assert open_trade is not None and bar.adj_factor is not None
            p, q = recover_split_ratio(bar.adj_factor)
            new_shares = shares * p // q  # 整数の掛け算と割り算
            remainder = shares * p % q
            fraction_shares = remainder / q
            fraction_cash = fraction_shares * valuation_price(loaded, t) if remainder else 0.0
            cash = cash + fraction_cash
            open_trade.fraction_cash = open_trade.fraction_cash + fraction_cash
            closed = new_shares == 0
            events.append(
                CorporateActionEvent(
                    date=bar.date,
                    ex_rt=bar.ex_rt,
                    adj_factor=bar.adj_factor,
                    ratio_numerator=p,
                    ratio_denominator=q,
                    shares_before=shares,
                    shares_after=new_shares,
                    fraction_shares=fraction_shares,
                    fraction_cash=fraction_cash,
                    closed_position=closed,
                )
            )
            shares = new_shares
            if closed:
                # 併合で0株になったら、その日に決済したものとして扱う
                trades.append(
                    open_trade.close(
                        exit_date=bar.date,
                        exit_price=None,
                        exit_shares=None,
                        sell_proceeds=None,
                        closed_by="merger",
                    )
                )
                open_trade = None
                if pending is not None and pending.side == "sell":
                    pending = None  # 売る株がなくなったので、売り注文は取り消す

        # 手順2:約定(2.6)。始値が Null なら次の有効日に繰り越す
        if pending is not None and bar.open is not None:
            if pending.side == "buy":
                fill_price = bar.open * (1 + params.slippage_rate)
                buy_shares, unit_cost = decide_buy_shares(
                    cash, fill_price, params.fee_rate, params.lot_size
                )
                if buy_shares == 0:
                    skipped.append(
                        SkippedOrder(
                            date=bar.date,
                            signal_date=pending.signal_date,
                            open_price=bar.open,
                            fill_price=fill_price,
                            cash=cash,
                        )
                    )
                else:
                    notional = fill_price * buy_shares
                    fee = notional * params.fee_rate
                    buy_cost = unit_cost * buy_shares
                    cash = cash - buy_cost
                    if cash < 0:
                        raise AssertionError("買った後の現金が負になりました(実装のバグ)")
                    shares = buy_shares
                    open_trade = _OpenTrade(bar.date, fill_price, buy_shares, buy_cost)
                    fills.append(
                        Fill(
                            date=bar.date,
                            signal_date=pending.signal_date,
                            side="buy",
                            open_price=bar.open,
                            fill_price=fill_price,
                            shares=buy_shares,
                            notional=notional,
                            fee=fee,
                            cash_after=cash,
                        )
                    )
            else:
                assert open_trade is not None and shares > 0
                fill_price = bar.open * (1 - params.slippage_rate)
                notional = fill_price * shares
                fee = notional * params.fee_rate
                proceeds = notional - fee
                cash = cash + proceeds
                fills.append(
                    Fill(
                        date=bar.date,
                        signal_date=pending.signal_date,
                        side="sell",
                        open_price=bar.open,
                        fill_price=fill_price,
                        shares=shares,
                        notional=notional,
                        fee=fee,
                        cash_after=cash,
                    )
                )
                trades.append(
                    open_trade.close(
                        exit_date=bar.date,
                        exit_price=fill_price,
                        exit_shares=shares,
                        sell_proceeds=proceeds,
                        closed_by="sell",
                    )
                )
                open_trade = None
                shares = 0
            pending = None

        # 手順3:評価(5章)
        price = valuation_price(loaded, t) if shares > 0 else None
        equity = cash + shares * price if price is not None else cash

        # 手順4:シグナル判定(2.3、2.4)
        state = states.get(t)
        prev = previous_valid.get(t)
        prev_state = states.get(prev) if prev is not None else None
        if (
            state is not None
            and state.d is not None
            and prev_state is not None
            and prev_state.d is not None
        ):
            if first_judgeable is None:
                first_judgeable = t
            side = detect_cross(prev_state.d, state.d)
            if side is not None:
                assert pending is None  # 有効日の手順2で必ず片づいている
                acts = (side == "buy" and shares == 0) or (side == "sell" and shares > 0)
                signals.append(Signal(bar.date, side, "order" if acts else "ignored"))  # type: ignore[arg-type]
                if acts:
                    pending = _Order(side, bar.date)  # type: ignore[arg-type]

        daily.append(
            DailyRecord(
                date=bar.date,
                close=bar.close,
                short_ma=_moving_average(state, params.short_window, "short"),
                long_ma=_moving_average(state, params.long_window, "long"),
                cash=cash,
                shares=shares,
                valuation_price=price,
                equity=equity,
            )
        )

    if open_trade is not None:
        trades.append(open_trade.as_open_trade())

    equities = [record.equity for record in daily]
    metrics = compute_metrics(equities, params.initial_cash, trades)
    warmup = _warmup_info(loaded, first_period, period_indices, params.long_window, first_judgeable)
    notes = Notes(
        open_position_at_end=shares > 0,
        annualized_is_reference=metrics.return_count < TRADING_DAYS_PER_YEAR,
    )
    return BacktestResult(
        params=params,
        start=start,
        end=end,
        daily=tuple(daily),
        signals=tuple(signals),
        fills=tuple(fills),
        skipped_orders=tuple(skipped),
        events=tuple(events),
        trades=tuple(trades),
        metrics=metrics,
        warmup=warmup,
        notes=notes,
    )


def _moving_average(state: CrossState | None, window: int, which: str) -> float | None:
    if state is None:
        return None
    total = state.short_sum if which == "short" else state.long_sum
    return None if total is None else total / window


def _warmup_info(
    loaded: Sequence[Bar],
    first_period: int,
    period_indices: Sequence[int],
    long_window: int,
    first_judgeable: int | None,
) -> WarmupInfo:
    warm = [bar for bar in loaded[:first_period] if bar.is_valid]
    sufficient = len(warm) >= long_window
    unavailable_until: dt.date | None = None
    if not sufficient:
        if first_judgeable is None:
            unavailable_until = loaded[period_indices[-1]].date
        else:
            position = period_indices.index(first_judgeable)
            unavailable_until = loaded[period_indices[position - 1]].date if position > 0 else None
    return WarmupInfo(
        first_date=warm[0].date if warm else None,
        last_date=warm[-1].date if warm else None,
        valid_days=len(warm),
        sufficient=sufficient,
        signals_unavailable_until=unavailable_until,
    )
