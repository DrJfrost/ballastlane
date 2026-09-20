"""Request correlation and timing middleware."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from taskflow.infrastructure.observability.logging import request_id_var

logger = logging.getLogger("taskflow.access")

REQUEST_ID_HEADER = "X-Request-ID"
RESPONSE_TIME_HEADER = "X-Response-Time-ms"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, echoes it back, and logs one line per request.

    An inbound ``X-Request-ID`` is honoured so a trace can span the frontend,
    a proxy and this service; otherwise one is generated. The value lands in
    a ``ContextVar`` that the JSON log formatter reads, which means every log
    line produced anywhere during the request -- including inside a use case
    that knows nothing about HTTP -- is automatically correlated.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # Logged here so the access log records the failure even though
            # the exception handler produces the body.
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(elapsed_ms, 2),
                },
            )
            raise
        finally:
            # Reset rather than leave it set: the worker task is reused, and a
            # stale id would be attached to the *next* request's logs.
            request_id_var.reset(token)

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[RESPONSE_TIME_HEADER] = f"{elapsed_ms:.2f}"

        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
                "request_id": request_id,
            },
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds the low-cost hardening headers.

    None of these matter for a JSON API consumed by fetch(), except that the
    docs pages and any error HTML *are* rendered in a browser -- and they
    cost nothing to send.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response
