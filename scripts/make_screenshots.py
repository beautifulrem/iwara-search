"""Regenerate the README screenshots from a neutral demo catalogue.

    uv run --group e2e python scripts/make_screenshots.py

Real oreno3d.com metadata is adult content, so the screenshots use made-up, work-safe titles
and abstract generated thumbnails (served by intercepting the thumbnail requests). Everything
else — templates, styles, scripts — is the real application.
"""

from __future__ import annotations

import random
import socket
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from playwright.sync_api import Browser, Page, Route, sync_playwright

from search_iwara.config import get_settings
from search_iwara.models import EntityRef, MovieDetail
from search_iwara.storage import CrawlStore
from search_iwara.web import create_app

OUT = Path("docs/assets/screenshots")
JST = ZoneInfo("Asia/Tokyo")
AUTHORS = ["Kaede Motion", "PixelForge", "Studio Hoshi", "MMD Lab", "Aoi Works", "NightOwl3D", "Lumen Pose"]
CHARACTERS = ["Aoi", "Rin", "Mika", "Yuna", "Sora", "Hana"]
ORIGINS = ["Starlight Academy", "Project Aurora", "Neon Drift", "Original"]
TAGS = [
    "dance",
    "MMD",
    "4K",
    "60fps",
    "original motion",
    "music video",
    "camera work",
    "outfit",
    "ray tracing",
]
TITLES = [
    "Summer Festival Dance — Full Choreography",
    "【MMD】夏祭りダンス 4K",
    "Rooftop Sunset — Original Motion",
    "Neon City Night Walk",
    "【MMD】ステージライブ・アンコール",
    "Rainy Window Lo-fi Loop",
    "Starlight Academy — Opening Dance",
    "Cherry Blossom Waltz",
    "Cyber Idol Showcase 60fps",
    "Beach Day — Camera Test",
    "Winter Lights Duet",
    "Retro Arcade Groove",
    "【MMD】桜並木で踊ってみた",
    "Moonlit Garden Ballet",
    "Aurora Stage — Ray Traced",
    "Studio Practice Session #12",
]


def demo_catalogue(count: int = 48) -> list[MovieDetail]:
    rng = random.Random(7)  # noqa: S311 - deterministic demo data
    now = datetime.now(JST)
    movies = []
    for index in range(count):
        source_id = 900_000 - index
        author = rng.randrange(len(AUTHORS))
        published = now - timedelta(hours=index * 7 + rng.randint(0, 6))
        views = int(rng.paretovariate(1.15) * 900)
        movies.append(
            MovieDetail(
                source_site_id=source_id,
                oreno3d_url=f"https://oreno3d.com/movies/{source_id}",
                title=TITLES[index % len(TITLES)]
                + ("" if index < len(TITLES) else f" · Take {index // len(TITLES) + 1}"),
                external_video_url=f"https://www.iwara.tv/video/demo{source_id}",
                author=EntityRef(100 + author, AUTHORS[author]),
                tags=[EntityRef(300 + t, TAGS[t]) for t in sorted(rng.sample(range(len(TAGS)), 3))],
                origins=[EntityRef(400 + (o := rng.randrange(len(ORIGINS))), ORIGINS[o])],
                characters=[EntityRef(500 + (c := rng.randrange(len(CHARACTERS))), CHARACTERS[c])],
                thumbnail_url=f"https://oreno3d.com/storage/demo/{source_id}.jpg",
                published_at=published.strftime("%Y-%m-%d %H:%M"),
                view_count=views,
                favorite_count=int(views * rng.uniform(0.02, 0.09)),
                author_comment=(
                    "Motion: original choreography.\nCamera and lighting by the author — thanks for watching!"
                    if index == 0
                    else None
                ),
            )
        )
    return movies


def thumbnail_svg(seed: int) -> str:
    """Abstract 16:9 'stage' artwork: gradient, glow, light beams and sparkles."""

    rng = random.Random(seed)  # noqa: S311
    hue = rng.randrange(360)
    beams = "".join(
        f'<polygon points="{x},0 {x + 40},0 {x + 160},360 {x - 80},360" fill="#fff" '
        f'opacity="{rng.uniform(0.05, 0.14):.2f}"/>'
        for x in rng.sample(range(40, 600, 40), 3)
    )
    sparkles = "".join(
        f'<circle cx="{rng.randrange(640)}" cy="{rng.randrange(260)}" '
        f'r="{rng.uniform(1, 3):.1f}" fill="#fff" '
        f'opacity="{rng.uniform(0.4, 0.9):.2f}"/>'
        for _ in range(18)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360">
<defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="hsl({hue},70%,32%)"/>
<stop offset="1" stop-color="hsl({(hue + 60) % 360},80%,55%)"/>
</linearGradient>
<radialGradient id="r" cx="0.5" cy="0.95" r="0.7">
<stop offset="0" stop-color="hsl({(hue + 30) % 360},95%,75%)" stop-opacity="0.9"/>
<stop offset="1" stop-color="#000" stop-opacity="0"/>
</radialGradient>
</defs>
<rect width="640" height="360" fill="url(#g)"/>
<rect width="640" height="360" fill="url(#r)"/>{beams}{sparkles}
<ellipse cx="320" cy="350" rx="260" ry="34" fill="#000" opacity="0.25"/>
</svg>"""


def serve(db: Path) -> tuple[str, uvicorn.Server]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(get_settings(db_path=db)), port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server


def open_page(browser: Browser, url: str, *, width: int, height: int, scheme: str, scale: float = 1) -> Page:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme=scheme,
        device_scale_factor=scale,  # type: ignore[arg-type]
    )

    def thumbnails(route: Route) -> None:
        seed = int("".join(ch for ch in route.request.url if ch.isdigit())[-6:] or 0)
        route.fulfill(status=200, content_type="image/svg+xml", body=thumbnail_svg(seed))

    context.route("https://oreno3d.com/**", thumbnails)
    page = context.new_page()
    page.goto(url)
    page.wait_for_selector("html.js-ready", state="attached")
    page.wait_for_load_state("networkidle")
    return page


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "demo.sqlite3"
        store = CrawlStore.open(db)
        with store.transaction():
            for movie in demo_catalogue():
                store.apply_movie_detail(movie)
        run = store.start_run("latest")
        store.finish_run(run, status="success", counters={"new_movies": 48})
        store.refresh_derived()
        store.close()

        base, server = serve(db)
        shots = {
            "home-light": ("/?lang=en", 1440, 900, "light", 1),
            "home-dark": ("/?lang=en", 1440, 900, "dark", 1),
            "detail-light": (f"/movies/{900_000}?lang=en", 1440, 900, "light", 1),
            "mobile-dark": ("/?lang=en&q=dance", 390, 844, "dark", 2),
        }
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for name, (path, width, height, scheme, scale) in shots.items():
                page = open_page(browser, base + path, width=width, height=height, scheme=scheme, scale=scale)
                page.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=86)
                page.context.close()

            page = open_page(
                browser,
                base + "/?lang=en&tag_all=300&character_any=500",
                width=1440,
                height=900,
                scheme="dark",
            )
            page.locator('[data-dialog-open="filters"]').first.click()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / "filters-dark.jpg"), type="jpeg", quality=86)
            page.context.close()

            page = open_page(browser, base + "/?lang=en", width=390, height=844, scheme="light", scale=2)
            page.locator('[data-dialog-open="filters"]').first.click()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / "mobile-filters-light.jpg"), type="jpeg", quality=86)
            page.context.close()
            browser.close()
        server.should_exit = True
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"screenshots written to {OUT}/ at {stamp}")


if __name__ == "__main__":
    main()
