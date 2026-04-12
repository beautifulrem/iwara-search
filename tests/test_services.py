import asyncio
from pathlib import Path
from types import SimpleNamespace

from search_iwara.crawler import RemoteUnavailableError
from search_iwara.db import Repository
from search_iwara.models import ListingPage, MovieListItem
from search_iwara.services import SyncService


class FakeUnavailableClient:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(detail_batch_size=8, listing_prefetch_pages=1)

    async def fetch_listing_page(self, page: int) -> ListingPage:
        assert page == 1
        return ListingPage(
            page=1,
            last_page=1,
            items=[
                MovieListItem(
                    source_site_id=501,
                    oreno3d_url="https://oreno3d.com/movies/501",
                    title="placeholder listing title",
                    author_name="Creator A",
                    thumbnail_url=None,
                    view_count=0,
                    favorite_count=0,
                )
            ],
        )

    async def fetch_movie_detail(self, source_site_id: int):
        raise RemoteUnavailableError(f"https://oreno3d.com/movies/{source_site_id}")


def test_sync_latest_marks_unavailable_detail_as_missing(tmp_path: Path):
    repo = Repository.open(tmp_path / "service.sqlite3")
    service = SyncService(repo, FakeUnavailableClient())

    summary = asyncio.run(service.sync_latest(stable_page_limit=1, max_pages=1))

    movie = repo.get_movie(501)
    assert movie is not None
    assert movie["status"] == "missing"
    assert summary.details_fetched == 0
    assert summary.failed_details == 0
    assert summary.missing_movies == 1
    assert repo.get_failed_movie_ids() == []

    repo.close()
