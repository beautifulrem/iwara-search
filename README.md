# Search Iwara

Local-first metadata mirror of [Oreno3D](https://oreno3d.com/) with advanced search and filtering capabilities.

Crawls video metadata (title, author, tags, origins, characters, view/favorite counts, thumbnails, Iwara links) from Oreno3D and stores it in a local SQLite database. Provides a web UI for searching, filtering, and browsing — features the original site doesn't offer.

**No video files are downloaded or hosted. This is a metadata search tool only.**

## Features

- **Full-text title search** (SQLite FTS5)
- **Boolean entity filtering** — include/exclude by author, origin, character, tag (any/all/not)
- **Range filters** — published date, view count, favorite count
- **Four sort modes** matching the original site: Trending / Top Rated / Latest / Popular
- **Related videos** on detail pages (weighted by shared author, characters, origins, tags)
- **Light/Dark theme** with system preference detection and manual toggle
- **Popularity rankings** — sidebar with top characters, authors, and categories
- **Entity browsing** — ranked lists for `/characters`, `/authors`, `/tags`, `/origins` with author video carousels
- **Incremental & full sync** — resumable crawling with retry on failures
- **Terminal progress bars** — page progress + detail fetch progress during sync
- **Tunable concurrency** — request concurrency, prefetch window, and detail batch size are configurable
- **Responsive design** — mobile sidebar, adaptive grid

## Tech Stack

- Python 3.13, [uv](https://github.com/astral-sh/uv)
- SQLite / FTS5
- FastAPI + Jinja2
- httpx + selectolax
- Vanilla CSS (custom properties) + vanilla JS

## Quick Start

### Install

```bash
uv sync
```

### Crawl some data

```bash
# Quick test: grab the latest page only
uv run search-iwara sync latest --stable-pages 1 --max-pages 1

# Incremental sync: fetch new videos since last run
uv run search-iwara sync latest

# Full sync: crawl everything (resumable)
uv run search-iwara sync full

# Faster full sync (tune based on your network / remote site tolerance)
uv run search-iwara sync full \
  --request-concurrency 24 \
  --request-delay-ms 0 \
  --list-prefetch-pages 16 \
  --detail-batch-size 192
```

### Start the web UI

```bash
uv run search-iwara serve
# or specify a port
uv run search-iwara serve --port 8765
```

Open `http://127.0.0.1:8000` (default) in your browser.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Search & browse with filters and sort tabs |
| `/movies/{id}` | Video detail with metadata grid and related videos |
| `/characters` | Character rankings with search links |
| `/authors` | Author rankings with video carousels |
| `/tags` | Tag rankings |
| `/origins` | Origin/franchise rankings |

## Crawl Speed Tuning

The crawler is network-bound. It already uses async concurrency; by default it now runs with:

- `request_concurrency = 12`
- `request_delay_seconds = 0.05`
- `listing_prefetch_pages = 8`
- `detail_batch_size = 96`

You can override these from the CLI:

```bash
uv run search-iwara sync full \
  --request-concurrency 24 \
  --request-delay-ms 0 \
  --list-prefetch-pages 16 \
  --detail-batch-size 192
```

Recommended approach:

- Start with `--request-concurrency 24 --request-delay-ms 0`
- If the site starts failing or slowing down, lower concurrency to `16`
- Increase `--list-prefetch-pages` and `--detail-batch-size` only after request concurrency is stable

## Crawl Progress Output

Both sync commands show terminal progress bars:

- **Page progress**
  - `sync full`: current page / total pages
  - `sync latest`: current page and stable-page stop state
- **Detail progress**
  - number of video detail pages fetched in the current batch

Example:

```text
full page 53/8823
pages 49-56 details
```

## Search Parameters

All parameters are optional query strings on `/`.

| Category | Parameters |
|----------|-----------|
| Title | `q`, `title_mode=all\|any` |
| Author | `author_any`, `author_not` |
| Origin | `origin_any`, `origin_not` |
| Character | `character_any`, `character_not` |
| Tag | `tag_all`, `tag_any`, `tag_not` |
| Date range | `published_from`, `published_to` |
| View range | `min_views`, `max_views` |
| Favorite range | `min_favorites`, `max_favorites` |
| Sort | `sort=hot\|favorites\|latest\|popularity\|views_desc\|...` |

### Examples

```
/?q=Yelan&title_mode=all
/?author_any=4972&sort=hot
/?origin_any=276&character_any=1470
/?tag_any=2,3&tag_not=84
/?min_views=1000&min_favorites=100&sort=popularity
```

## Scoring & Rankings

All rankings are computed from **locally crawled data only** and do not represent the original site's full rankings.

| Mode | Formula |
|------|---------|
| Top Rated | `favorite_count DESC` |
| Latest | `published_at DESC` |
| Popular | `view_count + favorite_count * 50` |
| Trending | `(view_count + favorite_count * 50) / (hours_since_publish + 6)` |

### Related Videos Algorithm

Each video on the detail page shows up to 12 related videos, scored by:

| Dimension | Weight |
|-----------|--------|
| Same author | +10 |
| Each shared character | +5 |
| Each shared origin | +5 |
| Each shared tag | +1 |

Ties are broken by popularity score.

## Database

Default path: `data/oreno3d.sqlite3`

Override with environment variable:

```bash
SEARCH_IWARA_DB=/path/to/custom.sqlite3 uv run search-iwara serve
```

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run --extra dev pytest

# Quick crawl + serve for manual testing
uv run search-iwara sync latest --stable-pages 1 --max-pages 1
uv run search-iwara serve --port 8765
```

### Project Structure

```
search_iwara/
  cli.py          # Typer CLI: sync full, sync latest, serve
  services.py     # Sync orchestration, prefetch, detail batching, progress events
  crawler.py      # Async HTTP to oreno3d.com (rate limiting, retries)
  parsers.py      # HTML -> structured fields via selectolax
  db.py           # SQLite schema, upserts, FTS5 search, rankings
  models.py       # Dataclass models
  config.py       # Settings (DB path, concurrency, delay, batch sizes)
  web.py          # FastAPI routes
  utils.py        # URL parsing, formatting, pagination helpers
  static/
    style.css     # Light/dark theme with CSS custom properties
    app.js        # Theme toggle, filter panel, autocomplete chips
  templates/
    base.html     # Layout: header, sidebar, theme toggle
    index.html    # Search page with sort tabs and collapsible filters
    movie_detail.html  # Detail page with related videos
    entity_index.html  # Entity ranking pages
tests/
  test_parsers.py
  test_repository.py
  test_web.py
```

## License

This project is licensed under the MIT License.

See [LICENSE](/path/to/repo/LICENSE).
