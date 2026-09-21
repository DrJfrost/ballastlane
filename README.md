# TaskFlow

A task management system: **FastAPI** backend on a Clean Architecture layout,
**React + TypeScript** frontend, **PostgreSQL**, **Celery + Redis**, JWT auth.

| | |
|---|---|
| **Run it** | `docker compose up --build` → <http://localhost:8080> |
| **Sign in** | `ada@taskflow.dev` / `DemoPassw0rd!2026` |
| **API docs** | <http://localhost:8000/docs> |
| **Tests** | 407 backend (93.6% coverage) + 27 frontend |

GenAI usage — the prompts, the output, and every place the model was wrong —
is documented separately in **[docs/GENAI.md](docs/GENAI.md)**.

---

## Contents

- [Setup](#setup)
- [What it does](#what-it-does)
- [Architecture](#architecture)
- [API reference](#api-reference)
- [Testing](#testing)
- [Key implementation decisions](#key-implementation-decisions)
- [Known limitations](#known-limitations)

---

## Setup

### With Docker (everything)

```bash
docker compose up --build
```

Six services: PostgreSQL, Redis, the API, a Celery worker, the Celery
scheduler, and nginx serving the built frontend. Migrations and demo data are
applied automatically on first start.

- **App** → <http://localhost:8080>
- **Swagger** → <http://localhost:8000/docs> — click **Authorize** and paste
  the `access_token` from `POST /auth/login`

Stop it with `docker compose down -v`.

**Only two ports are published**: `8000` for the API and `8080` for the web
UI. PostgreSQL and Redis are deliberately *not* mapped to the host — the API
reaches them over the compose network, so a mapping buys nothing and can cost
you the whole stack: any fixed host port may already be taken, and Docker
aborts with `port is already allocated`. Picking a less common port only
makes that rarer, not impossible.

To inspect them:

```bash
docker compose exec db psql -U taskflow -d taskflow
docker compose exec redis redis-cli
```

If 8000 or 8080 are busy on your machine, override them:

```bash
API_HOST_PORT=9000 WEB_HOST_PORT=9080 docker compose up --build
```

### Without Docker (no PostgreSQL or Redis needed)

```bash
# backend -- defaults to SQLite with Celery disabled
cd backend
uv venv --python 3.12 && uv pip install -e ".[dev]"
cp .env.example .env
uv run python -m taskflow.scripts.seed
uv run uvicorn taskflow.main:app --reload      # http://localhost:8000

# frontend, in a second terminal
cd frontend && npm install && npm run dev      # http://localhost:5173
```

With `CELERY_ENABLED=false` the app still works end to end: domain events are
recorded in-process instead of dispatched to a broker, so the whole API is
usable with zero infrastructure.

> If the Docker stack is running, ports 8000 and 8080 are already taken — run
> `docker compose down` first.

### Configuration

Every setting is an environment variable, documented in
[`backend/.env.example`](backend/.env.example) and typed in
[`settings.py`](backend/src/taskflow/infrastructure/config/settings.py). The
ones worth knowing:

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | SQLite file | `postgresql+asyncpg://…` in Docker |
| `SECRET_KEY` | random per boot | **Must** be set outside local/test |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | Rotated on every refresh |
| `CELERY_ENABLED` | `true` | `false` records events in-process instead |
| `RATE_LIMIT_ENABLED` | `true` | |
| `RATE_LIMIT_STORAGE_URL` | memory | Must be Redis when running >1 worker |

Configuration that is safe on a laptop but not in production — a
generated-at-boot secret key, SQLite, in-memory rate-limit counters — makes
the app **refuse to start** when `ENVIRONMENT=production`, rather than
booting into a subtly broken state.

### Demo data

Four users, all with password `DemoPassw0rd!2026`: `ada@`, `grace@`, `alan@`
and `margaret@taskflow.dev`.

25 tasks, chosen to exercise every filter: overdue items, items due today and
next week, undated items, one of each status and priority, tasks Ada owns and
tasks merely assigned to her, plus filler so pagination is visible. The seeder
is idempotent — rerun it to reset.

### Verifying it

```bash
bash scripts/verify.sh                 # lint, types, tests, coverage, build
bash scripts/verify.sh --with-docker   # the above, plus the running stack
```

Invoked through `bash` rather than `./` on purpose: a zip archive does not
carry the Unix execute bit, so `./scripts/verify.sh` fails with
`Permission denied` for anyone who received this as an archive rather than a
clone. (`chmod +x scripts/verify.sh` also works.)

Prints a pass/fail line per requirement and exits non-zero on any failure.
Needs no `make`, which is the usual reason a project's own checks do not run
on the first try.

Individual commands:

```bash
cd backend && uv run pytest                      # 407 tests, fails under 80% coverage
cd backend && uv run pytest -m unit              # 253 tests, no I/O, under a second
cd backend && uv run ruff check . && uv run mypy
cd frontend && npm test && npm run lint
```

There is also a [`Makefile`](Makefile) wrapping these plus the day-to-day
commands (`make api`, `make worker`, `make seed`, `make migrate`). It needs
`make`, which is why `scripts/verify.sh` exists as the portable path.

---

## What it does

A small team tracks work items. Each task has an **owner** (whoever created
it) and optionally an **assignee**.

That split is the design decision the model hangs on. A task list where every
item belongs to one person is a to-do app; separating *who is accountable*
from *who is doing it* is what makes assignment and the permission rules
meaningful.

- **CRUD** on tasks, with a validated lifecycle: `todo → in_progress → done`,
  plus `cancelled`, and legal transitions enforced in the domain.
- **Assignment** to another user, and unassignment.
- **Completion**, which records *when* and notifies the owner in the
  background.
- **Filtering** by status, priority, due-date window, overdue-only, assignee,
  owner, unassigned, and search over title and description — all combinable.
- **Sorting** by due date, priority, status, title or timestamps.
- **Pagination** with `total`, `total_pages`, `has_next`, `has_previous`.

Permissions are part of the domain, not an afterthought:

| | Owner | Assignee | Anyone else |
|---|---|---|---|
| See the task | yes | yes | **404**, not 403 |
| Change status | yes | yes | no |
| Edit content, reassign, delete | yes | no | no |

The API returns `can_edit` and `can_change_status` on every task, so the UI
disables what it is not allowed to do rather than re-implementing the rules
and drifting from them.

---

## Architecture

```
presentation  ──▶  infrastructure  ──▶  application  ──▶  domain
                                   └──────────────────────────▶
     routers            SQLAlchemy         use cases      entities
     schemas            bcrypt, PyJWT      DTOs           value objects
     DI wiring          Celery             ports          events
     error → HTTP       logging                           repo ports
```

Dependencies point **inwards only**. `domain` knows about nothing;
`application` knows only `domain`; `presentation` may know everything.

Three properties are worth checking rather than taking on trust:

1. **`taskflow/domain` imports nothing but the standard library** — no
   Pydantic, no SQLAlchemy, no FastAPI. You could copy the folder into
   another project and it would work with nothing installed.
2. **HTTP status codes appear in exactly one module**
   ([`presentation/errors.py`](backend/src/taskflow/presentation/errors.py)).
   The domain raises `ConflictError`; deciding that means 409 is a transport
   decision.
3. **Both are enforced by tests**, not by convention:
   [`tests/unit/test_architecture.py`](backend/tests/unit/test_architecture.py)
   parses the actual import statements and fails the build on a violation.
   A diagram cannot enforce a boundary; a test can.

```bash
cd backend && uv run pytest tests/unit/test_architecture.py -v
```

### Every use case has the same shape

```python
class CompleteTask:
    def __init__(self, *, uow: UnitOfWork, clock: Clock, publisher: EventPublisher): ...

    async def execute(self, command: CompleteTaskCommand) -> TaskView:
        async with self._uow as uow:
            task = await uow.tasks.get(command.task_id)
            # authorise, mutate, persist
            await uow.commit()
            view = await hydrate_task(task, users=uow.users, ...)
        await self._publisher.publish_many(task.pull_events())   # after commit
        return view
```

Transactions are explicit (the unit of work rolls back unless `commit()` was
called), events fire only for committed work, and DTOs rather than entities
cross the boundary.

### Data model

```
users                            tasks
─────                            ─────
id           uuid  PK            id            uuid  PK
email        varchar(254) UNIQUE title         varchar(200)
full_name    varchar(120)        description   text
hashed_password varchar(255)     status        varchar(20)   CHECK
is_active    bool                priority      varchar(10)   CHECK
created_at   timestamptz         owner_id      uuid → users  ON DELETE CASCADE
updated_at   timestamptz         assignee_id   uuid → users  ON DELETE SET NULL
                                 due_date      timestamptz   NULL
                                 completed_at  timestamptz   NULL
                                 created_at    timestamptz
                                 updated_at    timestamptz
```

- **UUID primary keys**: ids appear in URLs, and a sequential id leaks how
  many tasks exist and makes neighbours guessable.
- **Asymmetric `ON DELETE`**: deleting a user removes the tasks they own, but
  only unassigns the ones assigned to them — someone leaving must not delete
  other people's work.
- **A check constraint tying `completed_at` to `status = 'done'`**, because
  the ORM is not the only writer (migrations, fixtures, manual fixes).
- **Two composite indexes**, `(owner_id, status)` and
  `(assignee_id, status)`: every list query filters on owner or assignee and
  usually narrows by status. Indexing every column would slow writes for
  nothing.
- **Foreign keys enabled on SQLite** via a `PRAGMA` on connect. SQLite
  ignores them by default, so without it the `ON DELETE` rules are inert
  under test and the suite would accept data PostgreSQL rejects.

### Frontend

Organised **by feature, not by file type** — everything about tasks is in one
place instead of split across `components/`, `hooks/` and `services/`.

Server state lives in React Query; components hold only UI state (which modal
is open, what the filter form says). The filter object *is* the query key, so
"what the user asked for", "what was requested" and "what is cached" cannot
drift apart.

---

## API reference

`POST /api/v1/auth/register` · `POST /auth/login` · `POST /auth/token`
(OAuth2 form, for the Swagger **Authorize** button) · `POST /auth/refresh` ·
`GET /auth/me`

`GET /api/v1/tasks` · `POST /tasks` · `GET /tasks/{id}` · `PATCH /tasks/{id}` ·
`DELETE /tasks/{id}` · `POST /tasks/{id}/complete` · `POST /tasks/{id}/reopen` ·
`PUT /tasks/{id}/assignee` · `GET /tasks/stats`

`GET /api/v1/users` · `GET /health/live` · `GET /health/ready`

### Errors

Every failure is an [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem
document, so a client needs one parser rather than a chain of
`err.detail ?? err.message ?? err.error` guesses:

```json
{
  "title": "Validation error",
  "status": 422,
  "detail": "Due date must be in the future.",
  "code": "validation_error",
  "errors": { "field": "due_date" },
  "request_id": "9f2c1a…"
}
```

`code` is stable enough to branch on, `detail` is safe to show a user, and
`request_id` is echoed in the `X-Request-ID` header and appears on every log
line for that request.

### Filtering

```http
GET /api/v1/tasks?status=todo&status=in_progress
                 &priority=urgent
                 &due_before=2026-12-31T23:59:59Z
                 &overdue_only=true
                 &assigned_to_me=true
                 &search=architecture
                 &sort_by=priority&sort_dir=desc
                 &page=1&page_size=20
```

Repeat a parameter to combine values. `page_size` is capped at 100 — an
uncapped list endpoint is a free denial-of-service.

### Rate limiting

Four tiers: 200/min by default, 10/min on login, 5/min on register, 60/min on
writes. Buckets are keyed by **user id once authenticated and by IP before
that**: IP-only would throttle a whole office behind one NAT, and user-only
cannot work because the endpoint that most needs limiting has no user yet.

```bash
# the eleventh attempt returns 429 with Retry-After
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"email":"ada@taskflow.dev","password":"wrong"}'
done

# counters live in Redis, shared across workers
docker compose exec -T redis redis-cli -n 2 --scan
```

### Background processing

Domain events become Celery jobs: notify on assignment, on completion, on a
moved deadline, plus a daily overdue digest on Celery beat.

```bash
# assign a task, then watch the worker pick it up
docker compose logs --since 30s worker | grep -E "received|notification_sent|succeeded"

# trigger the scheduled digest by hand
docker compose exec -T worker celery \
  --app=taskflow.infrastructure.tasks.celery_app:celery_app call taskflow.scan_overdue_tasks
```

---

## Testing

**407 backend tests, 93.6% line-and-branch coverage.** The build fails below
80% (`--cov-fail-under=80`), so the figure is enforced rather than reported.

| Suite | Count | Time | What it is for |
|---|---|---|---|
| Domain | 106 | ~0.1 s | Every business rule, without a database |
| Application | 62 | ~0.1 s | Orchestration, transactions, events — against in-memory fakes |
| Infrastructure | 77 | ~0.5 s | Real bcrypt, real PyJWT, real SQL |
| Architecture | 8 | ~0.1 s | The dependency rule, by parsing imports |
| Integration | 154 | ~9 s | The real ASGI app and a real database |

The layers are tested differently on purpose. Fakes make the application
suite fast enough to run on every save, but they could agree with the use
case and still disagree with reality — so the adapters are tested against the
real libraries, and the endpoints against the real app.

Three bugs were found by writing these tests, each now covered by a named
regression test: a JWT clock inconsistency, ORM insert ordering, and Alembic
silently muting the application logger. All three are described in
[docs/GENAI.md](docs/GENAI.md).

---

## Key implementation decisions

Each one states the trade-off accepted, not just the choice.

**FastAPI rather than Django REST Framework.** DRF's serializers,
`ModelViewSet` and active-record ORM are excellent *because* they couple HTTP
to the database model; getting a persistence-ignorant domain out of Django
means fighting the framework. Cost: no Django admin, no batteries.

**Repository ports as `typing.Protocol`, not `abc.ABC`.** Adapters satisfy
them structurally, so infrastructure never imports an abstract base it must
keep in sync — the dependency exists only in the type checker. The payoff is
visible in `tests/fakes.py`. Cost: a missing method is a mypy error rather
than a runtime `TypeError`, which is only acceptable because mypy runs strict
in CI.

**ORM models separate from entities**, with an explicit mapper. Sharing one
class means the aggregate inherits from `DeclarativeBase`: every unit test
needs metadata, and a lazy-loading attribute can fire I/O from inside a
business rule — which in async SQLAlchemy is a `MissingGreenlet` exception,
not merely a slow query. Cost: ~60 lines of mapping, fully covered, and two
places to touch when a field is added.

**A `UNSET` sentinel for PATCH.** Three states per field — set, set to null,
untouched — because `None` for both of the last two makes clearing a nullable
field like `due_date` unreachable. Pydantic's `model_fields_set` supplies the
distinction at the boundary. Cost: a custom type mypy has to be taught about.

**Domain events, drained after commit.** Aggregates record `TaskAssigned`;
the use case publishes only once the transaction has committed, so a
rolled-back write can never notify. A broker failure is logged and swallowed
— the write already succeeded, and a 500 after a successful commit makes the
user retry and duplicate. Cost: best-effort delivery. A crash between commit
and publish loses the event; a transactional outbox is the fix if events ever
drive something more important than email.

**A `Clock` port.** Nothing calls `datetime.now()` inline, so every
time-dependent rule is deterministic under test — one constructor argument
instead of a pile of `freezegun` patches.

**A `typ` claim on every JWT**, checked on decode. Without it the 7-day
refresh token is a valid bearer token everywhere, and the 15-minute access
lifetime buys nothing. Refresh tokens are rotated, and the user is re-loaded
from the database on refresh so deactivation takes effect immediately rather
than in a week.

**404, not 403, for a task you are not party to.** A 403 confirms the id
exists, which turns the endpoint into an existence oracle. A 403 *is* used
once visibility is established but the action is not permitted.

**Login is not an enumeration oracle.** Identical message for a wrong
password, an unknown account and a malformed email — and a dummy bcrypt
verification on the missing-user path, because otherwise it returns in
microseconds while a real one costs 250 ms.

**Timezone-aware UTC, enforced twice.** The domain rejects naive datetimes,
and a custom `UTCDateTime` column normalises on write and re-attaches UTC on
read. PostgreSQL `TIMESTAMPTZ` round-trips correctly but SQLite returns naive
values, so comparing a loaded `due_date` against `datetime.now(UTC)` raises
`TypeError` on one backend only — passing CI and breaking locally, or the
reverse. `ruff`'s `DTZ` rules catch the rest.

**Offset pagination, with a tiebreaker.** Every `ORDER BY` ends with `id`:
without a *total* order, rows that tie can come back in a different order per
query and an item appears on two pages or none
(`test_pages_do_not_overlap_or_skip`). Cost: `OFFSET` degrades on deep pages.
Cursors do not, but cannot express "jump to page 7", which a dashboard wants.

**Sorting by priority uses a SQL `CASE` rank**, because ordering by the
column sorts alphabetically — high, low, medium, urgent — which is not the
business order.

**No N+1.** A page of tasks needs owner and assignee names; resolving them
per row makes a 20-item page 41 queries.
[`hydration.py`](backend/src/taskflow/application/use_cases/hydration.py)
batches them into one `WHERE id IN (...)`, so a page is two queries whatever
its size.

**Filtering happens in SQL**, never by post-filtering a page in Python — that
returns short pages, wrong totals, and loads rows the caller may not see.

**Tokens in `localStorage`, knowingly.** The secure option is an
`httpOnly; SameSite=Strict` cookie, which JavaScript cannot read and so
cannot leak to an XSS payload; it needs the API to set cookies plus a CSRF
strategy, which is a backend change scoped out here. Mitigations in place:
15-minute access tokens, rotation, and the standard security headers. Cost:
an XSS hole becomes a session compromise. Recorded rather than discovered.

**Dependency wiring written by hand.** An explicit `Container` and one
three-line provider per use case: the graph is greppable, a missing
dependency is a type error at import, and `Depends` overrides work per use
case in tests. Cost: ~150 lines of uniform, table-like repetition.

---

## Known limitations

Stated so they read as decisions rather than oversights.

| Limitation | Why it was accepted |
|---|---|
| No refresh-token reuse detection | Rotation without it means a leaked token still works once. Needs a token-family table — the first thing to add |
| At-least-once events, not exactly-once | A crash between commit and publish loses the event. Needs an outbox |
| Tokens in `localStorage` | Needs cookie auth plus CSRF |
| Offset pagination | Fine at this scale; the swap point is `TaskFilter` / `Pagination` |
| No optimistic concurrency on PATCH | Two owners editing concurrently: last write wins. A `version` column and `If-Match` fixes it |
| `_deliver` logs instead of sending email | A real provider is one function away; the seam is deliberate |
| No audit trail | `TaskUnassigned` is recorded and logged but not persisted |
| No admin role | The brief does not ask for one, and adding a permission check without a story that needs it is speculative. The extension point is small: one predicate on `Task`, one flag on `TaskFilter`, and the use cases stop passing `visible_to` for that role |

## Project layout

```
backend/
├── src/taskflow/
│   ├── domain/           entities, value objects, events, repository ports
│   ├── application/      use cases, DTOs, ports
│   ├── infrastructure/   SQLAlchemy, bcrypt, PyJWT, Celery, logging
│   └── presentation/     routers, schemas, DI, error mapping
├── migrations/           Alembic
└── tests/                unit/ (domain, application, infrastructure) + integration/
frontend/
└── src/
    ├── lib/              API client, error parsing, formatting
    ├── components/ui/    design-system primitives
    └── features/         auth, tasks, users (api + hooks + components)
docs/GENAI.md             GenAI usage: prompts, validation, corrections
scripts/verify.sh         runs every quality gate
docker-compose.yml
```

## Licence

MIT.
