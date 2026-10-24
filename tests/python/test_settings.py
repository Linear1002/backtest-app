"""設定の読み込み(backend/settings.py)のテスト。.env.example のように値を空にした行も扱えること。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.settings import Settings, SettingsError, load_settings

VARIABLES = (
    "JQUANTS_API_KEY",
    "JQUANTS_REQUESTS_PER_MINUTE",
    "JQUANTS_MAX_AGE_DAYS",
    "BACKTEST_DATA_DIR",
    "BACKTEST_CORS_ORIGINS",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def write_env(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_nothing_is_set(tmp_path: Path) -> None:
    settings = load_settings(env_file=tmp_path / "missing.env")
    assert settings.jquants_api_key is None
    assert settings.jquants_requests_per_minute == 5
    assert settings.jquants_max_age_days == 7
    assert settings.cors_origins == Settings.cors_origins


def test_empty_values_from_env_example_mean_default(tmp_path: Path) -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    settings = load_settings(env_file=write_env(tmp_path, example))
    assert settings.jquants_api_key is None
    assert settings.jquants_requests_per_minute == 5
    assert settings.jquants_max_age_days == 7
    assert settings.data_dir.name == "data"


def test_values_are_read(tmp_path: Path) -> None:
    env = write_env(
        tmp_path,
        "JQUANTS_API_KEY=abc\nJQUANTS_REQUESTS_PER_MINUTE=60\nJQUANTS_MAX_AGE_DAYS= 3 \n"
        f"BACKTEST_DATA_DIR={tmp_path / 'store'}\nBACKTEST_CORS_ORIGINS=http://a:1, http://b:2\n",
    )
    settings = load_settings(env_file=env)
    assert settings.jquants_configured
    assert settings.jquants_requests_per_minute == 60
    assert settings.jquants_max_age_days == 3
    assert settings.data_dir == tmp_path / "store"
    assert settings.cors_origins == ("http://a:1", "http://b:2")


@pytest.mark.parametrize("value", ["abc", "0", "-1", "1.5"])
def test_invalid_numbers_are_explained_in_japanese(tmp_path: Path, value: str) -> None:
    env = write_env(tmp_path, f"JQUANTS_REQUESTS_PER_MINUTE={value}\n")
    with pytest.raises(SettingsError) as error:
        load_settings(env_file=env)
    assert "JQUANTS_REQUESTS_PER_MINUTE は1以上の整数で書いてください" in str(error.value)


def test_api_key_is_not_in_repr(tmp_path: Path) -> None:
    settings = load_settings(env_file=write_env(tmp_path, "JQUANTS_API_KEY=very-secret\n"))
    assert "very-secret" not in repr(settings)
