"""パラメータの定義と入力チェックを、画面(frontend)と API でそろえるためのテスト。

- tests/fixtures/ma_cross_params.json:API が返す移動平均クロスのパラメータの定義(GET /api/strategies)。
  画面のテスト(frontend/lib/testing.ts)はこのファイルを読むので、定義を変えたら作り直す:
      uv run python -m tests.python.test_param_contract
- tests/fixtures/param_messages.json:入力 → 誤りのメッセージ の表。画面のテストも同じ表を読む
- tests/fixtures/period_messages.json:期間の入力 → 誤りのメッセージ の表。画面のテストも同じ表を読む
- tests/fixtures/sweep_messages.json:総当たりの格子の入力 → 誤りのメッセージ・組み合わせの数 の表(docs/sweep.md)
- tests/fixtures/walkforward_messages.json:ウォークフォワードの設定・区切り・計算の量 → 誤りのメッセージ の表(docs/walkforward.md)
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from backend.api.schemas import MaCrossParamsIn, ParamOut, SweepCostsIn, SweepGridIn
from backend.api.validation import (
    InputValidationError,
    check_walkforward_runs,
    validate_params,
    validate_period,
    validate_sweep_inputs,
    walkforward_settings_errors,
)
from backend.marketdata.models import DateRange, SymbolId
from backend.marketdata.synthetic import generate_bars
from backend.strategies import STRATEGIES_BY_ID
from engine.reference.walkforward import WalkForwardSettings, calendar_windows, no_windows_error

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PARAMS_FILE = FIXTURES / "ma_cross_params.json"
MESSAGES = json.loads((FIXTURES / "param_messages.json").read_text(encoding="utf-8"))["cases"]
DEFAULTS = {
    "short_window": 5,
    "long_window": 25,
    "fee_rate_pct": 0.1,
    "slippage_rate_pct": 0.05,
    "initial_cash": 1_000_000,
}


def served_params() -> list[dict]:
    """GET /api/strategies が返す ma_cross のパラメータ(routes.strategies と同じ作り方)。"""
    spec = STRATEGIES_BY_ID["ma_cross"]
    return [ParamOut(**vars(p)).model_dump(mode="json") for p in spec.params]


def test_params_fixture_matches_api() -> None:
    saved = json.loads(PARAMS_FILE.read_text(encoding="utf-8"))
    assert saved == served_params(), (
        "パラメータの定義が変わりました。"
        "uv run python -m tests.python.test_param_contract で tests/fixtures/ma_cross_params.json を作り直してください"
    )


@pytest.mark.parametrize(
    "case",
    [c for c in MESSAGES if not c["frontend_only"]],
    ids=lambda c: json.dumps(c["params"], ensure_ascii=False),
)
def test_api_gives_the_same_message_as_the_screen(case: dict) -> None:
    raw = MaCrossParamsIn(**{**DEFAULTS, **{k: float(v) for k, v in case["params"].items()}})
    market = SymbolId.parse("DEMO:1001").market_config
    if case["field"] is None:
        validate_params(raw, market)
        return
    with pytest.raises(InputValidationError) as caught:
        validate_params(raw, market)
    # 表で指定した欄だけに、その文が出る(ほかの欄に余計な誤りが出ていないことも確かめる)
    assert {e.field: e.message for e in caught.value.errors} == {case["field"]: case["message"]}


PERIODS = json.loads((FIXTURES / "period_messages.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def demo_bars() -> list:
    return list(generate_bars("1001"))


@pytest.mark.parametrize(
    "case",
    [c for c in PERIODS["cases"] if c["only"] != "frontend"],
    ids=lambda c: f"{c['start_date']}..{c['end_date']}",
)
def test_api_gives_the_same_period_message_as_the_screen(case: dict, demo_bars: list) -> None:
    available = DateRange(
        dt.date.fromisoformat(PERIODS["range"]["first_date"]),
        dt.date.fromisoformat(PERIODS["range"]["last_date"]),
    )
    assert (demo_bars[0].date, demo_bars[-1].date) == (available.first, available.last)
    start = dt.date.fromisoformat(case["start_date"])
    end = dt.date.fromisoformat(case["end_date"])
    if case["field"] is None:
        validate_period(start, end, available, demo_bars)
        return
    with pytest.raises(InputValidationError) as caught:
        validate_period(start, end, available, demo_bars)
    assert {e.field: e.message for e in caught.value.errors} == {case["field"]: case["message"]}


SWEEPS = json.loads((FIXTURES / "sweep_messages.json").read_text(encoding="utf-8"))
SWEEP_DEFAULTS = {
    "short_min": 3,
    "short_max": 30,
    "short_step": 3,
    "long_min": 20,
    "long_max": 120,
    "long_step": 10,
}


@pytest.mark.parametrize(
    "case",
    [c for c in SWEEPS["cases"] if not c["frontend_only"]],
    ids=lambda c: json.dumps(c["grid"], ensure_ascii=False),
)
def test_api_gives_the_same_sweep_message_as_the_screen(case: dict) -> None:
    grid_in = SweepGridIn(**{**SWEEP_DEFAULTS, **{k: float(v) for k, v in case["grid"].items()}})
    market = SymbolId.parse("DEMO:1001").market_config
    if not case["errors"]:
        grid, _ = validate_sweep_inputs(grid_in, SweepCostsIn(), market, SWEEPS["max_pairs"])
        assert len(grid.pairs()) == case["pairs"]
        return
    with pytest.raises(InputValidationError) as caught:
        validate_sweep_inputs(grid_in, SweepCostsIn(), market, SWEEPS["max_pairs"])
    assert {e.field: e.message for e in caught.value.errors} == case["errors"]


WALKS = json.loads((FIXTURES / "walkforward_messages.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", WALKS["cases"], ids=lambda c: c["name"])
def test_api_gives_the_same_walkforward_message_as_the_screen(case: dict) -> None:
    """API(POST /api/walkforwards)と同じ順番で確かめる:設定 → 区切り → 計算の量。"""
    walk = {"objective": "sharpe_ratio", "in_sample_months": 24, "out_of_sample_months": 6}
    walk.update(case["walk"])
    errors = {
        e.field: e.message
        for e in walkforward_settings_errors(
            walk["objective"], walk["in_sample_months"], walk["out_of_sample_months"]
        )
    }
    if errors:
        assert case["windows"] is None
        assert errors == case["errors"]
        return
    settings = WalkForwardSettings(**walk)
    windows = calendar_windows(
        dt.date.fromisoformat(case["start"]),
        dt.date.fromisoformat(case["end"]),
        settings.in_sample_months,
        settings.out_of_sample_months,
    )
    assert len(windows) == case["windows"]
    if not windows:
        error = no_windows_error(settings)
        assert {error.field: str(error)} == case["errors"]
        return
    if not case["errors"]:
        check_walkforward_runs(case["pairs"], len(windows), WALKS["max_runs"])
        return
    with pytest.raises(InputValidationError) as caught:
        check_walkforward_runs(case["pairs"], len(windows), WALKS["max_runs"])
    assert {e.field: e.message for e in caught.value.errors} == case["errors"]


def test_walkforward_run_limit_is_twice_the_sweep_limit() -> None:
    from backend.api.routes import walkforward_max_runs

    assert walkforward_max_runs(SWEEPS["max_pairs"]) == WALKS["max_runs"]


if __name__ == "__main__":
    PARAMS_FILE.write_text(
        json.dumps(served_params(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{PARAMS_FILE} を書きました")
