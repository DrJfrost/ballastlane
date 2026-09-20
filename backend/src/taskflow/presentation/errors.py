"""Mapping from domain errors to HTTP responses.

This module is the *only* place that knows about status codes. The domain
raises ``ConflictError``; deciding that this means 409 is a transport
decision, and keeping it here is what lets the same use cases run behind a
CLI or a worker without dragging HTTP semantics along.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from taskflow.domain.errors import (
    AlreadyExistsError,
    AuthenticationError,
    ConflictError,
    DomainError,
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from taskflow.infrastructure.observability.logging import request_id_var
from taskflow.presentation.schemas.common import ProblemDetail

logger = logging.getLogger("taskflow.errors")

#: Starlette renamed this constant (``..._UNPROCESSABLE_ENTITY`` ->
#: ``..._UNPROCESSABLE_CONTENT``) and emits a DeprecationWarning for the old
#: name. Resolving it at import time keeps the app warning-free on both, which
#: matters because the test suite runs with warnings promoted to errors.
HTTP_422: int = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

#: Order matters: the most specific subclass has to be checked first, and
#: ``AlreadyExistsError`` is a ``ConflictError``.
_STATUS_BY_ERROR: tuple[tuple[type[DomainError], int], ...] = (
    (ValidationError, HTTP_422),
    (AuthenticationError, status.HTTP_401_UNAUTHORIZED),
    (PermissionDeniedError, status.HTTP_403_FORBIDDEN),
    (EntityNotFoundError, status.HTTP_404_NOT_FOUND),
    (AlreadyExistsError, status.HTTP_409_CONFLICT),
    (ConflictError, status.HTTP_409_CONFLICT),
)


def status_for(error: DomainError) -> int:
    for error_type, code in _STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return code
    return status.HTTP_400_BAD_REQUEST


def build_problem_response(
    *,
    status_code: int,
    title: str,
    detail: str,
    code: str,
    errors: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        title=title,
        status=status_code,
        detail=detail,
        code=code,
        errors=errors,
        request_id=request_id_var.get(),
    )
    response = JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        media_type="application/problem+json",
    )
    if status_code == status.HTTP_401_UNAUTHORIZED:
        # Required by RFC 9110 for a 401; also what makes a browser or an
        # HTTP client understand that re-authentication is the fix.
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status_code = status_for(exc)
        # Expected failures are logged at info; they are not incidents.
        logger.info(
            "domain_error",
            extra={
                "code": exc.code,
                "status": status_code,
                "path": request.url.path,
            },
        )
        return build_problem_response(
            status_code=status_code,
            title=exc.title,
            detail=exc.message,
            code=exc.code,
            errors=exc.details or None,
        )

    # Starlette fixes the handler signature at ``(request, exc)``, so some
    # handlers necessarily ignore one of the two.
    @app.exception_handler(RequestValidationError)
    async def _request_validation(
        request: Request,  # noqa: ARG001
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Reshape FastAPI's validation errors into the same envelope.

        FastAPI's default 422 body has a completely different shape from our
        domain errors, so a client would need two parsers. This flattens it
        into ``{"field": "message"}`` under the same ``ProblemDetail``.
        """
        fields: dict[str, str] = {}
        for error in exc.errors():
            location = [str(part) for part in error["loc"] if part != "body"]
            fields[".".join(location) or "body"] = error["msg"]

        return build_problem_response(
            status_code=HTTP_422,
            title="Validation error",
            detail="The request payload is invalid.",
            code="validation_error",
            errors=fields,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(
        request: Request,  # noqa: ARG001
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return build_problem_response(
            status_code=exc.status_code,
            title=_TITLES.get(exc.status_code, "Request failed"),
            detail=str(exc.detail),
            code=_CODES.get(exc.status_code, "http_error"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        # An unexpected exception *is* an incident: log it with the stack
        # trace, but never send internals to the client -- a stack trace in a
        # response body leaks file paths, library versions and sometimes
        # connection strings.
        logger.exception(
            "unhandled_exception",
            extra={"path": request.url.path, "method": request.method},
        )
        return build_problem_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal server error",
            detail="Something went wrong. Please try again later.",
            code="internal_error",
        )


_TITLES = {
    400: "Bad request",
    401: "Authentication failed",
    403: "Permission denied",
    404: "Resource not found",
    405: "Method not allowed",
    409: "Conflicting state",
    422: "Validation error",
    429: "Too many requests",
    500: "Internal server error",
    503: "Service unavailable",
}

_CODES = {
    400: "bad_request",
    401: "authentication_failed",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limit_exceeded",
    500: "internal_error",
    503: "service_unavailable",
}

__all__ = ["build_problem_response", "register_exception_handlers", "status_for"]
