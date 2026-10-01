"""Logging configuration: human-readable on a TTY, one JSON object per line otherwise."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Literal, TextIO

LogFormat = Literal["auto", "text", "json"]
# Standard LogRecord attributes plus uvicorn's ANSI-coloured duplicate of the message.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"color_message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({key: value for key, value in vars(record).items() if key not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class StderrHandler(logging.StreamHandler[TextIO]):
    """Writes to whatever ``sys.stderr`` is *now* (survives stream swaps by test runners)."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self) -> Any:
        return sys.stderr

    @stream.setter
    def stream(self, value: Any) -> None:
        pass


def resolve_format(fmt: LogFormat) -> Literal["text", "json"]:
    if fmt == "auto":
        return "text" if sys.stderr.isatty() else "json"
    return fmt


def configure_logging(fmt: LogFormat = "auto", level: str = "INFO") -> Literal["text", "json"]:
    resolved = resolve_format(fmt)
    handler = StderrHandler()
    if resolved == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return resolved


def uvicorn_log_config(fmt: Literal["text", "json"], level: str) -> dict[str, Any]:
    """dictConfig for uvicorn so access/error logs share the application's format."""

    formatter: dict[str, Any] = (
        {"()": f"{__name__}.JsonFormatter"}
        if fmt == "json"
        else {"format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "datefmt": "%H:%M:%S"}
    )
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": formatter},
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.error": {"level": level},
            "uvicorn.access": {"handlers": ["default"], "level": level, "propagate": False},
            "search_iwara": {"handlers": ["default"], "level": level, "propagate": False},
        },
    }
