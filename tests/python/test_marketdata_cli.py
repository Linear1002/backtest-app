"""株価データのコマンド(python -m backend.marketdata)のテスト。本物の J-Quants には接続しない。"""

from __future__ import annotations

import datetime as dt

import pytest

from backend.marketdata import __main__ as cli
from backend.marketdata.models import DailyBar, SymbolId
from backend.marketdata.source import DataSourceRequestError
from backend.settings import Settings


def bar(day: str) -> DailyBar:
    return DailyBar(dt.date.fromisoformat(day), 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, None)


class FakeSource:
    has_client = True

    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.fetched: list[str] = []

    def refresh_bars(self, symbol_id: SymbolId) -> list[DailyBar]:
        if str(symbol_id) in self.failing:
            raise DataSourceRequestError("J-Quants API がエラーを返しました(HTTP 503)")
        self.fetched.append(str(symbol_id))
        return [bar("2024-01-04"), bar("2024-01-05")]


def test_fetch_continues_after_a_failure_and_summarizes(monkeypatch, capsys, tmp_path) -> None:
    fake = FakeSource({"TSE:6758"})
    monkeypatch.setattr(
        cli, "load_settings", lambda: Settings(data_dir=tmp_path, jquants_api_key="x")
    )
    monkeypatch.setattr(cli, "_jquants", lambda settings: fake)
    code = cli.main(["fetch", "TSE:7203", "TSE:6758", "TSE:9432", "abc"])
    assert code == 1
    assert fake.fetched == ["TSE:7203", "TSE:9432"]  # 途中で失敗しても残りは取る
    err = capsys.readouterr().err
    assert "取得できなかった銘柄が 2 件あります" in err
    assert "TSE:6758" in err and "abc" in err


def test_info_does_not_fetch_for_tse(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=tmp_path))
    code = cli.main(["info", "TSE:7203"])
    assert code == 1
    assert "保存されていません" in capsys.readouterr().err


def test_info_for_demo(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=tmp_path))
    assert cli.main(["info", "DEMO:1003"]) == 0
    out = capsys.readouterr().out
    assert "権利落ち: 2025-04-01 分割 調整係数=0.5" in out


@pytest.mark.parametrize("argv", [["fetch"], ["unknown"]])
def test_bad_arguments_exit_with_usage(argv) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2
