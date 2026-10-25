"""API のエンドポイント。"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.api import convert, sweep_convert, walkforward_convert
from backend.api.schemas import (
    BacktestOut,
    BacktestRequest,
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
    SweepEngineOut,
    SweepRequest,
    SweepResultOut,
    SweepStatusOut,
    SymbolDetailOut,
    SymbolListOut,
    WalkForwardRequest,
    WalkForwardResultOut,
    WalkForwardStatusOut,
)
from backend.api.validation import (
    InputValidationError,
    check_walkforward_runs,
    validate_holdout,
    validate_params,
    validate_period,
    validate_sweep_inputs,
    walkforward_settings_errors,
)
from backend.engines import get_engine, get_sweep_engine, list_engines, list_sweep_engines
from backend.marketdata.models import SymbolId
from backend.marketdata.service import MarketDataService
from backend.strategies import STRATEGIES, STRATEGIES_BY_ID
from backend.sweeps import INTERNAL_ERROR as SWEEP_INTERNAL_ERROR
from backend.sweeps import SweepJob, SweepJobs, SweepSpec
from engine.reference.benchmark import run_buy_and_hold
from engine.reference.sweep import InSampleTooShortError, SweepRow, validate_sweep
from engine.reference.types import TRADING_DAYS_PER_YEAR
from engine.reference.walkforward import (
    WalkForwardSettings,
    WindowError,
    assemble_walkforward,
    calendar_windows,
    validate_walkforward,
)

router = APIRouter(prefix="/api")

ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "銘柄が見つからない"},
    422: {"model": ErrorResponse, "description": "入力内容に誤りがある"},
    503: {"model": ErrorResponse, "description": "外部のデータソースに問い合わせできない"},
}


def get_service(request: Request) -> MarketDataService:
    return request.app.state.market_data


Service = Annotated[MarketDataService, Depends(get_service)]


def get_sweeps(request: Request) -> SweepJobs:
    return request.app.state.sweeps


Sweeps = Annotated[SweepJobs, Depends(get_sweeps)]


class SweepNotFoundError(LookupError):
    """知らない(または消えた)総当たりのジョブ。メッセージは画面に出せる日本語。"""


@router.get("/health")
def health() -> dict[str, str]:
    """サーバーが起動しているかの確認用。"""
    return {"status": "ok"}


@router.get("/meta", response_model=MetaOut)
def meta(service: Service, sweeps: Sweeps) -> MetaOut:
    """使えるデータソースとエンジン。"""
    sources = [
        DataSourceOut(
            id=source.source_id,
            label=source.source_label,
            markets=list(source.markets),
            license_note=source.license_note,
            can_fetch=source.can_fetch,
        )
        for source in service.sources
    ]
    return MetaOut(
        data_sources=sources,
        engines=[EngineOut(**vars(e)) for e in list_engines()],
        sweep_engines=[SweepEngineOut(**vars(e)) for e in list_sweep_engines(sweeps.workers)],
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
        items.append(convert.symbol_out(info, source.source_id, service.describe(info.symbol_id)))
    return SymbolListOut(items=items)


@router.get("/symbols/{symbol_id}", response_model=SymbolDetailOut, responses=ERROR_RESPONSES)
def symbol_detail(symbol_id: str, service: Service) -> SymbolDetailOut:
    """銘柄の詳細(データの範囲・権利落ち・売買不成立の日数)。"""
    sid = SymbolId.parse(symbol_id)
    source = service.source_for(sid)
    service.require_listed(sid)  # 上場廃止などで MVP の対象外なら 404(docs/mvp.md 3.6)
    data = service.load(sid)
    return SymbolDetailOut(
        symbol=convert.symbol_out(
            service.find_symbol(sid), source.source_id, service.describe(sid)
        ),
        market=market_out(sid),
        range=DateRangeOut(
            first_date=data.available.first,
            last_date=data.available.last,
            business_days=len(data.bars),
            trading_days=sum(1 for bar in data.bars if bar.close is not None),
        ),
        corporate_actions=convert.corporate_actions_out(data.bars),
        halted_days=sum(1 for bar in data.bars if bar.close is None),
        data_info=convert.data_info_out(data.info),
    )


def market_out(sid: SymbolId) -> MarketOut:
    market = sid.market_config
    return MarketOut(
        code=market.code,
        name=market.name,
        currency=market.currency,
        lot_size=market.lot_size,
        trading_days_per_year=market.trading_days_per_year,
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
    params = validate_params(body.params, market)
    run = get_engine(body.engine)  # 使えないエンジンなら EngineUnavailableError

    source = service.source_for(sid)
    service.require_listed(sid)
    data = service.load(sid)  # 日足・範囲・出どころを1回の読み込みから作る
    period = validate_period(body.start_date, body.end_date, data.available, data.bars)

    bars = convert.to_engine_bars(data.bars)
    started = time.perf_counter()
    result = run(bars, period.start, period.end, params)
    elapsed_ms = (time.perf_counter() - started) * 1000
    # 比較の基準:同じ期間・同じ費用の買い持ち(docs/benchmark.md)。エンジンにかかわらず Python で計算する
    benchmark = run_buy_and_hold(bars, period.start, period.end, params)

    first_day, last_day = result.daily[0].date, result.daily[-1].date
    engine_info = next(e for e in list_engines() if e.id == body.engine)
    return BacktestOut(
        symbol=convert.symbol_out(
            service.find_symbol(sid), source.source_id, service.describe(sid)
        ),
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
            trading_days_per_year=params.trading_days_per_year,
        ),
        metrics=convert.metrics_out(result),
        warmup=convert.warmup_out(result.warmup),
        insufficient_cash_count=result.insufficient_cash_count,
        notes=convert.notes_out(result, sid.market, data.info, benchmark),
        daily=convert.daily_out(result, benchmark),
        signals=convert.signals_out(result),
        fills=convert.fills_out(result),
        skipped_orders=convert.skipped_out(result),
        events=convert.events_out(result),
        trades=convert.trades_out(result),
        benchmark=convert.benchmark_out(benchmark),
        corporate_actions=convert.corporate_actions_out(
            [bar for bar in data.bars if first_day <= bar.date <= last_day]
        ),
        data_info=convert.data_info_out(data.info),
        elapsed_ms=elapsed_ms,
    )


# --- 総当たり(docs/sweep.md) ----------------------------------------------------------

SWEEP_RESPONSES = {
    **ERROR_RESPONSES,
    409: {"model": ErrorResponse, "description": "ほかの総当たりを計算している"},
}
SWEEP_NOT_FOUND = (
    "その総当たりは見つかりません。終わってから30分たったか、API サーバーを起動し直した可能性があります。"
    "もう一度実行してください"
)


def job_fields(job: SweepJob) -> dict:
    """ジョブの途中経過・結果・失敗(総当たりとウォークフォワード分析で共通)。job.lock の中で呼ぶ。"""
    error = None
    if job.status == "failed":
        if job.error_kind == "data":
            detail = f"データに異常があるため計算できません:{job.error_message}"
        elif job.error_kind == "input":
            detail = job.error_message or "入力内容を確認してください"
        else:
            detail = job.error_message or SWEEP_INTERNAL_ERROR
        error = ErrorResponse(detail=detail, errors=[])
    return {
        "id": job.id,
        "status": job.status,
        "done": job.done,
        "total": job.total,
        "elapsed_ms": job.elapsed_seconds * 1000 if job.elapsed_seconds is not None else None,
        "result": job.output if job.status == "done" else None,
        "error": error,
    }


def sweep_status_out(job: SweepJob) -> SweepStatusOut:
    with job.lock:
        return SweepStatusOut(**job_fields(job))


def find_job(jobs: SweepJobs, job_id: str, kind: str, cancel: bool = False) -> SweepJob:
    """その種類のジョブ(ほかの種類の id は、見つからないのと同じにする)。"""
    job = jobs.get(job_id)
    if job is None or job.spec.kind != kind:
        raise SweepNotFoundError(SWEEP_NOT_FOUND if kind == "sweep" else WALKFORWARD_NOT_FOUND)
    if cancel:
        jobs.cancel(job_id)
    return job


@router.post("/sweeps", status_code=202, response_model=SweepStatusOut, responses=SWEEP_RESPONSES)
def start_sweep(body: SweepRequest, service: Service, sweeps: Sweeps) -> SweepStatusOut:
    """総当たりを始める(すぐに返る)。途中経過と結果は GET /api/sweeps/{id} で受け取る。"""
    strategy = STRATEGIES_BY_ID.get(body.strategy_id)
    if strategy is None or not strategy.available:
        raise InputValidationError(
            [ErrorItem(field="strategy_id", message="この戦略はまだ使えません")]
        )
    engine = get_sweep_engine(body.engine, sweeps.workers)  # 使えなければ EngineUnavailableError
    sid = SymbolId.parse(body.symbol_id)
    grid, costs = validate_sweep_inputs(body.grid, body.params, sid.market_config, engine.max_pairs)

    source = service.source_for(sid)
    service.require_listed(sid)
    data = service.load(sid)
    period = validate_period(body.start_date, body.end_date, data.available, data.bars)
    holdout = validate_holdout(body.holdout_start_date, period, data.bars)
    bars = convert.to_engine_bars(data.bars)
    # エンジンのチェック(データの異常など。docs/sweep.md 5章)は、計算を始める前にここで行う
    try:
        pairs, segments = validate_sweep(bars, period.start, period.end, grid, costs, holdout)
    except InSampleTooShortError as error:
        # 選ぶ期間の始まりをそろえると短すぎる:検証期間があればその開始日の欄、なければ格子の欄に出す
        field = "holdout_start_date" if holdout is not None else "grid"
        raise InputValidationError([ErrorItem(field=field, message=str(error))]) from error

    # 期間ごとの買い持ち(docs/benchmark.md)。日数は使わないので、どの組み合わせのパラメータでも同じ
    benchmarks = [
        run_buy_and_hold(bars, segment.start, segment.end, costs.params_for(*pairs[0]))
        for segment in segments
    ]
    context = sweep_convert.SweepContext(
        symbol=convert.symbol_out(
            service.find_symbol(sid), source.source_id, service.describe(sid)
        ),
        strategy_id=strategy.id,
        engine=SweepEngineOut(**vars(engine)),
        market=sid.market,
        data_info=data.info,
        grid=grid,
        costs=costs,
        fee_rate_pct=body.params.fee_rate_pct,
        slippage_rate_pct=body.params.slippage_rate_pct,
        segments=sweep_convert.segments_out(segments, data.bars, period.start, benchmarks),
        longest_window=max(long for _, long in pairs),
    )
    spec = SweepSpec(tuple(bars), segments, costs, tuple(pairs), context)

    def build(rows: tuple[SweepRow, ...]) -> SweepResultOut:
        return sweep_convert.result_out(context, spec.pairs, rows)

    return sweep_status_out(sweeps.start(spec, build=build))


@router.get("/sweeps/{sweep_id}", response_model=SweepStatusOut, responses=SWEEP_RESPONSES)
def get_sweep(sweep_id: str, sweeps: Sweeps) -> SweepStatusOut:
    """総当たりの途中経過。終わっていれば結果も返す。"""
    return sweep_status_out(find_job(sweeps, sweep_id, "sweep"))


@router.delete("/sweeps/{sweep_id}", response_model=SweepStatusOut, responses=SWEEP_RESPONSES)
def cancel_sweep(sweep_id: str, sweeps: Sweeps) -> SweepStatusOut:
    """総当たりを中止する(すでに終わっていれば何もしない)。"""
    return sweep_status_out(find_job(sweeps, sweep_id, "sweep", cancel=True))


# --- ウォークフォワード分析(docs/walkforward.md) ------------------------------------------

WALKFORWARD_NOT_FOUND = (
    "そのウォークフォワード分析は見つかりません。終わってから30分たったか、API サーバーを起動し直した可能性があります。"
    "もう一度実行してください"
)


def walkforward_status_out(job: SweepJob) -> WalkForwardStatusOut:
    with job.lock:
        return WalkForwardStatusOut(**job_fields(job))


def walkforward_max_runs(max_pairs: int) -> int:
    """計算の量の上限(docs/walkforward.md 9章):総当たりの組み合わせの上限 × 2(選ぶ期間と検証期間の2回分と同じ量)。"""
    return max_pairs * 2


@router.post(
    "/walkforwards", status_code=202, response_model=WalkForwardStatusOut, responses=SWEEP_RESPONSES
)
def start_walkforward(
    body: WalkForwardRequest, service: Service, sweeps: Sweeps
) -> WalkForwardStatusOut:
    """ウォークフォワード分析を始める(すぐに返る)。途中経過と結果は GET /api/walkforwards/{id} で受け取る。"""
    strategy = STRATEGIES_BY_ID.get(body.strategy_id)
    if strategy is None or not strategy.available:
        raise InputValidationError(
            [ErrorItem(field="strategy_id", message="この戦略はまだ使えません")]
        )
    engine = get_sweep_engine(body.engine, sweeps.workers)  # 使えなければ EngineUnavailableError
    sid = SymbolId.parse(body.symbol_id)
    # 1〜3:格子・費用・設定(誤りはまとめて返す。組み合わせの数の上限は、区切りの数が決まってから計算の量で確かめる)
    grid, costs = validate_sweep_inputs(
        body.grid,
        body.params,
        sid.market_config,
        None,
        extra=walkforward_settings_errors(
            body.objective, body.in_sample_months, body.out_of_sample_months
        ),
    )
    settings = WalkForwardSettings(
        objective=body.objective,
        in_sample_months=int(body.in_sample_months),
        out_of_sample_months=int(body.out_of_sample_months),
    )

    source = service.source_for(sid)
    service.require_listed(sid)
    data = service.load(sid)
    period = validate_period(body.start_date, body.end_date, data.available, data.bars)  # 4
    windows_plan = calendar_windows(
        period.start, period.end, settings.in_sample_months, settings.out_of_sample_months
    )
    pairs_count = len(grid.pairs())
    if windows_plan:  # 6:計算の量(区切りがないときは、下の validate_walkforward が 5 の誤りにする)
        check_walkforward_runs(
            pairs_count, len(windows_plan), walkforward_max_runs(engine.max_pairs)
        )
    bars = convert.to_engine_bars(data.bars)
    try:
        pairs, windows = validate_walkforward(bars, period.start, period.end, grid, costs, settings)
    except WindowError as error:
        raise InputValidationError([ErrorItem(field=error.field, message=str(error))]) from error

    context = walkforward_convert.WalkForwardContext(
        symbol=convert.symbol_out(
            service.find_symbol(sid), source.source_id, service.describe(sid)
        ),
        strategy_id=strategy.id,
        engine=SweepEngineOut(**vars(engine)),
        market=sid.market,
        data_info=data.info,
        bars=tuple(data.bars),
        end=period.end,
        grid=grid,
        costs=costs,
        fee_rate_pct=body.params.fee_rate_pct,
        slippage_rate_pct=body.params.slippage_rate_pct,
        settings=settings,
    )
    # 重い計算(すべての組み合わせを、すべての区切りの選ぶ期間で)は総当たりと同じジョブで並列にする
    spec = SweepSpec(
        tuple(bars),
        tuple(w.in_sample for w in windows),
        costs,
        tuple(pairs),
        context,
        kind="walkforward",
    )

    def build(rows: tuple[SweepRow, ...]) -> WalkForwardResultOut:
        # 選んで、使う期間を計算して、つなぐ(区切りの数だけの軽い計算。ジョブのスレッドで行う)
        result = assemble_walkforward(spec.bars, pairs, windows, rows, costs, settings)
        return walkforward_convert.result_out(context, result)

    return walkforward_status_out(sweeps.start(spec, build=build))


@router.get(
    "/walkforwards/{walkforward_id}",
    response_model=WalkForwardStatusOut,
    responses=SWEEP_RESPONSES,
)
def get_walkforward(walkforward_id: str, sweeps: Sweeps) -> WalkForwardStatusOut:
    """ウォークフォワード分析の途中経過。終わっていれば結果も返す。"""
    return walkforward_status_out(find_job(sweeps, walkforward_id, "walkforward"))


@router.delete(
    "/walkforwards/{walkforward_id}",
    response_model=WalkForwardStatusOut,
    responses=SWEEP_RESPONSES,
)
def cancel_walkforward(walkforward_id: str, sweeps: Sweeps) -> WalkForwardStatusOut:
    """ウォークフォワード分析を中止する(すでに終わっていれば何もしない)。"""
    return walkforward_status_out(find_job(sweeps, walkforward_id, "walkforward", cancel=True))
