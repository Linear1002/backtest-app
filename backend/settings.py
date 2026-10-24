"""環境変数から設定を読む。

.env(Git管理外)があれば読み込む。APIキーの値はこのモジュールの外に文字列として出さない
(Settings の repr にも出さない)。

.env.example のように「KEY=」と値を空にした行は、書いていないのと同じ扱い(既定値を使う)にする。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


class SettingsError(ValueError):
    """設定の値が正しくない。メッセージは画面やターミナルにそのまま出せる日本語。"""


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    jquants_api_key: str | None = field(default=None, repr=False)
    jquants_requests_per_minute: int = 5
    jquants_max_age_days: int = 7
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    sweep_workers: int | None = None  # 総当たりに使うプロセスの数(None は CPU のコアの数)

    @property
    def jquants_configured(self) -> bool:
        return bool(self.jquants_api_key)


def _env(name: str) -> str | None:
    """環境変数の値。空文字や空白だけのときは、設定されていないものとして None を返す。"""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _positive_int(name: str, default: int) -> int:
    text = _env(name)
    if text is None:
        return default
    try:
        value = int(text)
    except ValueError:
        raise SettingsError(f"{name} は1以上の整数で書いてください(いまの値:{text!r})") from None
    if value < 1:
        raise SettingsError(f"{name} は1以上の整数で書いてください(いまの値:{text!r})")
    return value


def load_settings(*, env_file: Path | None = None) -> Settings:
    """環境変数(と .env)から設定を作る。すでに環境変数にある値は .env で上書きしない。"""
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    data_dir = Path(_env("BACKTEST_DATA_DIR") or REPO_ROOT / "data")
    origins = _env("BACKTEST_CORS_ORIGINS")
    return Settings(
        data_dir=data_dir,
        jquants_api_key=_env("JQUANTS_API_KEY"),
        jquants_requests_per_minute=_positive_int("JQUANTS_REQUESTS_PER_MINUTE", 5),
        jquants_max_age_days=_positive_int("JQUANTS_MAX_AGE_DAYS", 7),
        sweep_workers=_positive_int("BACKTEST_SWEEP_WORKERS", 0) or None,
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip())
        if origins
        else Settings.cors_origins,
    )
