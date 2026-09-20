"""Typed application settings, loaded from the environment."""

from __future__ import annotations

import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[4]

#: Shortest key that gives HS256 its full 256 bits of strength.
MIN_SECRET_KEY_LENGTH = 32


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production_like(self) -> bool:
        return self in (Environment.STAGING, Environment.PRODUCTION)


class Settings(BaseSettings):
    """Single source of truth for configuration.

    Everything that differs between a laptop, CI and production is read from
    the environment, never hard-coded and never branched on with
    ``if DEBUG:`` scattered through the code (12-factor, config in env).
    """

    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- app
    environment: Environment = Environment.LOCAL
    debug: bool = False
    app_name: str = "TaskFlow API"
    app_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # ----------------------------------------------------------- database
    database_url: str = f"sqlite+aiosqlite:///{BACKEND_ROOT / 'taskflow.db'}"
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_pre_ping: bool = True

    # ----------------------------------------------------------- security
    secret_key: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_urlsafe(48)))
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "taskflow"
    access_token_ttl_minutes: Annotated[int, Field(ge=1, le=1440)] = 15
    refresh_token_ttl_days: Annotated[int, Field(ge=1, le=90)] = 7
    bcrypt_rounds: Annotated[int, Field(ge=4, le=16)] = 12

    # --------------------------------------------------------------- cors
    # ``NoDecode`` is required: pydantic-settings JSON-decodes complex types
    # straight from the environment, so a plain comma-separated value would
    # blow up before the validator below ever runs.
    cors_origins: Annotated[tuple[str, ...], NoDecode] = (
        "http://localhost:5173",
        "http://localhost:4173",
        "http://localhost:3000",
        "http://localhost:8080",
    )

    # -------------------------------------------------------- rate limits
    rate_limit_enabled: bool = True
    rate_limit_default: str = "200/minute"
    rate_limit_login: str = "10/minute"
    rate_limit_register: str = "5/minute"
    rate_limit_write: str = "60/minute"
    rate_limit_storage_url: str | None = None

    # ------------------------------------------------------------- celery
    celery_enabled: bool = True
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_task_always_eager: bool = False
    overdue_scan_cron_hour: Annotated[int, Field(ge=0, le=23)] = 7

    # --------------------------------------------------------------- docs
    docs_enabled: bool = True

    # ---------------------------------------------------------- seed data
    seed_password: SecretStr = SecretStr("DemoPassw0rd!2026")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string so docker-compose stays readable."""
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        """Fail fast on configuration that is only safe on a laptop.

        A generated-at-boot secret key is convenient locally and catastrophic
        in production: every restart would invalidate all tokens, and worse,
        each replica in a cluster would sign with a different key. Better to
        refuse to start than to boot into a broken auth system.
        """
        if not self.environment.is_production_like:
            return self
        if len(self.secret_key.get_secret_value()) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters "
                "outside local/test."
            )
        if self.debug:
            raise ValueError("DEBUG must be off in staging and production.")
        if self.database_url.startswith("sqlite"):
            raise ValueError("SQLite is not supported in staging or production.")
        if self.rate_limit_enabled and not self.rate_limit_storage_url:
            raise ValueError(
                "RATE_LIMIT_STORAGE_URL must point at shared storage (e.g. Redis) "
                "outside local/test; in-memory counters are per-worker and would "
                "multiply the configured limit by the number of workers."
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_rate_limit_storage_url(self) -> str:
        """Where the rate limiter keeps its counters.

        Defaults to in-process memory so that ``uvicorn`` runs with no
        infrastructure at all. That default is only correct for a single
        worker: memory counters are per-process, so with N workers the
        effective limit silently becomes N times the configured one.
        ``docker-compose.yml`` therefore sets this to Redis explicitly, and
        :meth:`_guard_production` refuses to start a production deployment
        without it.
        """
        return self.rate_limit_storage_url or "memory://"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """The same database, with a blocking driver, for Alembic and Celery."""
        return self.database_url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor.

    Settings are immutable for the lifetime of the process; parsing them once
    keeps ``Depends(get_settings)`` free and makes the cache easy to clear in
    tests via ``get_settings.cache_clear()``.
    """
    return Settings()
