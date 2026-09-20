"""Liveness and readiness probes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from taskflow.presentation.dependencies.container import ContainerDep
from taskflow.presentation.schemas.common import HealthResponse

logger = logging.getLogger("taskflow.health")

router = APIRouter(tags=["Health"])


@router.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Answers as long as the process is up. Never touches the database.",
)
async def liveness(container: ContainerDep) -> HealthResponse:
    # Deliberately dependency-free: a liveness probe that checks the database
    # will restart a perfectly healthy API during a brief database blip,
    # turning a degradation into an outage.
    return HealthResponse(
        status="ok",
        version=container.settings.app_version,
        environment=container.settings.environment.value,
    )


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description="Verifies the database connection; use this one for load-balancer checks.",
    responses={503: {"description": "A dependency is unavailable."}},
)
async def readiness(container: ContainerDep, response: Response) -> HealthResponse:
    database = "ok"
    try:
        async with container.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness_check_failed")
        database = "unavailable"
        # 503 so the orchestrator stops routing traffic here, without killing
        # the container the way a failed liveness probe would.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=container.settings.app_version,
        environment=container.settings.environment.value,
        database=database,
    )
