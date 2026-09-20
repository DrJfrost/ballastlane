"""Aggregates the v1 routers."""

from __future__ import annotations

from fastapi import APIRouter

from taskflow.presentation.api.v1.routers import auth, tasks, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(tasks.router)
api_router.include_router(users.router)

__all__ = ["api_router"]
