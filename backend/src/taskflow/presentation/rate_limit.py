"""Rate limiting.

Built on ``slowapi`` (a Starlette wrapper around ``limits``). Two tiers:

* a **default** limit applied to every route by the middleware;
* **tighter** per-route limits on the endpoints worth brute-forcing, applied
  with the :func:`limit` decorator.

The limiter is a module-level singleton because the decorators are evaluated
at import time, when there is no app instance yet. ``enabled`` and the
middleware are still driven by settings at startup, so the test suite can
switch limiting off without re-importing anything.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, status
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from taskflow.infrastructure.config.settings import Settings, get_settings
from taskflow.presentation.errors import build_problem_response

logger = logging.getLogger("taskflow.ratelimit")


def rate_limit_key(request: Request) -> str:
    """Bucket by authenticated user when known, else by client IP.

    Keying purely on IP punishes everyone behind a shared NAT or corporate
    proxy: one heavy user would throttle a whole office. Keying purely on the
    user id cannot work either, because the endpoint that most needs limiting
    -- login -- has no user yet. Hence: user id once authenticated, IP before.

    ``request.state.user_id`` is set by the auth dependency and simply absent
    on anonymous routes.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


_settings = get_settings()

limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=[_settings.rate_limit_default],
    storage_uri=_settings.effective_rate_limit_storage_url,
    enabled=_settings.rate_limit_enabled,
    # Emit the standard ``X-RateLimit-*`` headers so a well-behaved client can
    # back off before it ever sees a 429.
    headers_enabled=True,
    strategy="fixed-window",
)


class _ActiveLimits:
    """The limits currently in force, installed by the app factory.

    A module-level holder is needed because the ``@limit(...)`` decorators run
    at *import* time, when no app exists -- but the values must come from the
    settings the app was actually built with. Reading ``get_settings()``
    inside the resolver looked equivalent and was not: it is a different,
    process-wide object, so an app constructed with overridden limits silently
    enforced the global ones instead.

    slowapi calls a dynamic limit provider with no arguments (see
    ``slowapi.wrappers.LimitGroup.__iter__``), so the request -- and therefore
    ``request.app.state`` -- is not reachable from there.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings


_active = _ActiveLimits(_settings)

#: Resolved per request through a callable, so changing the settings at
#: startup is enough; the decorators do not capture a value.
_LIMIT_RESOLVERS: dict[str, Callable[[], str]] = {
    "login": lambda: _active.settings.rate_limit_login,
    "register": lambda: _active.settings.rate_limit_register,
    "write": lambda: _active.settings.rate_limit_write,
    "default": lambda: _active.settings.rate_limit_default,
}


def limit(kind: str) -> Callable[[Any], Any]:
    """Apply a named rate limit to a route.

    Usage::

        @router.post("/login")
        @limit("login")
        async def login(request: Request, ...): ...

    The ``request: Request`` parameter is mandatory -- slowapi locates it by
    name to derive the bucket key, and silently skips the limit without it.
    """
    try:
        resolver = _LIMIT_RESOLVERS[kind]
    except KeyError as exc:  # pragma: no cover - programmer error
        raise ValueError(
            f"Unknown rate limit '{kind}'. Known: {sorted(_LIMIT_RESOLVERS)}."
        ) from exc
    return limiter.limit(resolver)


def register_rate_limiting(app: FastAPI, settings: Settings) -> Limiter:
    # Install this app's limits so the decorators resolve against them.
    _active.settings = settings
    limiter.enabled = settings.rate_limit_enabled
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    if settings.rate_limit_enabled:
        # Applies ``default_limits`` to every route; the per-route decorators
        # stack on top for the sensitive ones.
        app.add_middleware(SlowAPIMiddleware)

    return limiter


async def _rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    detail = getattr(exc, "detail", "too many requests")
    logger.warning(
        "rate_limit_exceeded",
        extra={
            "path": request.url.path,
            "bucket": rate_limit_key(request),
            "limit": str(detail),
        },
    )
    response = build_problem_response(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        title="Too many requests",
        detail=f"Rate limit exceeded ({detail}). Please slow down and retry.",
        code="rate_limit_exceeded",
    )
    # Tell the client when to come back instead of leaving it to guess.
    response.headers["Retry-After"] = "60"
    return response
