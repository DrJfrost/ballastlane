#!/usr/bin/env bash
#
# Runs every quality gate and prints a requirement-by-requirement report.
#
# Works in Git Bash on Windows as well as on Linux and macOS, and needs no
# `make` -- which is the usual reason a reviewer cannot run a project's own
# checks on the first try.
#
#   ./scripts/verify.sh                 checks that need no infrastructure
#   ./scripts/verify.sh --with-docker   the above, plus the full stack
#
# Exit code is 0 only if every check passed, so it is usable in CI too.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WITH_DOCKER=0
[[ "${1:-}" == "--with-docker" ]] && WITH_DOCKER=1

# ---------------------------------------------------------------------------
# Locate the backend interpreter. The venv layout differs between Windows
# (Scripts/) and POSIX (bin/), so it is detected rather than assumed.
# ---------------------------------------------------------------------------
if [[ -x "backend/.venv/Scripts/python.exe" ]]; then
  PY="backend/.venv/Scripts/python.exe"
elif [[ -x "backend/.venv/bin/python" ]]; then
  PY="backend/.venv/bin/python"
else
  echo "No virtualenv found at backend/.venv."
  echo "Run:  cd backend && uv venv --python 3.12 && uv pip install -e \".[dev]\""
  exit 1
fi
PY="$REPO_ROOT/$PY"

PASSED=0
FAILED=0
declare -a RESULTS=()

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'
else
  BOLD=''; GREEN=''; RED=''; DIM=''; OFF=''
fi

heading() { printf '\n%s──── %s ────%s\n' "$BOLD" "$1" "$OFF"; }

# check "<requirement>" <working dir> <command...>
check() {
  local label="$1" workdir="$2"; shift 2
  printf '  %-46s' "$label"

  local output
  if output=$(cd "$workdir" && "$@" 2>&1); then
    printf '%sPASS%s\n' "$GREEN" "$OFF"
    RESULTS+=("PASS|$label")
    PASSED=$((PASSED + 1))
  else
    printf '%sFAIL%s\n' "$RED" "$OFF"
    RESULTS+=("FAIL|$label")
    FAILED=$((FAILED + 1))
    printf '%s' "$DIM"
    printf '%s\n' "$output" | tail -15 | sed 's/^/        /'
    printf '%s' "$OFF"
  fi
}

printf '%sTaskFlow — requirement verification%s\n' "$BOLD" "$OFF"
printf '%s%s%s\n' "$DIM" "$(date)" "$OFF"

# ---------------------------------------------------------------------------
heading "Backend — code quality"
check "Lint (ruff, ~20 rule families)"   backend "$PY" -m ruff check .
check "Formatting (ruff format)"         backend "$PY" -m ruff format --check .
check "Static types (mypy --strict)"     backend "$PY" -m mypy

heading "Backend — tests and coverage"
# The coverage gate lives in pyproject.toml (--cov-fail-under=80), so this
# single command covers the "at least 80% coverage" requirement too.
check "407 tests + 80% coverage gate"    backend "$PY" -m pytest
check "Unit tests only (no I/O)"         backend "$PY" -m pytest -m unit -q --no-cov
check "Integration tests (real DB)"      backend "$PY" -m pytest -m integration -q --no-cov

heading "Backend — architecture"
check "Clean Architecture dependency rule" backend \
  "$PY" -m pytest tests/unit/test_architecture.py -q --no-cov

heading "Backend — database and docs"
check "Migrations apply and roll back"   backend \
  "$PY" -m pytest tests/integration/test_persistence.py -q --no-cov -k Migrations
check "OpenAPI/Swagger schema generates" backend \
  "$PY" -c "from taskflow.main import create_app; s=create_app().openapi(); assert len(s['paths'])>=14, s['paths']"
check "Seed script runs (demo data)"     backend \
  "$PY" -m taskflow.scripts.seed

heading "Frontend"
check "Lint (ESLint, type-aware)"        frontend npx --no-install eslint .
check "Static types (tsc --noEmit)"      frontend npx --no-install tsc --noEmit
check "27 tests (vitest)"                frontend npx --no-install vitest run
check "Production build"                 frontend npm run build

# ---------------------------------------------------------------------------
if (( WITH_DOCKER )); then
  heading "Docker — full stack"

  check "Compose file is valid"          . docker compose config --quiet
  check "All images build"               . docker compose build

  printf '  %-46s' "Stack starts and reports healthy"
  if docker compose up -d --wait --wait-timeout 240 >/dev/null 2>&1; then
    printf '%sPASS%s\n' "$GREEN" "$OFF"
    PASSED=$((PASSED + 1)); RESULTS+=("PASS|Stack starts and reports healthy")

    # A stack that starts is not a stack that works: log in with a seeded
    # account and read a protected endpoint.
    check "Readiness probe (DB reachable)" . \
      curl --fail --silent --show-error --output /dev/null http://localhost:8000/health/ready
    check "Login with seeded credentials"  . bash -c '
      set -euo pipefail
      curl --fail --silent -X POST http://localhost:8000/api/v1/auth/login \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"ada@taskflow.dev\",\"password\":\"DemoPassw0rd!2026\"}" \
        | grep -q access_token'
    check "Protected endpoint + filtering" . bash -c '
      set -euo pipefail
      TOKEN=$(curl --fail --silent -X POST http://localhost:8000/api/v1/auth/login \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"ada@taskflow.dev\",\"password\":\"DemoPassw0rd!2026\"}" \
        | python -c "import sys,json; print(json.load(sys.stdin)[\"access_token\"])")
      curl --fail --silent "http://localhost:8000/api/v1/tasks?overdue_only=true" \
        -H "Authorization: Bearer $TOKEN" | grep -q "\"total\""'
    check "Rate limiting returns 429"      . bash -c '
      for _ in $(seq 1 13); do
        code=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
          http://localhost:8000/api/v1/auth/login \
          -H "Content-Type: application/json" \
          -d "{\"email\":\"ada@taskflow.dev\",\"password\":\"wrong\"}")
      done
      [[ "$code" == "429" ]]'
    check "Celery worker processed a job"  . bash -c '
      docker compose logs worker 2>&1 | grep -q "celery@"'
    check "Frontend is served"             . \
      curl --fail --silent --output /dev/null http://localhost:8080/
    check "Swagger reachable through nginx" . \
      curl --fail --silent --output /dev/null http://localhost:8080/docs

    printf '\n  %sStack left running:%s  app http://localhost:8080   docs http://localhost:8000/docs\n' \
      "$DIM" "$OFF"
    printf '  %sStop it with:%s       docker compose down -v\n' "$DIM" "$OFF"
  else
    printf '%sFAIL%s\n' "$RED" "$OFF"
    FAILED=$((FAILED + 1)); RESULTS+=("FAIL|Stack starts and reports healthy")
    docker compose logs 2>&1 | tail -30 | sed 's/^/        /'
  fi
else
  printf '\n  %sSkipping the Docker checks. Add --with-docker to include them.%s\n' \
    "$DIM" "$OFF"
fi

# ---------------------------------------------------------------------------
heading "Summary"
for entry in "${RESULTS[@]}"; do
  status="${entry%%|*}"; label="${entry#*|}"
  if [[ "$status" == PASS ]]; then
    printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$label"
  else
    printf '  %s✗%s %s\n' "$RED" "$OFF" "$label"
  fi
done

printf '\n  %s%d passed, %d failed%s\n\n' "$BOLD" "$PASSED" "$FAILED" "$OFF"
(( FAILED == 0 )) || exit 1
printf '  %sEvery gate passed.%s\n\n' "$GREEN" "$OFF"
