# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Builder: resolve and install dependencies into a self-contained virtualenv.
#
# Two stages so the final image carries no compilers, no build caches and no
# dev dependencies -- which is both smaller and a smaller attack surface.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# `uv` is used for installation: it resolves and installs an order of
# magnitude faster than pip, which matters most in CI.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# ``VIRTUAL_ENV`` is what ``uv pip`` looks at to find the target environment;
# ``UV_PROJECT_ENVIRONMENT`` only applies to ``uv sync``. Setting the wrong
# one fails with "No virtual environment found" even though it exists.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Dependency metadata is copied on its own first, so the (slow) install layer
# is cached and only re-runs when the dependencies actually change -- not on
# every source edit.
COPY pyproject.toml ./
COPY src/taskflow/__init__.py src/taskflow/__init__.py

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && uv pip install --no-cache .

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

# `curl` is here only for the healthcheck; everything else is left out.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# A dedicated unprivileged user. Running as root means a container escape
# starts with root on the host namespace, and it is one line to avoid.
RUN groupadd --system --gid 1001 taskflow \
    && useradd --system --uid 1001 --gid taskflow --create-home taskflow

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=taskflow:taskflow src ./src
COPY --chown=taskflow:taskflow migrations ./migrations
COPY --chown=taskflow:taskflow alembic.ini pyproject.toml ./
COPY --chown=taskflow:taskflow docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER taskflow

EXPOSE 8000

# Hits the *liveness* probe, which does not touch the database: a readiness
# check here would report the container unhealthy during a brief database
# blip and get it restarted for no reason.
# An explicit 127.0.0.1 rather than `localhost`, which inside the container
# also resolves to ::1 while uvicorn is bound to IPv4 — the probe would then
# fail on a perfectly healthy service.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/health/live || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "taskflow.main:app", "--host", "0.0.0.0", "--port", "8000"]
