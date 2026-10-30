"""例外を、日本語のエラーレスポンス({"detail": ..., "errors": [...]})に変換する。

- APIキーなどの秘密情報は、どのメッセージにも含めない(データ層のメッセージも含まないように作ってある)
- 想定していない例外も、必ず JSON(日本語)で返す。中身(トレースバック)はサーバーのログにだけ出す。
  画面は「JSON でない 500」を「API サーバーにつながらない」と判断するので、区別できるようにするため
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.validation import InputValidationError
from backend.engines import EngineUnavailableError
from backend.marketdata.models import InvalidSymbolIdError
from backend.marketdata.source import (
    DataSourceNotConfiguredError,
    DataSourceRequestError,
    SymbolNotFoundError,
)
from engine.reference import EngineDataError, EngineInputError

logger = logging.getLogger("backend.api")

HTTP_MESSAGES = {
    404: "そのアドレスの API はありません",
    405: "その方法(メソッド)では呼び出せません",
}

INTERNAL_ERROR = (
    "サーバーの中で想定していないエラーが起きました。"
    "API サーバーのターミナルに出ているエラーを確認してください"
)


def _response(status: int, detail: str, errors: list[dict[str, Any]] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "errors": errors or []})


def _field_name(loc: tuple[Any, ...] | list[Any]) -> str | None:
    parts = [str(p) for p in loc]
    if parts and parts[0] in ("body", "query", "path"):
        parts = parts[1:]
    if parts and parts[0] == "params":
        parts = parts[1:]
    return ".".join(parts) or None


def japanese_message(error: dict[str, Any]) -> str:
    kind = str(error.get("type", ""))
    if kind == "missing":
        return "必須の項目です"
    if kind == "extra_forbidden":
        return "知らない項目です"
    if kind in ("json_invalid", "model_attributes_type", "dict_type"):
        return "送られてきたデータの形式が正しくありません"
    if kind.startswith(("float", "int", "finite")):
        return "数値で入力してください"
    if kind.startswith(("date", "datetime")):
        return "日付は YYYY-MM-DD の形で入力してください"
    if kind == "string_too_long":
        return "文字数が多すぎます"
    if kind.startswith("string"):
        return "文字列で入力してください"
    if kind.startswith(("greater_than", "less_than")):
        return "値の範囲が正しくありません"
    return "入力内容が正しくありません"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": _field_name(e.get("loc", ())), "message": japanese_message(e)}
            for e in exc.errors()
        ]
        return _response(422, "入力内容を確認してください", errors)

    @app.exception_handler(InputValidationError)
    async def input_validation(_: Request, exc: InputValidationError) -> JSONResponse:
        return _response(422, "入力内容を確認してください", [e.model_dump() for e in exc.errors])

    @app.exception_handler(InvalidSymbolIdError)
    async def invalid_symbol(_: Request, exc: InvalidSymbolIdError) -> JSONResponse:
        return _response(422, str(exc), [{"field": "symbol_id", "message": str(exc)}])

    @app.exception_handler(SymbolNotFoundError)
    async def not_found(_: Request, exc: SymbolNotFoundError) -> JSONResponse:
        return _response(404, str(exc))

    @app.exception_handler(DataSourceNotConfiguredError)
    async def not_configured(_: Request, exc: DataSourceNotConfiguredError) -> JSONResponse:
        return _response(503, str(exc))

    @app.exception_handler(DataSourceRequestError)
    async def upstream(_: Request, exc: DataSourceRequestError) -> JSONResponse:
        return _response(503, str(exc))

    @app.exception_handler(EngineInputError)
    async def engine_input(_: Request, exc: EngineInputError) -> JSONResponse:
        return _response(422, str(exc), [{"field": None, "message": str(exc)}])

    @app.exception_handler(EngineDataError)
    async def engine_data(_: Request, exc: EngineDataError) -> JSONResponse:
        return _response(422, f"データに異常があるため計算できません:{exc}")

    @app.exception_handler(EngineUnavailableError)
    async def engine_unavailable(_: Request, exc: EngineUnavailableError) -> JSONResponse:
        return _response(422, str(exc), [{"field": "engine", "message": str(exc)}])

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = HTTP_MESSAGES.get(
            exc.status_code, f"エラーが発生しました(HTTP {exc.status_code})"
        )
        return _response(exc.status_code, message)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 中身はログにだけ残す(例外のメッセージに内部の情報が入っていることがあるため、画面には出さない)
        logger.exception("想定していないエラー: %s %s", request.method, request.url.path)
        return _response(500, INTERNAL_ERROR)
