"""Security response headers as a pure ASGI middleware (no BaseHTTPMiddleware overhead)."""

from __future__ import annotations

from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

IMAGE_SOURCES: Final = "https://oreno3d.com https://*.oreno3d.com"
CONTENT_SECURITY_POLICY: Final = "; ".join(
    (
        "default-src 'self'",
        f"img-src 'self' data: {IMAGE_SOURCES}",
        "style-src 'self'",
        "script-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)
# Swagger UI (only when SEARCH_IWARA_API_DOCS_ENABLED) is served by FastAPI from jsDelivr.
DOCS_CONTENT_SECURITY_POLICY: Final = (
    CONTENT_SECURITY_POLICY.replace("style-src 'self'", "style-src 'self' https://cdn.jsdelivr.net")
    .replace("script-src 'self'", "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net")
    .replace("img-src 'self' data:", "img-src 'self' data: https://fastapi.tiangolo.com")
)
PERMISSIONS_POLICY: Final = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), "
    "payment=(), usb=(), interest-cohort=()"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, allow_indexing: bool = False, docs_path: str | None = None) -> None:
        self.app = app
        self.docs_path = docs_path
        self.headers: dict[str, str] = {
            "Content-Security-Policy": CONTENT_SECURITY_POLICY,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": PERMISSIONS_POLICY,
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Resource-Policy": "same-origin",
        }
        if not allow_indexing:
            self.headers["X-Robots-Tag"] = "noindex, nofollow"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if self.docs_path is not None and scope["path"] == self.docs_path:
                    headers["Content-Security-Policy"] = DOCS_CONTENT_SECURITY_POLICY
                for name, value in self.headers.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
