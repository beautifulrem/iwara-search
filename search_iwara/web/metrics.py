"""Prometheus instrumentation: request latency middleware and dataset gauges."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from datetime import datetime

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..models import DatasetStatus

access_logger = logging.getLogger("search_iwara.access")


class AppMetrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests = Counter(
            "search_iwara_http_requests_total",
            "HTTP requests by route template, method and status.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.latency = Histogram(
            "search_iwara_http_request_duration_seconds",
            "HTTP request latency by route template.",
            ("method", "route"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=self.registry,
        )

    def register_dataset(
        self, status: Callable[[], DatasetStatus], *, sync_interval: int | None = None
    ) -> Callable[[], None]:
        """Register dataset gauges; returns a callable that unregisters them (lifespan exit)."""

        collector = _DatasetCollector(status, sync_interval)
        self.registry.register(collector)
        return lambda: self.registry.unregister(collector)


class _DatasetCollector(Collector):
    def __init__(self, status: Callable[[], DatasetStatus], sync_interval: int | None) -> None:
        self._status = status
        self._sync_interval = sync_interval

    def collect(self) -> Iterator[GaugeMetricFamily]:
        status = self._status()
        if self._sync_interval is not None:
            yield GaugeMetricFamily(
                "search_iwara_sync_interval_seconds",
                "Configured interval between scheduled syncs (drives the staleness alert).",
                value=self._sync_interval,
            )
        yield GaugeMetricFamily(
            "search_iwara_movies", "Active movies in the database.", value=status.movie_count
        )
        last_success = 0.0
        if status.last_success_at:
            last_success = datetime.fromisoformat(status.last_success_at).timestamp()
        yield GaugeMetricFamily(
            "search_iwara_last_sync_success_timestamp_seconds",
            "Unix time of the last successful (or partial) sync run; 0 if never.",
            value=last_success,
        )
        failed = GaugeMetricFamily("search_iwara_last_sync_failed", "1 if the most recent sync run failed.")
        failed.add_metric([], 1.0 if status.last_run_status == "failed" else 0.0)
        yield failed
        for name, value, help_text in (
            ("requests", status.last_run_requests, "HTTP requests made by the most recent sync run."),
            ("retries", status.last_run_retries, "Retried requests in the most recent sync run."),
            (
                "throttled",
                status.last_run_throttled,
                "429/503 responses received by the most recent sync run.",
            ),
        ):
            yield GaugeMetricFamily(f"search_iwara_last_sync_{name}", help_text, value=value)


class ObservabilityMiddleware:
    """Structured access log (``search_iwara.access``) plus optional Prometheus instrumentation.

    Replaces uvicorn's access log, whose JSON form is a single pre-formatted string.
    """

    def __init__(self, app: ASGIApp, *, metrics: AppMetrics | None) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            template = getattr(route, "path", None) or (
                "/static" if scope["path"].startswith("/static/") else "unmatched"
            )
            method = scope["method"]
            if self.metrics is not None:
                self.metrics.latency.labels(method, template).observe(elapsed)
                self.metrics.requests.labels(method, template, str(status_code)).inc()
            client = scope.get("client")
            access_logger.info(
                "%s %s %d",
                method,
                scope["path"],
                status_code,
                extra={
                    "method": method,
                    "path": scope["path"],
                    "route": template,
                    "status": status_code,
                    "duration_ms": round(elapsed * 1000, 2),
                    "client": client[0] if client else None,
                },
            )
