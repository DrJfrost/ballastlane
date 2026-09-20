#!/usr/bin/env bash
#
# Container entrypoint.
#
# Waits for the database, applies migrations, optionally seeds, then hands
# over to the given command via `exec` -- so the process replaces the shell
# and receives SIGTERM directly. Without `exec`, the shell stays PID 1,
# swallows the signal, and Docker kills the container after the timeout
# instead of letting it shut down cleanly.
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# Wait for PostgreSQL
#
# `depends_on: condition: service_healthy` covers this in compose, but an
# entrypoint that also waits works under Kubernetes, Swarm and a plain
# `docker run` -- none of which have that feature.
# ---------------------------------------------------------------------------
wait_for_database() {
  if [[ "${DATABASE_URL:-}" != postgresql* ]]; then
    log "not a PostgreSQL URL; skipping the wait"
    return 0
  fi

  local attempt=1
  local max_attempts="${DB_WAIT_ATTEMPTS:-30}"

  until python - <<'PY'
import sys
from sqlalchemy import create_engine, text
from taskflow.infrastructure.config.settings import get_settings

try:
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
except Exception as exc:                      # noqa: BLE001
    print(exc, file=sys.stderr)
    sys.exit(1)
PY
  do
    if (( attempt >= max_attempts )); then
      log "database not reachable after ${max_attempts} attempts; giving up"
      exit 1
    fi
    log "database not ready (attempt ${attempt}/${max_attempts}); retrying in 1s"
    attempt=$(( attempt + 1 ))
    sleep 1
  done

  log "database is reachable"
}

wait_for_database

# ---------------------------------------------------------------------------
# Migrations
#
# Only the API container runs them (RUN_MIGRATIONS=true in compose). Letting
# the worker and beat migrate too means three processes racing on the same
# alembic_version row on every deploy.
# ---------------------------------------------------------------------------
if [[ "${RUN_MIGRATIONS:-false}" == "true" ]]; then
  log "applying migrations"
  alembic upgrade head
  log "migrations applied"
fi

if [[ "${RUN_SEED:-false}" == "true" ]]; then
  log "seeding demo data"
  python -m taskflow.scripts.seed
fi

log "starting: $*"
exec "$@"
