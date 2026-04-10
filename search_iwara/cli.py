from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn

from .config import get_settings
from .crawler import Oreno3dClient
from .db import Repository
from .services import SyncService
from .web import create_app


app = typer.Typer(help="Local Oreno3D search mirror.")
sync_app = typer.Typer(help="Metadata sync commands.")
app.add_typer(sync_app, name="sync")


def _echo_summary(name: str, summary) -> None:
    typer.echo(
        (
            f"{name}: pages={summary.pages_checked}, seen={summary.movies_seen}, "
            f"new={summary.new_movies}, changed={summary.changed_movies}, "
            f"details={summary.details_fetched}, missing={summary.missing_movies}, "
            f"failed={summary.failed_details}"
        )
    )


@sync_app.command("full")
def sync_full(
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    start_page: int | None = typer.Option(None, min=1, help="Override resume page."),
    max_pages: int | None = typer.Option(None, min=1, help="Limit pages for a partial run."),
) -> None:
    """Run a resumable full sync from the latest listing pages."""

    async def runner() -> None:
        repo = Repository.open(db_path)
        async with Oreno3dClient(get_settings(db_path)) as client:
            service = SyncService(repo, client)
            summary = await service.sync_full(start_page=start_page, max_pages=max_pages)
            _echo_summary("sync full", summary)
        repo.close()

    asyncio.run(runner())


@sync_app.command("latest")
def sync_latest(
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    stable_pages: int = typer.Option(3, min=1, help="Stop after this many stable pages."),
    max_pages: int | None = typer.Option(None, min=1, help="Limit pages for a partial run."),
) -> None:
    """Fetch only the newest pages until results stabilize."""

    async def runner() -> None:
        repo = Repository.open(db_path)
        async with Oreno3dClient(get_settings(db_path)) as client:
            service = SyncService(repo, client)
            summary = await service.sync_latest(stable_page_limit=stable_pages, max_pages=max_pages)
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
