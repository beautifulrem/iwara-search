from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path
    page_size: int = 36
    request_timeout_seconds: float = 30.0
    request_retries: int = 3
    request_concurrency: int = 4
    request_delay_seconds: float = 0.35
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )


def default_db_path() -> Path:
    return PROJECT_ROOT / "data" / "oreno3d.sqlite3"


@lru_cache(maxsize=1)
def get_settings(db_path: str | Path | None = None) -> Settings:
    raw_path = db_path or os.getenv("SEARCH_IWARA_DB") or default_db_path()
    path = Path(raw_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(db_path=path)
