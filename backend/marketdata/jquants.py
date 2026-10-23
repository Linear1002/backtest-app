"""J-Quants API(V2)のクライアントとデータソース。

公式仕様(2026年10月に確認):
- 日足:GET /v2/equities/bars/daily  https://jpx-jquants.com/en/spec/eq-bars-daily
- 銘柄一覧:GET /v2/equities/master  https://jpx-jquants.com/en/spec/eq-master
- 取引カレンダー:GET /v2/markets/calendar  https://jpx-jquants.com/en/spec/mkt-cal
- 認証:APIキーを x-api-key ヘッダーで渡す
- 続きがあるときは、レスポンスに pagination_key が入る
- リクエスト数の上限:Free は1分間に5回。超えると 429(Retry-After ヘッダーなし)。429 も回数に数えられ、
  大きく超え続けると約5分間すべてのリクエストがエラーになる  https://jpx-jquants.com/en/spec/rate-limits

利用規約上、データは私的使用のみ(docs/mvp.md 3.2)。取得したデータは data/ に保存し、Git やアプリ経由で配布しない。
APIキーは例外メッセージ・ログ・repr に絶対に出さない。
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx

from backend.marketdata.models import DailyBar, DataInfo, DateRange, SymbolId, SymbolInfo
from backend.marketdata.source import (
    DataSourceNotConfiguredError,
    DataSourceRequestError,
    RateLimitExceededError,
    SymbolNotFoundError,
    filter_bars,
)
from backend.marketdata.store import ParquetStore

BASE_URL = "https://api.jquants.com/v2"
FREE_PLAN_REQUESTS_PER_MINUTE = 5

SOURCE_ID = "jquants"
SOURCE_LABEL = "J-Quants API(東証)"
LICENSE_NOTE = "J-Quants API のデータです。利用規約により私的使用に限られ、第三者への提供・再配布はできません。"

# 429 が返ったあとに待つ秒数。公式には「1分以上待つ」とだけあるので、少し余裕を持たせる
WAIT_AFTER_429_SECONDS = 65.0


# --- 銘柄コードの変換 ---------------------------------------------------------------


def to_jquants_code(symbol_id: SymbolId) -> str:
    """TSE:7203 → "72030"。5文字目の 0 は普通株を表す。"""
    if symbol_id.market != "TSE":
        raise ValueError(f"J-Quants は東証の銘柄だけを扱います: {symbol_id}")
    return f"{symbol_id.code}0"


def from_jquants_code(code: str) -> SymbolId | None:
    """ "72030" → TSE:7203。普通株(5文字目が 0)以外は MVP の対象外なので None を返す。"""
    if len(code) != 5 or code[4] != "0":
        return None
    try:
        return SymbolId.parse(f"TSE:{code[:4]}")
    except ValueError:
        return None


# --- レスポンスの変換 ---------------------------------------------------------------


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _flag(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return str(value) == "1"


def parse_daily_bar(item: dict[str, Any]) -> DailyBar:
    """日足の1レコードを共通形式に変換する。"""
    ex_rt_raw = item.get("ExRT")
    return DailyBar(
        date=dt.date.fromisoformat(item["Date"]),
        open=_number(item.get("O")),
        high=_number(item.get("H")),
        low=_number(item.get("L")),
        close=_number(item.get("C")),
        volume=_number(item.get("Vo")),
        turnover=_number(item.get("Va")),
        adj_factor=_number(item.get("AdjFactor")),
        ex_rt=None if ex_rt_raw in (None, "") else int(ex_rt_raw),
        upper_limit=_flag(item.get("UL")),
        lower_limit=_flag(item.get("LL")),
    )


def parse_symbol(item: dict[str, Any]) -> SymbolInfo | None:
    """銘柄一覧の1レコードを変換する。普通株以外は None。"""
    symbol_id = from_jquants_code(str(item.get("Code", "")))
    if symbol_id is None:
        return None
    return SymbolInfo(
        symbol_id=symbol_id,
        name=str(item.get("CoName") or symbol_id.code),
        name_en=item.get("CoNameEn") or None,
        segment=item.get("MktNm") or None,
        sector=item.get("S33Nm") or None,
    )


# --- レート制限 ---------------------------------------------------------------------


class RateLimiter:
    """直近 period 秒のリクエスト数が max_requests を超えないように待つ(スライディングウィンドウ)。"""

    def __init__(
        self,
        max_requests: int,
        period: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests は1以上にしてください")
        self.max_requests = max_requests
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()

    def acquire(self) -> None:
        """リクエストを1回送ってよい状態になるまで待ち、送った時刻を記録する。"""
        while True:
            now = self._clock()
            while self._sent and self._sent[0] <= now - self.period:
                self._sent.popleft()
            if len(self._sent) < self.max_requests:
                self._sent.append(now)
                return
            # 一番古いリクエストが窓から出るまで待つ(少しだけ余裕を持たせる)
            self._sleep(self._sent[0] + self.period - now + 0.5)


# --- クライアント -------------------------------------------------------------------


class JQuantsClient:
    """J-Quants API を呼ぶ薄いクライアント。ページング・レート制限・429 の待機をまとめて扱う。"""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        requests_per_minute: int = FREE_PLAN_REQUESTS_PER_MINUTE,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise DataSourceNotConfiguredError(
                "J-Quants の APIキーが設定されていません。.env に JQUANTS_API_KEY を書いてください"
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._limiter = RateLimiter(requests_per_minute, clock=clock, sleep=sleep)
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._http = httpx.Client(transport=transport, timeout=timeout)

    def __repr__(self) -> str:  # APIキーを表示しない
        return f"JQuantsClient(base_url={self._base_url!r}, api_key=***)"

    def close(self) -> None:
        self._http.close()

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***") if self._api_key else text

    def get_all(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        parse_float: Callable[[str], Any] | None = None,
    ) -> list[dict[str, Any]]:
        """ページングをたどって data をすべて集める。parse_float=str にすると、数値を元の文字列のまま受け取れる。"""
        query = dict(params or {})
        items: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        while True:
            payload = self._request(path, query, parse_float=parse_float)
            items.extend(payload.get("data", []))
            next_key = payload.get("pagination_key")
            if not next_key:
                return items
            if next_key in seen_keys:  # 同じキーが返り続けたら無限ループになるので止める
                raise DataSourceRequestError("J-Quants API のページングが正しく進みませんでした")
            seen_keys.add(next_key)
            query["pagination_key"] = next_key

    def _request(
        self,
        path: str,
        params: dict[str, str],
        *,
        parse_float: Callable[[str], Any] | None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        for attempt in range(1, self._max_attempts + 1):
            last_attempt = attempt == self._max_attempts
            self._limiter.acquire()
            try:
                response = self._http.get(url, params=params, headers={"x-api-key": self._api_key})
            except httpx.TransportError:
                if last_attempt:
                    raise DataSourceRequestError(
                        "J-Quants API に接続できませんでした。ネットワークを確認してください"
                    ) from None
                self._sleep(2.0**attempt)
                continue

            status = response.status_code
            if status == 200:
                return json.loads(response.text, parse_float=parse_float)
            if status == 429:
                if last_attempt:
                    raise RateLimitExceededError(
                        "J-Quants API のリクエスト数の上限に達しました。1分以上待ってから、もう一度試してください"
                    )
                self._sleep(WAIT_AFTER_429_SECONDS)
                continue
            if status in (401, 403):
                raise DataSourceNotConfiguredError(
                    "J-Quants API の認証に失敗しました。.env の JQUANTS_API_KEY が正しいか確認してください"
                )
            if status == 400:
                raise DataSourceRequestError(
                    f"J-Quants API がリクエストを受け付けませんでした: {self._error_message(response)}"
                )
            if status >= 500 and not last_attempt:
                self._sleep(2.0**attempt)
                continue
            raise DataSourceRequestError(f"J-Quants API がエラーを返しました(HTTP {status})")
        raise AssertionError("ここには来ない")  # pragma: no cover

    def _error_message(self, response: httpx.Response) -> str:
        try:
            message = str(response.json().get("message", ""))
        except ValueError, AttributeError:
            message = ""
        return self._redact(message) or f"HTTP {response.status_code}"

    # --- エンドポイント ---

    def daily_bars(
        self,
        *,
        code: str | None = None,
        date: dt.date | None = None,
        start: dt.date | None = None,
        end: dt.date | None = None,
        parse_float: Callable[[str], Any] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if code:
            params["code"] = code
        if date:
            params["date"] = date.isoformat()
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        if not params:
            raise ValueError("code か date のどちらかは指定してください")
        return self.get_all("/equities/bars/daily", params, parse_float=parse_float)

    def master(self, *, date: dt.date | None = None) -> list[dict[str, Any]]:
        params = {"date": date.isoformat()} if date else {}
        return self.get_all("/equities/master", params)

    def calendar(self, *, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
        return self.get_all("/markets/calendar", {"from": start.isoformat(), "to": end.isoformat()})


# --- データソース -------------------------------------------------------------------


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class JQuantsDataSource:
    """J-Quants のデータを data/jquants に保存しながら使うデータソース。

    - 日足は銘柄ごとに「取得できる全期間」をまとめて取り、保存する(Free は約2年分で、1回か2回のリクエストで済む)
    - 保存してから max_age より古くなったら取り直す。過去データの訂正(docs/mvp.md 3.1)も、取り直しで反映される
    - APIキーがなくても、保存済みのデータは読める(client=None)
    """

    source_id = SOURCE_ID
    source_label = SOURCE_LABEL
    markets = ("TSE",)

    def __init__(
        self,
        client: JQuantsClient | None,
        store: ParquetStore,
        *,
        max_age: dt.timedelta = dt.timedelta(days=7),
        now: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._client = client
        self._store = store
        self._max_age = max_age
        self._now = now

    @property
    def has_client(self) -> bool:
        return self._client is not None

    # --- 銘柄一覧 ---

    def list_symbols(self) -> list[SymbolInfo]:
        symbols = self._store.read_symbols()
        if symbols is not None:
            return symbols
        # 銘柄一覧はページ数が多く時間がかかることがあるので、画面からは取りにいかない
        cached = [
            SymbolInfo(symbol_id=symbol_id, name=symbol_id.code)
            for symbol_id in self._store.cached_symbol_ids()
        ]
        return cached

    def refresh_symbols(self) -> list[SymbolInfo]:
        client = self._require_client()
        symbols = [s for s in (parse_symbol(item) for item in client.master()) if s is not None]
        symbols.sort(key=lambda s: s.symbol_id)
        self._store.write_symbols(symbols, self._now())
        return symbols

    # --- 日足 ---

    def get_daily_bars(
        self,
        symbol_id: SymbolId,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[DailyBar]:
        return filter_bars(self._ensure_bars(symbol_id), start, end)

    def refresh_bars(self, symbol_id: SymbolId) -> list[DailyBar]:
        client = self._require_client()
        items = client.daily_bars(code=to_jquants_code(symbol_id))
        bars = sorted((parse_daily_bar(item) for item in items), key=lambda b: b.date)
        if not bars:
            raise SymbolNotFoundError(
                f"J-Quants から {symbol_id} のデータを取得できませんでした(上場していない銘柄の可能性があります)"
            )
        self._store.write_bars(symbol_id, bars, self._now())
        return bars

    def _ensure_bars(self, symbol_id: SymbolId) -> list[DailyBar]:
        self._check_market(symbol_id)
        cached = self._store.read_bars(symbol_id)
        fetched_at = self._store.bars_fetched_at(symbol_id)
        is_fresh = fetched_at is not None and self._now() - fetched_at <= self._max_age
        if cached is not None and (is_fresh or self._client is None):
            return cached
        return self.refresh_bars(symbol_id)

    def get_available_range(self, symbol_id: SymbolId) -> DateRange:
        bars = self._ensure_bars(symbol_id)
        return DateRange(bars[0].date, bars[-1].date)

    def get_data_info(self, symbol_id: SymbolId) -> DataInfo:
        self._check_market(symbol_id)
        return DataInfo(
            source_id=SOURCE_ID,
            source_label=SOURCE_LABEL,
            license_note=LICENSE_NOTE,
            fetched_at=self._store.bars_fetched_at(symbol_id),
        )

    # --- 内部 ---

    def _require_client(self) -> JQuantsClient:
        if self._client is None:
            raise DataSourceNotConfiguredError(
                "J-Quants の APIキーが設定されていないため、データを取得できません。.env に JQUANTS_API_KEY を書いてください"
            )
        return self._client

    @staticmethod
    def _check_market(symbol_id: SymbolId) -> None:
        if symbol_id.market != "TSE":
            raise SymbolNotFoundError(f"J-Quants は東証の銘柄だけを扱います: {symbol_id}")
