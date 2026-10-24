"""J-Quants API(V2)のクライアントとデータソース。

公式仕様(2026年10月に確認):
- 日足:GET /v2/equities/bars/daily  https://jpx-jquants.com/en/spec/eq-bars-daily
- 銘柄一覧:GET /v2/equities/master  https://jpx-jquants.com/en/spec/eq-master
- 取引カレンダー:GET /v2/markets/calendar  https://jpx-jquants.com/en/spec/mkt-cal
- 認証:APIキーを x-api-key ヘッダーで渡す
- 続きがあるときは、レスポンスに pagination_key が入る
- リクエスト数の上限:Free は1分間に5回(1分間のスライディングウィンドウ)。超えると 429(Retry-After ヘッダーなし)。
  429 も回数に数えられ、大きく超え続けると5分程度すべてのリクエストがエラーになる。
  429 のあとは「1分以上(確実を期す場合は2分程度)待機」が推奨  https://jpx-jquants.com/ja/spec/rate-limits

利用規約上、データは私的使用のみ(docs/mvp.md 3.2)。取得したデータは data/ に保存し、Git やアプリ経由で配布しない。
APIキーは例外メッセージ・ログ・repr に絶対に出さない。

API サーバーは複数のリクエストを同時に(別々のスレッドで)処理する。リクエスト数の数え方と、
同じ銘柄の取り直しが重ならないようにする仕組みは、スレッドの間で共有している。
"""

from __future__ import annotations

import datetime as dt
import json
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx

from backend.marketdata.models import DailyBar, DataInfo, DateRange, SymbolId, SymbolInfo
from backend.marketdata.source import (
    DataSourceNotConfiguredError,
    DataSourceRequestError,
    MarketDataError,
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

# 429 が返ったあとに待つ秒数。公式の推奨「1分以上(ウィンドウがスライドするため、確実を期す場合は2分程度)」の
# 確実なほうに合わせる。早く再送すると、その 429 も回数に数えられて、制限が解けるのが遅くなる
WAIT_AFTER_429_SECONDS = 120.0

# 画面から来たリクエストで待ってよい最長の秒数。これより長く待つ必要があるときは、待たずに目安を伝える
INTERACTIVE_MAX_WAIT_SECONDS = 15.0

JST = dt.timezone(dt.timedelta(hours=9), "JST")


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


def _short(value: Any) -> str:
    """エラーメッセージに入れる値を短くする(長い応答をそのまま画面に出さないため)。"""
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        raise DataSourceRequestError(
            f"J-Quants の応答に、数値として読めない値がありました: {_short(value)}"
        ) from None


def _flag(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return str(value) == "1"


def _ex_rt(value: Any) -> int | None:
    """権利落ちの種類。"1" のような文字列も、1.0 のような小数の形も受け付ける。"""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        number = math.nan
    if not number.is_integer():
        raise DataSourceRequestError(
            f"J-Quants の日足の権利落ちの種類(ExRT)を読めませんでした: {_short(value)}"
        )
    return int(number)


def parse_daily_bar(item: dict[str, Any]) -> DailyBar:
    """日足の1レコードを共通形式に変換する。"""
    try:
        date = dt.date.fromisoformat(str(item["Date"]))
    except KeyError, ValueError:
        raise DataSourceRequestError(
            f"J-Quants の日足の日付を読めませんでした: {_short(item.get('Date'))}"
        ) from None
    return DailyBar(
        date=date,
        open=_number(item.get("O")),
        high=_number(item.get("H")),
        low=_number(item.get("L")),
        close=_number(item.get("C")),
        volume=_number(item.get("Vo")),
        turnover=_number(item.get("Va")),
        adj_factor=_number(item.get("AdjFactor")),
        ex_rt=_ex_rt(item.get("ExRT")),
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


def _wait_text(seconds: float) -> str:
    """待つ時間の目安を短く書く(90秒未満は秒、それ以上は分。どちらも切り上げ)。"""
    if seconds < 90:
        return f"約{math.ceil(seconds)}秒"
    return f"約{math.ceil(seconds / 60)}分"


class RateLimiter:
    """直近 period 秒のリクエスト数が max_requests を超えないように待つ(スライディングウィンドウ)。

    スレッドの間で共有してよい。429 を受けたら block_for で「この時刻までは誰も送らない」を記録する。
    数えているのはこのプロセスの中だけ(API サーバーと make data-check を同時に動かすと、別々に数える)。
    """

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
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def block_for(self, seconds: float) -> None:
        """いまから seconds 秒のあいだ、どのスレッドもリクエストを送らないようにする(429 を受けたとき)。"""
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._clock() + seconds)

    def _wait_needed(self, now: float) -> float:
        while self._sent and self._sent[0] <= now - self.period:
            self._sent.popleft()
        if now < self._blocked_until:
            return self._blocked_until - now
        if len(self._sent) >= self.max_requests:
            # 一番古いリクエストが窓から出るまで待つ(少しだけ余裕を持たせる)
            return self._sent[0] + self.period - now + 0.5
        return 0.0

    def acquire(self, *, max_wait: float | None = None) -> None:
        """リクエストを1回送ってよい状態になるまで待ち、送った時刻を記録する。

        max_wait(秒)を超えて待つ必要があるときは、待たずに RateLimitExceededError を投げる
        (画面からのリクエストで、何分も待たせないため)。
        """
        started = self._clock()
        while True:
            with self._lock:
                now = self._clock()
                wait = self._wait_needed(now)
                if wait <= 0:
                    self._sent.append(now)
                    return
            if max_wait is not None and (now - started) + wait > max_wait:
                raise RateLimitExceededError(
                    f"J-Quants API のリクエスト数の上限(1分あたり{self.max_requests}回)に達しています。"
                    f"{_wait_text(wait)}後に、もう一度試してください"
                )
            self._sleep(wait)


# --- クライアント -------------------------------------------------------------------


class JQuantsClient:
    """J-Quants API を呼ぶ薄いクライアント。ページング・レート制限・429 の待機をまとめて扱う。

    max_wait:リクエスト数の上限で待つ最長の秒数。None なら必要なだけ待つ(コマンドから使うとき)。
    画面から使う API サーバーでは INTERACTIVE_MAX_WAIT_SECONDS を渡し、長く待たせない。
    """

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
        max_wait: float | None = None,
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
        self._max_wait = max_wait
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
            data = payload.get("data", [])
            if not isinstance(data, list):
                raise DataSourceRequestError(
                    "J-Quants API の応答の形が想定と違いました(data が一覧ではありません)"
                )
            items.extend(data)
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
            self._limiter.acquire(max_wait=self._max_wait)
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
                return self._parse_json(response, parse_float)
            if status == 429:
                # 429 も回数に数えられるので、ほかのスレッドも含めて全員がしばらく送らない
                self._limiter.block_for(WAIT_AFTER_429_SECONDS)
                interactive = self._max_wait is not None and self._max_wait < WAIT_AFTER_429_SECONDS
                if last_attempt or interactive:
                    raise RateLimitExceededError(
                        "J-Quants API のリクエスト数の上限に達しました。"
                        f"{_wait_text(WAIT_AFTER_429_SECONDS)}待ってから、もう一度試してください"
                    )
                continue  # 次の acquire が、block_for の時刻まで待つ
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

    @staticmethod
    def _parse_json(
        response: httpx.Response, parse_float: Callable[[str], Any] | None
    ) -> dict[str, Any]:
        try:
            payload = json.loads(response.text, parse_float=parse_float)
        except ValueError, httpx.DecodingError:
            raise DataSourceRequestError(
                "J-Quants API の応答を読み取れませんでした(JSON の形式ではありません)。時間をおいて試してください"
            ) from None
        if not isinstance(payload, dict):
            raise DataSourceRequestError("J-Quants API の応答の形が想定と違いました")
        return payload

    def _error_message(self, response: httpx.Response) -> str:
        try:
            message = str(response.json().get("message", ""))
        except (
            ValueError,
            AttributeError,
        ):  # Python 3.14 から、括弧なしで複数の例外を書ける(PEP 758)
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
        if not code and not date:
            raise ValueError("code か date のどちらかは指定してください")
        params: dict[str, str] = {}
        if code:
            params["code"] = code
        if date:
            params["date"] = date.isoformat()
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        return self.get_all("/equities/bars/daily", params, parse_float=parse_float)

    def master(self, *, date: dt.date | None = None) -> list[dict[str, Any]]:
        params = {"date": date.isoformat()} if date else {}
        return self.get_all("/equities/master", params)

    def calendar(self, *, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
        return self.get_all("/markets/calendar", {"from": start.isoformat(), "to": end.isoformat()})


# --- データソース -------------------------------------------------------------------


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def merge_bars(old: list[DailyBar] | None, new: list[DailyBar]) -> list[DailyBar]:
    """保存済みの日足と、新しく取った日足を合わせる。

    - 同じ日付は新しい方を使う(J-Quants 側の訂正を反映するため)
    - 新しく取れなかった古い日付は残す(Free プランは「直近の約2年」なので、取れる期間が少しずつ後ろへずれる。
      取り直しのたびに古い日付が消えると、前と同じ条件のバックテストを再現できなくなるため)
    """
    merged = {bar.date: bar for bar in old or []}
    merged.update({bar.date: bar for bar in new})
    return [merged[day] for day in sorted(merged)]


class JQuantsDataSource:
    """J-Quants のデータを data/jquants に保存しながら使うデータソース。

    - 日足は銘柄ごとに「取得できる全期間」をまとめて取り、保存済みのデータに合わせて保存する(merge_bars)
    - 保存してから max_age より古くなったら取り直す。過去データの訂正(docs/mvp.md 3.1)も、取り直しで反映される
    - 取り直しに失敗したら、保存済みのデータで続け、その旨を get_data_info の warning で伝える
    - APIキーがなくても、保存済みのデータは読める(client=None)
    """

    source_id = SOURCE_ID
    source_label = SOURCE_LABEL
    license_note = LICENSE_NOTE
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
        self._locks: dict[SymbolId, Any] = {}  # 銘柄ごとの RLock(取り直しが重ならないように)
        self._locks_guard = threading.Lock()
        self._warnings: dict[SymbolId, str] = {}

    @property
    def has_client(self) -> bool:
        return self._client is not None

    @property
    def can_fetch(self) -> bool:
        return self.has_client

    # --- 銘柄一覧 ---

    def list_symbols(self) -> list[SymbolInfo]:
        symbols = self._store.read_symbols()
        if symbols is not None:
            return symbols
        # 銘柄一覧はページ数が多く時間がかかることがあるので、画面からは取りにいかない
        return [
            SymbolInfo(symbol_id=symbol_id, name=symbol_id.code)
            for symbol_id in self._store.cached_symbol_ids()
        ]

    def refresh_symbols(self) -> list[SymbolInfo]:
        client = self._require_client()
        symbols = [s for s in (parse_symbol(item) for item in client.master()) if s is not None]
        symbols.sort(key=lambda s: s.symbol_id)
        self._store.write_symbols(symbols, self._now())
        return symbols

    def describe(self, symbol_id: SymbolId) -> str | None:
        return None

    def check_listed(self, symbol_id: SymbolId) -> None:
        """銘柄一覧(make data-symbols)を取得してあれば、そこに載っている銘柄か確かめる。

        一覧は「いま上場している普通株」なので、載っていなければ上場廃止などで MVP の対象外(docs/mvp.md 3.6)。
        一覧をまだ取得していないときは確かめようがないので、通す(docs/data.md に注意を書いてある)。
        """
        self._check_market(symbol_id)
        symbols = self._store.read_symbols()
        if symbols is None:
            return
        if all(info.symbol_id != symbol_id for info in symbols):
            raise SymbolNotFoundError(
                f"{symbol_id} は銘柄一覧(現在上場している普通株)にありません。"
                "上場廃止の銘柄は、いまは扱えません(生存者バイアスの扱いを決めてから対応します)"
            )

    # --- 日足 ---

    def get_daily_bars(
        self,
        symbol_id: SymbolId,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[DailyBar]:
        return filter_bars(self._ensure_bars(symbol_id), start, end)

    def read_cached_bars(self, symbol_id: SymbolId) -> list[DailyBar] | None:
        """保存済みの日足だけを読む(古くても取り直さない)。保存されていなければ None。"""
        self._check_market(symbol_id)
        return self._store.read_bars(symbol_id)

    def refresh_bars(self, symbol_id: SymbolId) -> list[DailyBar]:
        """J-Quants から取得できる全期間を取り直し、保存済みのデータに合わせて保存する。"""
        self._check_market(symbol_id)
        client = self._require_client()
        with self._lock_for(symbol_id):
            items = client.daily_bars(code=to_jquants_code(symbol_id))
            new = sorted((parse_daily_bar(item) for item in items), key=lambda b: b.date)
            if not new:
                raise SymbolNotFoundError(
                    f"J-Quants から {symbol_id} のデータを取得できませんでした(上場していない銘柄の可能性があります)"
                )
            bars = merge_bars(self._store.read_bars(symbol_id), new)
            self._store.write_bars(symbol_id, bars, self._now())
            self._warnings.pop(symbol_id, None)
            return bars

    def _is_fresh(self, symbol_id: SymbolId) -> bool:
        fetched_at = self._store.bars_fetched_at(symbol_id)
        return fetched_at is not None and self._now() - fetched_at <= self._max_age

    def _ensure_bars(self, symbol_id: SymbolId) -> list[DailyBar]:
        self._check_market(symbol_id)
        cached = self._store.read_bars(symbol_id)
        if cached is not None and (self._client is None or self._is_fresh(symbol_id)):
            return cached
        with self._lock_for(symbol_id):
            # ロックを待っているあいだに、別のスレッドが取り直したかもしれないので、もう一度確かめる
            cached = self._store.read_bars(symbol_id)
            if cached is not None and (self._client is None or self._is_fresh(symbol_id)):
                return cached
            try:
                return self.refresh_bars(symbol_id)
            except SymbolNotFoundError:
                raise
            except MarketDataError as error:
                if cached is None:
                    raise
                # 取り直せなくても、保存済みのデータがあればそれで続ける(古いことは画面で伝える)
                fetched_at = self._store.bars_fetched_at(symbol_id)
                when = (
                    fetched_at.astimezone(JST).strftime("%Y-%m-%d %H:%M") if fetched_at else "以前"
                )
                self._warnings[symbol_id] = (
                    f"最新のデータを取得できなかったため、{when} に取得したデータで計算しました({error})"
                )
                return cached

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
            warning=self._warnings.get(symbol_id),
        )

    # --- 内部 ---

    def _lock_for(self, symbol_id: SymbolId) -> Any:
        # RLock:_ensure_bars がロックを持ったまま refresh_bars を呼ぶので、同じスレッドからは何度でも取れるもの
        with self._locks_guard:
            return self._locks.setdefault(symbol_id, threading.RLock())

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
