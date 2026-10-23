"""環境変数から設定を読む。

.env(Git管理外)があれば読み込む。APIキーの値はこのモジュールの外に文字列として出さない
(Settings の repr にも出さない)。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    jquants_api_key: str | None = field(default=None, repr=False)
    jquants_requests_per_minute: int = 5
    jquants_max_age_days: int = 7
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    @property
    def jquants_configured(self) -> bool:
        return bool(self.jquants_api_key)


def load_settings(*, env_file: Path | None = None) -> Settings:
    """環境変数(と .env)から設定を作る。すでに環境変数にある値は .env で上書きしない。"""
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    data_dir = Path(os.environ.get("BACKTEST_DATA_DIR") or REPO_ROOT / "data")
    origins = os.environ.get("BACKTEST_CORS_ORIGINS")
    return Settings(
        data_dir=data_dir,
        jquants_api_key=os.environ.get("JQUANTS_API_KEY") or None,
        jquants_requests_per_minute=int(os.environ.get("JQUANTS_REQUESTS_PER_MINUTE", "5")),
        jquants_max_age_days=int(os.environ.get("JQUANTS_MAX_AGE_DAYS", "7")),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip())
        if origins
        else Settings.cors_origins,
    )
