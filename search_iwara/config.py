"""Runtime configuration.

Every setting can be supplied through ``SEARCH_IWARA_*`` environment variables (or an
``.env`` file in the working directory) and is validated once at start-up, so a typo such
as ``SEARCH_IWARA_REQUEST_CONCURRENCY=0`` fails loudly instead of dead-locking a crawl.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from platformdirs import user_data_dir
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import __version__

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
REPOSITORY_URL = "https://github.com/beautifulrem/iwara-search"
DEFAULT_USER_AGENT = f"search-iwara/{__version__} (+{REPOSITORY_URL})"

PositiveInt = Annotated[int, Field(ge=1)]


def default_db_path() -> Path:
    """``./data`` inside a source checkout, otherwise the per-user data directory.

    An installed package (wheel, ``uv tool install``, container) must not write next to
    ``site-packages``; ``platformdirs`` resolves e.g. ``~/.local/share/search-iwara`` on Linux,
    ``~/Library/Application Support/search-iwara`` on macOS and ``%LOCALAPPDATA%`` on Windows.
    """

    if (PROJECT_ROOT / "pyproject.toml").is_file() and (PROJECT_ROOT / "search_iwara").is_dir():
        return PROJECT_ROOT / "data" / "oreno3d.sqlite3"
    return Path(user_data_dir("search-iwara", appauthor=False)) / "oreno3d.sqlite3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEARCH_IWARA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        frozen=True,
        populate_by_name=True,
    )

    # --- storage -------------------------------------------------------------------------
    db_path: Path = Field(
        default_factory=default_db_path,
        validation_alias=AliasChoices("db_path", "SEARCH_IWARA_DB", "SEARCH_IWARA_DB_PATH"),
    )
    backup_dir: Path | None = None
    backup_keep: PositiveInt = 7

    # --- web -----------------------------------------------------------------------------
    host: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535)] = 8000
    page_size: Annotated[int, Field(ge=1, le=200)] = 36
    max_result_window: Annotated[int, Field(ge=100, le=1_000_000)] = 10_000
    metrics_enabled: bool = True
    metrics_token: Annotated[
        str | None, Field(min_length=16, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    ] = None
    api_docs_enabled: bool = False
    allow_indexing: bool = False
    web_threads: Annotated[int, Field(ge=1, le=256)] = 16

    # --- crawler -------------------------------------------------------------------------
    base_url: str = "https://oreno3d.com"
    user_agent: str = DEFAULT_USER_AGENT
    proxy: str | None = None
    trust_env: bool = True
    http2: bool = True
    respect_robots: bool = True
    request_timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 30.0
    request_retries: Annotated[int, Field(ge=0, le=10)] = 4
    request_concurrency: Annotated[int, Field(ge=1, le=64)] = 4
    request_rate: Annotated[float, Field(gt=0, le=50)] = 2.0
    backoff_base_seconds: Annotated[float, Field(gt=0, le=60)] = 1.0
    backoff_max_seconds: Annotated[float, Field(gt=0, le=3600)] = 60.0
    list_prefetch_pages: Annotated[int, Field(ge=1, le=64)] = 4
    detail_max_attempts: Annotated[int, Field(ge=1, le=50)] = 6
    detail_refresh_window_days: Annotated[int, Field(ge=0, le=3650)] = 30
    detail_refresh_after_hours: Annotated[int, Field(ge=1, le=24 * 365)] = 72
    detail_refresh_limit: Annotated[int, Field(ge=0, le=100_000)] = 500
    resume_overlap_pages: Annotated[int, Field(ge=0, le=20)] = 1
    sync_failure_tolerance: Annotated[int, Field(ge=0)] = 10
    # How often the scheduler runs `sync latest` (systemd timer / compose loop). Only used to
    # export search_iwara_sync_interval_seconds so staleness alerts follow the real schedule.
    sync_hours: Annotated[int | None, Field(ge=1, le=24 * 30)] = None
    sync_interval_seconds: Annotated[int | None, Field(ge=60)] = None

    # --- logging -------------------------------------------------------------------------
    log_format: Literal["auto", "text", "json"] = "auto"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("proxy", "metrics_token", mode="before")
    @classmethod
    def _blank_proxy_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("backup_dir", mode="before")
    @classmethod
    def _blank_backup_dir_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("db_path", "backup_dir", mode="after")
    @classmethod
    def _expand(cls, value: Path | None) -> Path | None:
        return None if value is None else value.expanduser().resolve()

    @field_validator("base_url", mode="after")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def resolved_backup_dir(self) -> Path:
        return self.backup_dir or self.db_path.parent / "backups"

    @property
    def expected_sync_interval(self) -> int | None:
        if self.sync_interval_seconds is not None:
            return self.sync_interval_seconds
        return None if self.sync_hours is None else self.sync_hours * 3600

    @property
    def max_page(self) -> int:
        return max(1, self.max_result_window // self.page_size)


def get_settings(db_path: str | Path | None = None, **overrides: Any) -> Settings:
    """Build validated settings; explicit arguments win over the environment."""

    values = {key: value for key, value in overrides.items() if value is not None}
    if db_path is not None:
        values["db_path"] = Path(db_path)
    return Settings(**values)
