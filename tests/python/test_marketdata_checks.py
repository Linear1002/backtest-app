"""「要確認」チェック(backend/marketdata/checks.py)のテスト。本物の API には接続しない。"""

import datetime as dt

import httpx

from backend.marketdata.checks import pick_dates, scan_assumptions
from backend.marketdata.jquants import JQuantsClient


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_pick_dates_uses_second_to_last_business_day() -> None:
    days = [dt.date(2025, 3, d) for d in (25, 26, 27, 28, 31)] + [
        dt.date(2025, 4, d) for d in (24, 25, 28, 30)
    ]
    assert pick_dates(days, 12) == [dt.date(2025, 3, 28), dt.date(2025, 4, 28)]
    assert pick_dates(days, 1) == [dt.date(2025, 4, 28)]


def test_scan_reports_digits_halted_days_and_unknown_types() -> None:
    calendar = [
        {"Date": "2025-03-27", "HolDiv": "1"},
        {"Date": "2025-03-28", "HolDiv": "1"},
        {"Date": "2025-03-29", "HolDiv": "0"},
        {"Date": "2025-03-31", "HolDiv": "1"},
    ]
    bars = (
        '{"data": ['
        '{"Code": "11110", "Date": "2025-03-28", "O": 10.0, "H": 10.0, "L": 10.0, "C": 10.0, "AdjFactor": 1.0, "ExRT": null},'
        '{"Code": "22220", "Date": "2025-03-28", "O": 5.0, "H": 5.0, "L": 5.0, "C": 5.0, "AdjFactor": 0.333333, "ExRT": "1"},'
        '{"Code": "33330", "Date": "2025-03-28", "O": null, "H": null, "L": null, "C": null, "AdjFactor": 0.5, "ExRT": "1"},'
        '{"Code": "44440", "Date": "2025-03-28", "O": 7.0, "H": 7.0, "L": 7.0, "C": 7.0, "AdjFactor": 0.9, "ExRT": null},'
        '{"Code": "55550", "Date": "2025-03-28", "O": 7.0, "H": 7.0, "L": 7.0, "C": 7.0, "AdjFactor": 0.7071067, "ExRT": "9"}'
        "]}"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/markets/calendar"):
            return httpx.Response(200, json={"data": calendar})
        assert request.url.params["date"] == "2025-03-28"
        return httpx.Response(200, text=bars)

    clock = _Clock()
    client = JQuantsClient(
        "key", transport=httpx.MockTransport(handler), clock=clock, sleep=clock.sleep
    )
    report = scan_assumptions(client, months=24, progress=lambda _: None)

    assert report.dates == [dt.date(2025, 3, 28)]
    assert report.records == 5
    assert report.max_decimals == 7
    assert (
        report.halted == 1 and report.halted_with_action == 1 and report.halted_without_factor == 0
    )
    assert report.missing_ex_rt == [("44440", "2025-03-28", "0.9")]
    assert report.ex_rt_counts == {"1": 2, "9": 1}
    text = "\n".join(report.lines())
    assert "想定外の ExRT" in text and "0.333333" in text
