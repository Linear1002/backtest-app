"""パラメータの定義と入力チェックを、画面(frontend)と API でそろえるためのテスト。

- tests/fixtures/ma_cross_params.json:API が返す移動平均クロスのパラメータの定義(GET /api/strategies)。
  画面のテスト(frontend/lib/testing.ts)はこのファイルを読むので、定義を変えたら作り直す:
      uv run python -m tests.python.test_param_contract
- tests/fixtures/param_messages.json:入力 → 誤りのメッセージ の表。画面のテストも同じ表を読む
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.api.schemas import MaCrossParamsIn, ParamOut
from backend.api.validation import InputValidationError, validate_params
from backend.marketdata.models import SymbolId
from backend.strategies import STRATEGIES_BY_ID

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
    errors = {e.field: e.message for e in caught.value.errors}
    assert errors.get(case["field"]) == case["message"], errors


if __name__ == "__main__":
    PARAMS_FILE.write_text(
        json.dumps(served_params(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{PARAMS_FILE} を書きました")
