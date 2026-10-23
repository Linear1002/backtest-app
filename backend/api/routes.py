"""API のエンドポイント。"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.api import convert
from backend.api.schemas import (
    BacktestOut,
    BacktestRequest,
    CorporateActionOut,
    DataSourceOut,
    DateRangeOut,
    EngineOut,
    ErrorItem,
    ErrorResponse,
    MarketOut,
    MetaOut,
    ParamOut,
    ParamsOut,
    PeriodOut,
    StrategyListOut,
    StrategyOut,
    SymbolDetailOut,
    SymbolListOut,
)
from backend.api.validation import InputValidationError, validate_params, validate_period
from backend.engines import get_engine, list_engines
from backend.marketdata.jquants import LICENSE_NOTE as JQUANTS_LICENSE
from backend.marketdata.jquants import JQuantsDataSource
from backend.marketdata.models import SymbolId
from backend.marketdata.service import MarketDataService
from backend.marketdata.synthetic import LICENSE_NOTE as DEMO_LICENSE
from backend.strategies import STRATEGIES, STRATEGIES_BY_ID
from engine.reference.types import TRADING_DAYS_PER_YEAR

router = APIRouter(prefix="/api")

ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "銘柄が見つからない"},
    422: {"model": ErrorResponse, "description": "入力内容に誤りがある"},
    503: {"model": ErrorResponse, "description": "外部のデータソースに問い合わせできない"},
}


def get_service(request: Request) -> MarketDataService:
    return request.app.state.market_data


Service = Annotated[MarketDataService, Depends(get_service)]


@router.get("/health")
def health() -> dict[str, str]:
    """サーバーが起動しているかの確認用。"""
    return {"status": "ok"}


@router.get("/meta", response_model=MetaOut)
def meta(service: Service) -> MetaOut:
    """使えるデータソースとエンジン。"""
    sources = [
        DataSourceOut(
            id=source.source_id,
            label=getattr(source, "source_label", source.source_id),
            markets=list(source.markets),
            license_note=JQUANTS_LICENSE if isinstance(source, JQuantsDataSource) else DEMO_LICENSE,
            can_fetch=source.has_client if isinstance(source, JQuantsDataSource) else True,
        )
        for source in service.sources
    ]
    return MetaOut(
        data_sources=sources,
        engines=[EngineOut(**vars(e)) for e in list_engines()],
        trading_days_per_year=TRADING_DAYS_PER_YEAR,
    )


@router.get("/symbols", response_model=SymbolListOut)
def search_symbols(
    service: Service,
    q: Annotated[str, Query(description="銘柄コードまたは銘柄名(ひらがな・全角数字も可)")] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SymbolListOut:
    """銘柄を検索する。"""
    items = []
    for info in service.search(q, limit=limit):
        source = service.source_for(info.symbol_id)
        items.append(convert.symbol_out(info, source.source_id))
    return SymbolListOut(items=items)


@router.get("/symbols/{symbol_id}", response_model=SymbolDetailOut, responses=ERROR_RESPONSES)
def symbol_detail(symbol_id: str, service: Service) -> SymbolDetailOut:
    """銘柄の詳細(データの範囲・権利落ち・売買不成立の日数)。"""
    sid = SymbolId.parse(symbol_id)
    source = service.source_for(sid)
    bars = service.get_daily_bars(sid)
    available = service.get_available_range(sid)
    market = sid.market_config
    return SymbolDetailOut(
        symbol=convert.symbol_out(service.find_symbol(sid), source.source_id),
        market=MarketOut(
            code=market.code, name=market.name, currency=market.currency, lot_size=market.lot_size
        ),
        range=DateRangeOut(
            first_date=available.first,
            last_date=available.last,
            business_days=len(bars),
            trading_days=sum(1 for bar in bars if bar.close is not None),
        ),
        corporate_actions=[
            CorporateActionOut(
                date=bar.date,
                ex_rt=bar.ex_rt,
                label=convert.EX_RT_LABELS.get(bar.ex_rt or 0, "権利落ち"),
                adj_factor=bar.adj_factor if bar.adj_factor is not None else 1.0,
            )
            for bar in bars
            if bar.ex_rt is not None or (bar.adj_factor not in (None, 1.0))
        ],
        halted_days=sum(1 for bar in bars if bar.close is None),
        data_info=convert.data_info_out(service.get_data_info(sid)),
    )


@router.get("/strategies", response_model=StrategyListOut)
def strategies() -> StrategyListOut:
    """戦略の一覧とパラメータの定義。"""
    return StrategyListOut(
        items=[
            StrategyOut(
                id=s.id,
                name=s.name,
                summary=s.summary,
                description=s.description,
                available=s.available,
                params=[ParamOut(**vars(p)) for p in s.params],
            )
            for s in STRATEGIES
        ]
    )


@router.post("/backtests", response_model=BacktestOut, responses=ERROR_RESPONSES)
def run_backtest_endpoint(body: BacktestRequest, service: Service) -> BacktestOut:
    """バックテストを実行する。"""
    strategy = STRATEGIES_BY_ID.get(body.strategy_id)
    if strategy is None or not strategy.available:
        raise InputValidationError(
            [ErrorItem(field="strategy_id", message="この戦略はまだ使えません")]
        )
    sid = SymbolId.parse(body.symbol_id)
    market = sid.market_config
    params = validate_params(body.params, market.lot_size)
    run = get_engine(body.engine)  # 使えないエンジンなら EngineUnavailableError

    source = service.source_for(sid)
    all_bars = service.get_daily_bars(sid)
    available = service.get_available_range(sid)
    period = validate_period(body.start_date, body.end_date, available, all_bars)

    started = time.perf_counter()
    result = run(convert.to_engine_bars(all_bars), period.start, period.end, params)
    elapsed_ms = (time.perf_counter() - started) * 1000

    data_info = service.get_data_info(sid)
    engine_info = next(e for e in list_engines() if e.id == body.engine)
    return BacktestOut(
        symbol=convert.symbol_out(service.find_symbol(sid), source.source_id),
        strategy_id=strategy.id,
        engine=EngineOut(**vars(engine_info)),
        period=PeriodOut(
            start_date=period.start,
            end_date=period.end,
            first_business_day=result.daily[0].date,
            last_business_day=result.daily[-1].date,
            business_days=len(result.daily),
            return_count=result.metrics.return_count,
        ),
        params=ParamsOut(
            short_window=params.short_window,
            long_window=params.long_window,
            fee_rate_pct=body.params.fee_rate_pct,
            slippage_rate_pct=body.params.slippage_rate_pct,
            fee_rate=params.fee_rate,
            slippage_rate=params.slippage_rate,
            initial_cash=params.initial_cash,
            lot_size=params.lot_size,
        ),
        metrics=convert.metrics_out(result),
        warmup=convert.warmup_out(result.warmup),
        insufficient_cash_count=result.insufficient_cash_count,
        notes=convert.notes_out(result, sid.market, data_info.license_note),
        daily=convert.daily_out(result),
        signals=convert.signals_out(result),
        fills=convert.fills_out(result),
        skipped_orders=convert.skipped_out(result),
        events=convert.events_out(result),
        trades=convert.trades_out(result),
        data_info=convert.data_info_out(data_info),
        elapsed_ms=elapsed_ms,
    )
