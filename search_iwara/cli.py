"""Command-line interface: ``search-iwara sync …``, ``search-iwara db …`` and ``search-iwara serve``.

Exit codes (stable, used by the systemd units):
    0   success
    1   the run finished but with more failures than ``SEARCH_IWARA_SYNC_FAILURE_TOLERANCE``
    2   parser drift — the site structure changed and the run was aborted
    75  another sync holds the lock (EX_TEMPFAIL); nothing was done
    78  invalid configuration (EX_CONFIG)
    143 terminated by SIGTERM/SIGINT; committed progress kept, run recorded as failed
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sqlite3
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Annotated, Any, Self

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from . import __version__
from .config import Settings, get_settings
from .crawler import CrawlerConfigError, Oreno3dClient, RobotsUnavailableError
from .logging_setup import configure_logging, uvicorn_log_config
from .services import (
    SyncAbortedError,
    SyncLockedError,
    SyncMode,
    SyncOptions,
    SyncProgress,
    SyncService,
    SyncSummary,
    sync_lock,
)
from .storage import SCHEMA_VERSION, CrawlStore, connect, migrate

EXIT_FAILURES = 1
EXIT_DRIFT = 2
EXIT_LOCKED = 75
EXIT_CONFIG = 78
EXIT_TERMINATED = 143  # 128 + SIGTERM

app = typer.Typer(help="Local Oreno3D metadata mirror.", no_args_is_help=True, add_completion=False)
sync_app = typer.Typer(help="Crawl oreno3d.com into the local database.", no_args_is_help=True)
db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)
app.add_typer(sync_app, name="sync")
app.add_typer(db_app, name="db")
logger = logging.getLogger("search_iwara.cli")
console = Console(stderr=True)

DbPathOption = Annotated[
    Path | None, typer.Option("--db-path", help="SQLite database path.", show_default=False)
]
ConcurrencyOption = Annotated[
    int | None, typer.Option(min=1, max=64, help="Concurrent HTTP requests (default 4).", show_default=False)
]
RateOption = Annotated[
    float | None,
    typer.Option(
        min=0.05, max=50.0, help="Request rate ceiling in requests/second (default 2).", show_default=False
    ),
]
MaxPagesOption = Annotated[int | None, typer.Option(min=1, help="Stop after this many listing pages.")]


def _settings(**overrides: Any) -> Settings:
    try:
        settings = get_settings(**overrides)
    except ValidationError as exc:
        console.print(f"[red]invalid configuration:[/red]\n{exc}")
        raise typer.Exit(EXIT_CONFIG) from exc
    configure_logging(settings.log_format, settings.log_level)
    return settings


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"search-iwara {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", help="Show the version and exit.", callback=_version_callback, is_eager=True
        ),
    ] = False,
) -> None:
    """Local Oreno3D metadata mirror."""


# --- progress reporting ------------------------------------------------------------------------


class RichProgress:
    """Live progress bars for interactive terminals."""

    def __init__(self) -> None:
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        )
        self.pages: TaskID | None = None
        self.details: TaskID | None = None

    def __enter__(self) -> Self:
        self.progress.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.progress.stop()

    def on_pages_planned(self, *, mode: SyncMode, first_page: int, last_page: int | None) -> None:
        total = None if last_page is None else last_page - first_page + 1
        self.pages = self.progress.add_task(f"[cyan]{mode}[/cyan] pages", total=total)
        self.details = self.progress.add_task("[magenta]details[/magenta]", total=0)

    def on_page_done(
        self,
        *,
        mode: SyncMode,
        page: int,
        pages_checked: int,
        stable_pages: int | None,
        stable_limit: int | None,
    ) -> None:
        if self.pages is None:
            return
        label = f"[cyan]{mode}[/cyan] page {page}"
        if stable_pages is not None:
            label += f" · stable {stable_pages}/{stable_limit}"
        self.progress.update(self.pages, completed=pages_checked, description=label)

    def on_details_queued(self, *, total: int) -> None:
        if self.details is not None:
            self.progress.update(self.details, total=total)

    def on_detail_done(self, *, done: int) -> None:
        if self.details is not None:
            self.progress.update(self.details, completed=done)


class LogProgress:
    """Periodic log lines for non-interactive runs (systemd/journald, CI, containers)."""

    def __init__(self) -> None:
        self.queued = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def on_pages_planned(self, *, mode: SyncMode, first_page: int, last_page: int | None) -> None:
        logger.info("sync %s started", mode, extra={"first_page": first_page, "last_page": last_page})

    def on_page_done(
        self,
        *,
        mode: SyncMode,
        page: int,
        pages_checked: int,
        stable_pages: int | None,
        stable_limit: int | None,
    ) -> None:
        if pages_checked % 10 == 0 or stable_pages == stable_limit:
            logger.info("listing progress", extra={"page": page, "pages_checked": pages_checked})

    def on_details_queued(self, *, total: int) -> None:
        self.queued = total

    def on_detail_done(self, *, done: int) -> None:
        if done % 100 == 0:
            logger.info("detail progress", extra={"done": done, "queued": self.queued})


# --- sync ---------------------------------------------------------------------------------------


SyncAction = Callable[[SyncService, SyncProgress], Awaitable[SyncSummary]]


def _run_sync(mode: SyncMode, settings: Settings, action: SyncAction) -> None:
    interactive = sys.stderr.isatty()

    async def runner() -> SyncSummary:
        # SIGTERM (systemd stop, docker stop, TimeoutStartSec) and SIGINT cancel the run
        # instead of killing the process, so pending writes are flushed and the run record
        # is closed as "failed" by SyncService's finally block.
        main_task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        if main_task is not None:
            for sig in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError, RuntimeError):  # Windows / non-main thread
                    loop.add_signal_handler(sig, main_task.cancel)
        store = CrawlStore.open(settings.db_path)
        try:
            async with Oreno3dClient(settings) as client:
                service = SyncService(store, client, SyncOptions.from_settings(settings))
                with RichProgress() if interactive else LogProgress() as progress:
                    return await action(service, progress)
        finally:
            store.close()

    try:
        with sync_lock(settings.db_path):
            summary = asyncio.run(runner())
    except SyncLockedError as exc:
        logger.warning("%s", exc)
        raise typer.Exit(EXIT_LOCKED) from exc
    except CrawlerConfigError as exc:
        logger.error("%s", exc)
        raise typer.Exit(EXIT_CONFIG) from exc
    except SyncAbortedError as exc:
        logger.error("sync aborted: %s — the parser probably needs updating", exc)
        raise typer.Exit(EXIT_DRIFT) from exc
    except RobotsUnavailableError as exc:
        logger.error("sync aborted: %s", exc)
        raise typer.Exit(EXIT_FAILURES) from exc
    except asyncio.CancelledError as exc:
        logger.warning("sync %s terminated by signal; committed progress was kept", mode)
        raise typer.Exit(EXIT_TERMINATED) from exc

    logger.info("sync %s finished", mode, extra=summary.counters())
    typer.echo(
        f"sync {mode}: pages={summary.pages_checked} (failed {summary.failed_pages}), "
        f"seen={summary.movies_seen}, new={summary.new_movies}, changed={summary.changed_movies}, "
        f"details={summary.details_fetched}, missing={summary.missing_movies}, "
        f"failed={summary.failed_details}"
    )
    if summary.failed_pages or summary.failed_details > settings.sync_failure_tolerance:
        raise typer.Exit(EXIT_FAILURES)


@sync_app.command("latest")
def sync_latest(
    db_path: DbPathOption = None,
    stable_pages: Annotated[
        int, typer.Option(min=1, help="Stop after N consecutive pages without new movies.")
    ] = 3,
    max_pages: MaxPagesOption = None,
    request_concurrency: ConcurrencyOption = None,
    request_rate: RateOption = None,
) -> None:
    """Fetch the newest pages until no new movies appear, then refresh stale details."""

    settings = _settings(db_path=db_path, request_concurrency=request_concurrency, request_rate=request_rate)
    _run_sync(
        "latest",
        settings,
        lambda service, progress: service.sync_latest(
            stable_page_limit=stable_pages, max_pages=max_pages, progress=progress
        ),
    )


@sync_app.command("full")
def sync_full(
    db_path: DbPathOption = None,
    start_page: Annotated[int | None, typer.Option(min=1, help="Override the resume page.")] = None,
    max_pages: MaxPagesOption = None,
    request_concurrency: ConcurrencyOption = None,
    request_rate: RateOption = None,
    list_prefetch_pages: Annotated[
        int | None, typer.Option(min=1, max=64, help="Listing pages fetched per batch (default 4).")
    ] = None,
) -> None:
    """Resumable crawl of the whole catalogue."""

    settings = _settings(
        db_path=db_path,
        request_concurrency=request_concurrency,
        request_rate=request_rate,
        list_prefetch_pages=list_prefetch_pages,
    )
    _run_sync(
        "full",
        settings,
        lambda service, progress: service.sync_full(
            start_page=start_page, max_pages=max_pages, progress=progress
        ),
    )


# --- database maintenance ----------------------------------------------------------------------


@db_app.command("migrate")
def db_migrate(db_path: DbPathOption = None) -> None:
    """Create the database or upgrade its schema (idempotent)."""

    settings = _settings(db_path=db_path)
    connection = connect(settings.db_path)
    try:
        applied = migrate(connection)
    finally:
        connection.close()
    typer.echo(f"schema v{SCHEMA_VERSION} ({applied} migration(s) applied) at {settings.db_path}")


@db_app.command("refresh")
def db_refresh(db_path: DbPathOption = None) -> None:
    """Recompute hot scores and ranking statistics without crawling."""

    settings = _settings(db_path=db_path)
    store = CrawlStore.open(settings.db_path)
    try:
        store.refresh_derived()
    finally:
        store.close()
    typer.echo("derived data refreshed")


@db_app.command("backup")
def db_backup(
    db_path: DbPathOption = None,
    dest: Annotated[Path | None, typer.Option(help="Backup directory (default: <db dir>/backups).")] = None,
    keep: Annotated[int | None, typer.Option(min=1, help="How many backups to keep (default 7).")] = None,
) -> None:
    """Consistent online backup via the SQLite backup API, with rotation."""

    settings = _settings(db_path=db_path, backup_dir=dest, backup_keep=keep)
    if not settings.db_path.exists():
        typer.echo(f"no database at {settings.db_path}", err=True)
        raise typer.Exit(1)
    target_dir = settings.resolved_backup_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"{settings.db_path.stem}-{stamp}.sqlite3"
    partial = target.with_suffix(".partial")

    source = connect(settings.db_path, readonly=True)
    destination = sqlite3.connect(partial)
    try:
        source.backup(destination, pages=4096)
        check = destination.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        destination.close()
        source.close()
    if check != "ok":
        partial.unlink(missing_ok=True)
        typer.echo(f"backup failed integrity check: {check}", err=True)
        raise typer.Exit(1)
    partial.rename(target)

    backups = sorted(target_dir.glob(f"{settings.db_path.stem}-*.sqlite3"))
    for old in backups[: -settings.backup_keep]:
        old.unlink()
    logger.info(
        "backup written", extra={"path": str(target), "kept": min(len(backups), settings.backup_keep)}
    )
    typer.echo(str(target))


# --- web ----------------------------------------------------------------------------------------


@app.command("serve")
def serve(
    db_path: DbPathOption = None,
    host: Annotated[
        str | None, typer.Option(help="Bind address (default 127.0.0.1).", show_default=False)
    ] = None,
    port: Annotated[
        int | None, typer.Option(min=1, max=65535, help="Port (default 8000).", show_default=False)
    ] = None,
    proxy_headers: Annotated[
        bool, typer.Option(help="Trust X-Forwarded-* from --forwarded-allow-ips (behind nginx).")
    ] = True,
    forwarded_allow_ips: Annotated[
        str, typer.Option(help="Comma-separated trusted proxy IPs.")
    ] = "127.0.0.1",
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes (development).")] = False,
) -> None:
    """Start the search UI."""

    import uvicorn  # noqa: PLC0415 - keep CLI start-up fast for sync commands

    settings = _settings(db_path=db_path, host=host, port=port)
    log_format = configure_logging(settings.log_format, settings.log_level)
    config = uvicorn_log_config(log_format, settings.log_level)
    if reload:
        # The reloader imports the app by path in a subprocess; hand the settings over via env.
        import os  # noqa: PLC0415

        os.environ["SEARCH_IWARA_DB"] = str(settings.db_path)
        uvicorn.run(
            "search_iwara.web:create_app",
            factory=True,
            host=settings.host,
            port=settings.port,
            reload=True,
            log_config=config,
            access_log=False,  # ObservabilityMiddleware logs structured access lines
        )
        return

    from .web import create_app  # noqa: PLC0415

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=proxy_headers,
        forwarded_allow_ips=forwarded_allow_ips,
        server_header=False,
        date_header=True,
        log_config=config,
        access_log=False,  # ObservabilityMiddleware logs structured access lines
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
