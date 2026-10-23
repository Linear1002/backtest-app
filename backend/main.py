"""FastAPI のエントリーポイント。

起動:make dev-api → http://localhost:8000/docs で API の説明とお試し実行ができる。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.errors import install_error_handlers
from backend.api.routes import router
from backend.marketdata.service import MarketDataService, build_service
from backend.settings import Settings, load_settings


def create_app(
    settings: Settings | None = None, service: MarketDataService | None = None
) -> FastAPI:
    """アプリを作る。テストでは settings や service を差し替えられる。"""
    settings = settings or load_settings()
    app = FastAPI(
        title="日本語バックテストアプリ API",
        description=(
            "移動平均クロス戦略のバックテストを実行する API。仕様は docs/mvp.md。"
            "率(手数料率・スリッページ率)は % で受け渡しする。"
        ),
        version="0.1.0",
    )
    app.state.settings = settings
    app.state.market_data = service or build_service(settings)
    # 画面は Next.js の rewrites で同じオリジンとして呼ぶが、直接呼ぶときのために許可しておく
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    install_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
