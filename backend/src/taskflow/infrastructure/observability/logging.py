"""Structured logging."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

#: Carries the current request id across ``await`` boundaries. A module-level
#: global would be shared by every concurrent request; a ContextVar is
#: per-task, which is exactly the scope of one HTTP request.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Emits one JSON object per line.

    Plain text logs are pleasant to read and useless to query. JSON lines let
    a log aggregator filter by ``request_id`` and follow a single request
    across the API and the Celery worker.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id

        # Anything passed via ``extra=`` becomes a top-level field.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


#: Marks the handler this module owns, so repeated configuration replaces it
#: instead of stacking duplicates.
_OWNED = "_taskflow_owned_handler"


def configure_logging(*, level: str = "INFO", as_json: bool = True) -> None:
    """Install the application log handler.

    Idempotent, and deliberately *narrow*: it removes only the handler it
    installed previously, never everything on the root logger. Wiping
    ``root.handlers`` is the usual shortcut and it silently breaks whatever
    the host process attached -- pytest's log capture, a gunicorn handler, an
    APM agent -- in a way that looks like the logs simply vanished.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if as_json
        else logging.Formatter("%(levelname)-8s %(name)s :: %(message)s")
    )
    setattr(handler, _OWNED, True)

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _OWNED, False):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # These libraries install their own handlers and would otherwise print
    # every line twice, in their own format.
    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logger = logging.getLogger(noisy)
        for existing in list(logger.handlers):
            logger.removeHandler(existing)
        logger.addHandler(handler)
        logger.propagate = False
