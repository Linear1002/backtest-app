"""株価データを取得・確認するコマンド。

使い方(リポジトリ直下で):
    uv run python -m backend.marketdata symbols            # J-Quants の銘柄一覧を取得して保存
    uv run python -m backend.marketdata fetch TSE:7203     # 日足を取得して保存(複数指定可)
    uv run python -m backend.marketdata info TSE:7203      # 保存済みデータの範囲と権利落ちの一覧
    uv run python -m backend.marketdata info DEMO:1003     # 架空データも見られる
    uv run python -m backend.marketdata check-assumptions  # docs/mvp.md 3.1 の「要確認」を実データで調べる

APIキーは .env の JQUANTS_API_KEY から読む。キーは画面に表示しない。
"""

from __future__ import annotations

import argparse
import sys

from backend.marketdata.checks import scan_assumptions
from backend.marketdata.jquants import JQuantsClient, JQuantsDataSource
from backend.marketdata.models import InvalidSymbolIdError, SymbolId
from backend.marketdata.service import build_jquants_source, build_service
from backend.marketdata.source import MarketDataError
from backend.settings import load_settings

EX_RT_LABELS = {1: "分割", 2: "併合", 3: "株主割当増資"}


def _jquants(settings) -> JQuantsDataSource:
    source = build_jquants_source(settings)
    if source is None or not source.has_client:
        raise MarketDataError(
            "J-Quants の APIキーが設定されていません。.env.example をコピーして .env を作り、JQUANTS_API_KEY を書いてください"
        )
    return source


def cmd_symbols(args: argparse.Namespace) -> int:
    source = _jquants(load_settings())
    print("J-Quants から銘柄一覧を取得しています(数分かかることがあります)...")
    symbols = source.refresh_symbols()
    print(f"{len(symbols)} 銘柄(普通株)を保存しました")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """指定した銘柄を順に取得する。途中の銘柄で失敗しても残りは続け、最後に失敗した銘柄をまとめて表示する。"""
    source = _jquants(load_settings())
    failed: list[tuple[str, str]] = []
    for text in args.symbols:
        try:
            symbol_id = SymbolId.parse(text)
        except InvalidSymbolIdError as error:
            failed.append((text, str(error)))
            continue
        if symbol_id.market != "TSE":
            print(f"{symbol_id}: 東証の銘柄だけ取得できます(DEMO は取得不要です)")
            continue
        print(f"{symbol_id}: 取得しています...")
        try:
            bars = source.refresh_bars(symbol_id)
        except MarketDataError as error:
            print(f"{symbol_id}: 取得できませんでした:{error}", file=sys.stderr)
            failed.append((str(symbol_id), str(error)))
            continue
        halted = sum(1 for bar in bars if bar.close is None)
        print(
            f"{symbol_id}: {bars[0].date}〜{bars[-1].date} の {len(bars)} 営業日を保存しました"
            f"(売買不成立 {halted} 日)"
        )
    if failed:
        print(f"\n取得できなかった銘柄が {len(failed)} 件あります:", file=sys.stderr)
        for name, reason in failed:
            print(f"  - {name}:{reason}", file=sys.stderr)
        return 1
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """保存済みのデータを表示する。J-Quants のデータは取り直さない(古くても、保存されている内容をそのまま見せる)。"""
    settings = load_settings()
    symbol_id = SymbolId.parse(args.symbol)
    if symbol_id.market == "TSE":
        source = build_jquants_source(settings)
        bars = source.read_cached_bars(symbol_id) if source is not None else None
        if not bars:
            raise MarketDataError(
                f"{symbol_id} のデータは保存されていません。make data-fetch SYMBOLS={symbol_id} で取得してください"
            )
        assert source is not None
        info = source.get_data_info(symbol_id)
    else:
        service = build_service(settings)
        bars = service.get_daily_bars(symbol_id)
        info = service.get_data_info(symbol_id)
    print(f"銘柄: {symbol_id}  データソース: {info.source_label}")
    if info.fetched_at:
        print(f"取得日時: {info.fetched_at.isoformat()}")
    print(f"期間: {bars[0].date}〜{bars[-1].date}({len(bars)} 営業日)")
    halted = [bar.date for bar in bars if bar.close is None]
    print(f"売買不成立の日: {len(halted)} 日" + (f"(例: {halted[0]})" if halted else ""))
    actions = [bar for bar in bars if bar.adj_factor != 1.0 or bar.ex_rt is not None]
    if not actions:
        print("権利落ち: なし")
    for bar in actions:
        label = EX_RT_LABELS.get(bar.ex_rt or 0, f"不明({bar.ex_rt})")
        print(f"権利落ち: {bar.date} {label} 調整係数={bar.adj_factor}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    settings = load_settings()
    if not settings.jquants_api_key:
        raise MarketDataError("J-Quants の APIキーが設定されていません(.env の JQUANTS_API_KEY)")
    client = JQuantsClient(
        settings.jquants_api_key, requests_per_minute=settings.jquants_requests_per_minute
    )
    print(
        f"{args.months} か月分を調べます。Free プランでは10分ほどかかります(途中で止めても問題ありません)"
    )
    report = scan_assumptions(client, months=args.months)
    print()
    for line in report.lines():
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.marketdata", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("symbols", help="J-Quants の銘柄一覧を取得して保存する").set_defaults(
        func=cmd_symbols
    )

    fetch = sub.add_parser("fetch", help="J-Quants から日足を取得して保存する")
    fetch.add_argument("symbols", nargs="+", help="銘柄ID(例: TSE:7203)")
    fetch.set_defaults(func=cmd_fetch)

    info = sub.add_parser("info", help="保存済みデータの範囲と権利落ちを表示する")
    info.add_argument("symbol", help="銘柄ID(例: TSE:7203、DEMO:1003)")
    info.set_defaults(func=cmd_info)

    check = sub.add_parser(
        "check-assumptions", help="docs/mvp.md 3.1 の「要確認」を実データで調べる"
    )
    check.add_argument("--months", type=int, default=24, help="調べる月数(既定: 24)")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (MarketDataError, InvalidSymbolIdError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
