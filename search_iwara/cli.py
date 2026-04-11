from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from .config import get_settings
from .crawler import Oreno3dClient
from .db import Repository
from .services import SyncProgressReporter, SyncService
from .web import create_app


app = typer.Typer(help="Local Oreno3D search mirror.")
sync_app = typer.Typer(help="Metadata sync commands.")
app.add_typer(sync_app, name="sync")
console = Console()


class RichSyncProgressReporter(SyncProgressReporter):
    def __init__(self) -> None:
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        )
        self.page_task: TaskID | None = None
        self.detail_task: TaskID | None = None

    def __enter__(self) -> "RichSyncProgressReporter":
        self.progress.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.progress.stop()

    def on_page_plan(self, *, mode: str, current_page: int, total_pages: int | None) -> None:
        description = (
            f"[cyan]Sync full[/cyan] pages from {current_page}"
            if mode == "full"
            else "[cyan]Sync latest[/cyan] scanning pages"
        )
        if self.page_task is not None:
            self.progress.remove_task(self.page_task)
        initial_completed = current_page - 1 if mode == "full" and total_pages and current_page > 1 else 0
        self.page_task = self.progress.add_task(
            description,
            total=total_pages if total_pages and total_pages > 0 else None,
            completed=initial_completed,
        )

    def on_page_processed(
        self,
        *,
        mode: str,
        page: int,
        pages_checked: int,
        total_pages: int | None,
        stable_pages: int | None = None,
        stable_page_limit: int | None = None,
    ) -> None:
        if self.page_task is None:
            self.on_page_plan(mode=mode, current_page=page, total_pages=total_pages)
        description = f"[cyan]{mode}[/cyan] page {page}"
        if mode == "full" and total_pages:
            description += f"/{total_pages}"
        if mode == "latest" and stable_pages is not None and stable_page_limit is not None:
            description += f"  stable {stable_pages}/{stable_page_limit}"
        self.progress.update(
            self.page_task,
            description=description,
            completed=page if mode == "full" and total_pages else pages_checked,
            total=total_pages if total_pages and total_pages > 0 else None,
        )

    def on_detail_batch_start(self, *, label: str, total_items: int) -> None:
        if self.detail_task is not None:
            self.progress.remove_task(self.detail_task)
        total = total_items if total_items > 0 else 1
        description = f"[magenta]{label}[/magenta]"
        self.detail_task = self.progress.add_task(description, total=total)
        if total_items == 0:
            self.progress.update(self.detail_task, completed=1, description=f"[magenta]{label}[/magenta] none")

    def on_detail_item_done(self, *, label: str, processed_items: int, total_items: int) -> None:
        if self.detail_task is None:
            return
        total = total_items if total_items > 0 else 1
        self.progress.update(
            self.detail_task,
            description=f"[magenta]{label}[/magenta]",
            completed=processed_items if total_items > 0 else 1,
            total=total,
        )


def _echo_summary(name: str, summary) -> None:
    typer.echo(
        (
            f"{name}: pages={summary.pages_checked}, seen={summary.movies_seen}, "
            f"new={summary.new_movies}, changed={summary.changed_movies}, "
            f"details={summary.details_fetched}, missing={summary.missing_movies}, "
            f"failed={summary.failed_details}"
        )
    )


def _build_settings(
    db_path: Path | None,
    *,
    request_concurrency: int | None,
    request_delay_ms: int | None,
    list_prefetch_pages: int | None,
    detail_batch_size: int | None,
):
    settings = get_settings(db_path)
    return replace(
        settings,
        request_concurrency=request_concurrency or settings.request_concurrency,
        request_delay_seconds=(
            settings.request_delay_seconds if request_delay_ms is None else max(request_delay_ms, 0) / 1000.0
        ),
        listing_prefetch_pages=list_prefetch_pages or settings.listing_prefetch_pages,
        detail_batch_size=detail_batch_size or settings.detail_batch_size,
    )


@sync_app.command("full")
def sync_full(
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    start_page: int | None = typer.Option(None, min=1, help="Override resume page."),
    max_pages: int | None = typer.Option(None, min=1, help="Limit pages for a partial run."),
    request_concurrency: int | None = typer.Option(None, min=1, help="Concurrent HTTP requests."),
    request_delay_ms: int | None = typer.Option(None, min=0, help="Delay between requests in milliseconds."),
    list_prefetch_pages: int | None = typer.Option(None, min=1, help="How many listing pages to prefetch per batch."),
    detail_batch_size: int | None = typer.Option(None, min=1, help="How many detail tasks to schedule per batch."),
) -> None:
    """Run a resumable full sync from the latest listing pages."""

    async def runner() -> None:
        settings = _build_settings(
            db_path,
            request_concurrency=request_concurrency,
            request_delay_ms=request_delay_ms,
            list_prefetch_pages=list_prefetch_pages,
            detail_batch_size=detail_batch_size,
        )
        repo = Repository.open(db_path)
        async with Oreno3dClient(settings) as client:
            service = SyncService(repo, client)
            with RichSyncProgressReporter() as reporter:
                summary = await service.sync_full(
                    start_page=start_page,
                    max_pages=max_pages,
                    progress=reporter,
                )
            _echo_summary("sync full", summary)
        repo.close()

    asyncio.run(runner())


@sync_app.command("latest")
def sync_latest(
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    stable_pages: int = typer.Option(3, min=1, help="Stop after this many stable pages."),
    max_pages: int | None = typer.Option(None, min=1, help="Limit pages for a partial run."),
    request_concurrency: int | None = typer.Option(None, min=1, help="Concurrent HTTP requests."),
    request_delay_ms: int | None = typer.Option(None, min=0, help="Delay between requests in milliseconds."),
    list_prefetch_pages: int | None = typer.Option(None, min=1, help="Reserved for future list prefetch tuning."),
    detail_batch_size: int | None = typer.Option(None, min=1, help="How many detail tasks to schedule per batch."),
) -> None:
    """Fetch only the newest pages until results stabilize."""

    async def runner() -> None:
        settings = _build_settings(
            db_path,
            request_concurrency=request_concurrency,
            request_delay_ms=request_delay_ms,
            list_prefetch_pages=list_prefetch_pages,
            detail_batch_size=detail_batch_size,
        )
        repo = Repository.open(db_path)
        async with Oreno3dClient(settings) as client:
            service = SyncService(repo, client)
            with RichSyncProgressReporter() as reporter:
                summary = await service.sync_latest(
                    stable_page_limit=stable_pages,
                    max_pages=max_pages,
                    progress=reporter,
                )
            _echo_summary("sync latest", summary)
        repo.close()

    asyncio.run(runner())


@app.command("serve")
def serve(
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    host: str = typer.Option("127.0.0.1", help="Host to bind."),
    port: int = typer.Option(8000, min=1, max=65535, help="Port to bind."),
) -> None:
    """Start the local search UI."""

    app_instance = create_app(db_path)
    uvicorn.run(app_instance, host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
