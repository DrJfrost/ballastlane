"""Application factory and ASGI entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from taskflow.infrastructure.config.settings import Settings, get_settings
from taskflow.infrastructure.observability.logging import configure_logging
from taskflow.presentation.api.v1.router import api_router
from taskflow.presentation.api.v1.routers import health
from taskflow.presentation.dependencies.container import Container
from taskflow.presentation.errors import register_exception_handlers
from taskflow.presentation.middleware.request_context import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from taskflow.presentation.rate_limit import register_rate_limiting

logger = logging.getLogger("taskflow.app")

DESCRIPTION = """
A task management API built with **FastAPI** on a **Clean Architecture** layout.

### Getting started
1. `POST /api/v1/auth/login` with one of the seeded accounts
   (`ada@taskflow.dev` / `DemoPassw0rd!2026`).
2. Click **Authorize** above and paste the `access_token`.
3. Every `/tasks` endpoint is now available.

### Layers
| Layer | Package | Depends on |
|---|---|---|
| Domain | `taskflow.domain` | nothing |
| Application | `taskflow.application` | domain |
| Infrastructure | `taskflow.infrastructure` | application, domain |
| Presentation | `taskflow.presentation` | all of the above |

Errors follow [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem
details, so `code` is stable enough to branch on and `detail` is safe to show
to a user.
"""

TAGS_METADATA = [
    {"name": "Authentication", "description": "Register, log in, rotate tokens."},
    {"name": "Tasks", "description": "CRUD, assignment, lifecycle, filtering."},
    {"name": "Users", "description": "Directory used by the assignee picker."},
    {"name": "Health", "description": "Liveness and readiness probes."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI app.

    A factory rather than a module-level ``app = FastAPI()`` so the test
    suite can build an isolated instance with its own settings and database,
    instead of mutating global state and hoping test order does not matter.
    """
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, as_json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = Container(settings)
        app.state.container = container
        logger.info(
            "application_started",
            extra={
                "environment": settings.environment.value,
                "celery_enabled": settings.celery_enabled,
                "rate_limit_enabled": settings.rate_limit_enabled,
            },
        )
        try:
            yield
        finally:
            # Releases the pool; without it, reloads and tests leak
            # connections until the database refuses new ones.
            await container.dispose()
            logger.info("application_stopped")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        # Docs are disabled in production by default: the schema is a precise
        # map of the attack surface, and there is no reason to publish it.
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        contact={"name": "TaskFlow", "url": "https://github.com/"},
        license_info={"name": "MIT"},
    )

    # Order matters: middleware runs outside-in on the way down. Request
    # context is outermost so every later layer (including the rate limiter
    # and the error handlers) logs with a request id attached.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # An explicit list, never ``["*"]``: with credentials enabled a
        # wildcard is rejected by browsers, and without that check any site
        # could call the API with the user's token.
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Response-Time-ms", "Retry-After"],
        max_age=600,
    )

    register_rate_limiting(app, settings)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs" if settings.docs_enabled else "/health/live")

    return app


#: Module-level instance for ``uvicorn taskflow.main:app``.
app = create_app()
