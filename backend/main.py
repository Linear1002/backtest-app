"""FastAPI のエントリーポイント。

起動:make dev-api → http://localhost:8000/docs で API の説明とお試し実行ができる。
uvicorn には create_app を「アプリを作る関数」として渡す(--factory)。import しただけでは .env を読まず、
アプリも作らないので、テストが本物の設定(APIキーなど)を読み込んでしまうことがない。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.errors import install_error_handlers
from backend.api.routes import router
from backend.marketdata.service import MarketDataService, build_service
from backend.settings import Settings, load_settings
from backend.sweeps import SweepJobs


def create_app(
    settings: Settings | None = None,
    service: MarketDataService | None = None,
    sweeps: SweepJobs | None = None,
) -> FastAPI:
    """アプリを作る。テストでは settings・service・sweeps(総当たりのジョブ)を差し替えられる。"""
    settings = settings or load_settings()
    jobs = sweeps or SweepJobs(settings.sweep_workers)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # サーバーを止めるとき、総当たりの計算に使っているプロセスも止める
        jobs.shutdown()

    app = FastAPI(
        lifespan=lifespan,
        title="日本語バックテストアプリ API",
        description=(
            "移動平均クロス戦略のバックテストを実行する API。仕様は docs/mvp.md。"
            "率(手数料率・スリッページ率)は % で受け渡しする。"
        ),
        version="0.1.0",
    )
    app.state.settings = settings
    # interactive=True:画面からのリクエストで、J-Quants の回数の上限を長く待たない
    app.state.market_data = service or build_service(settings, interactive=True)
    app.state.sweeps = jobs
    # 画面は Next.js の rewrites で同じオリジンとして呼ぶが、直接呼ぶときのために許可しておく
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    install_error_handlers(app)
    app.include_router(router)
    return app
