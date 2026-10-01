"""Regenerate the Search Iwara logo, favicon and PWA icons.

    uv run --group e2e python scripts/make_brand_assets.py

The mark is a magnifier whose lens is a faceted diamond (a nod to the angular, low-poly marks
common in 3D/MMD culture, including Iwara's own), holding a play glyph. The handle is detached
so the silhouette stays crisp down to 16 px. Colours are the UI's accent tokens (magenta to coral).
"""

from __future__ import annotations

import base64
import math
import pathlib

from playwright.sync_api import sync_playwright

Point = tuple[float, float]
SQRT_HALF = 1 / math.sqrt(2)
SVG_NS = "http://www.w3.org/2000/svg"


def _polygon(points: list[Point]) -> str:
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points) + " Z"


def _play(cx: float, cy: float, size: float) -> str:
    """Rounded play triangle, nudged right so it looks centred."""

    ax, ay = cx - size * 0.36, cy - size * 0.5
    bx, by = cx - size * 0.36, cy + size * 0.5
    px, py = cx + size * 0.52, cy
    return (
        f"M{ax:.1f} {ay + 6:.1f} Q{ax:.1f} {ay:.1f} {ax + 5:.1f} {ay + 3:.1f} "
        f"L{px - 5:.1f} {py - 3:.1f} Q{px:.1f} {py:.1f} {px - 5:.1f} {py + 3:.1f} "
        f"L{bx + 5:.1f} {by - 3:.1f} Q{bx:.1f} {by:.1f} {bx:.1f} {by - 6:.1f} Z"
    )


def mark(
    *,
    half_diagonal: float = 118.0,
    ring: float = 40.0,
    handle_width: float = 46.0,
    gap: float = 10.0,
    handle_length: float = 92.0,
) -> tuple[str, tuple[float, float, float, float]]:
    """SVG elements of the mark (lens centred at 0,0) and their bounding box."""

    outer, inner = half_diagonal, half_diagonal - ring * math.sqrt(2)
    top, right, bottom, left = (0.0, -outer), (outer, 0.0), (0.0, outer), (-outer, 0.0)
    i_top, i_right, i_bottom, i_left = (0.0, -inner), (inner, 0.0), (0.0, inner), (-inner, 0.0)
    # The whole ring at 80 % white, with the lit (left) facet drawn over it: no anti-aliasing seam.
    ring_path = _polygon([top, right, bottom, left]) + " " + _polygon([i_top, i_left, i_bottom, i_right])
    lit_facet = _polygon([top, i_top, i_left, i_bottom, bottom, left])
    # Handle at 45 degrees, starting `gap` outside the lower-right facet.
    offset = outer / 2 + (gap + handle_width / 2) * SQRT_HALF
    start = (offset, offset)
    end = (offset + handle_length * SQRT_HALF, offset + handle_length * SQRT_HALF)
    cap = handle_width / 2
    elements = (
        f'<path d="M{start[0]:.1f} {start[1]:.1f} L{end[0]:.1f} {end[1]:.1f}" stroke="#fff" '
        f'stroke-width="{handle_width}" stroke-linecap="round"/>'
        f'<path d="{ring_path}" fill="#fff" fill-opacity="0.8" fill-rule="evenodd"/>'
        f'<path d="{lit_facet}" fill="#fff"/>'
        f'<path d="{_play(0.0, 0.0, inner * 0.74)}" fill="#fff"/>'
    )
    return elements, (-outer, -outer, end[0] + cap, end[1] + cap)


def tile_svg(
    *, size: int = 512, radius: int = 116, fill: float = 0.66, full_bleed: bool = False, **shape: float
) -> str:
    elements, (x0, y0, x1, y1) = mark(**shape)
    scale = size * fill / max(x1 - x0, y1 - y0)
    tx, ty = size / 2 - scale * (x0 + x1) / 2, size / 2 - scale * (y0 + y1) / 2
    rect = f'width="{size}" height="{size}"' + ("" if full_bleed else f' rx="{radius}"')
    svg_open = f'<svg xmlns="{SVG_NS}" viewBox="0 0 {size} {size}" role="img" aria-labelledby="t">'
    return f"""{svg_open}
  <title id="t">Search Iwara</title>
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#d6146f"/>
      <stop offset="0.55" stop-color="#e2345a"/>
      <stop offset="1" stop-color="#f26a2c"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.22" cy="0.16" r="0.75">
      <stop offset="0" stop-color="#fff" stop-opacity="0.26"/>
      <stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect {rect} fill="url(#tile)"/>
  <rect {rect} fill="url(#glow)"/>
  <g transform="translate({tx:.2f} {ty:.2f}) scale({scale:.4f})">{elements}</g>
</svg>
"""


def rasterize(jobs: list[tuple[pathlib.Path, pathlib.Path, int]]) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for source, target, size in jobs:
            uri = "data:image/svg+xml;base64," + base64.b64encode(source.read_bytes()).decode()
            page = browser.new_page(viewport={"width": size, "height": size})
            img = f'<img src="{uri}" width="{size}" height="{size}" style="display:block">'
            page.set_content(f'<body style="margin:0">{img}')
            page.screenshot(path=str(target), omit_background=True)
            page.close()
        browser.close()


def main() -> None:
    assets, static = pathlib.Path("docs/assets"), pathlib.Path("search_iwara/static")
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "logo.svg").write_text(tile_svg())
    (assets / "logo-maskable.svg").write_text(tile_svg(full_bleed=True, fill=0.54))  # 80 % safe zone
    (static / "favicon.svg").write_text(tile_svg(ring=48, handle_width=54, gap=12))  # sturdier at 16 px
    rasterize(
        [
            (assets / "logo.svg", static / "icon-192.png", 192),
            (assets / "logo.svg", static / "icon-512.png", 512),
            (assets / "logo-maskable.svg", static / "icon-maskable-512.png", 512),
            (assets / "logo-maskable.svg", static / "apple-touch-icon.png", 180),
        ]
    )


if __name__ == "__main__":
    main()
