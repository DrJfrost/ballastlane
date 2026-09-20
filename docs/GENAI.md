# Working with a GenAI coding tool

**Tool used:** Claude Code (CLI, agentic mode — it can read and write files
and run commands, so it can execute the test suite it writes).

This document answers the four questions the exercise asks: the prompts, the
output, how I validated it, and what I corrected. The short version is that
the model was excellent at structure and consistently wrong about the edges
between libraries — and those edges are where the bugs were.

---

## 1. Prompt strategy

I did not ask for "a task API". A single large prompt produces a single
large plausible-looking file, and reviewing it is harder than writing it.
Three things made the difference:

1. **Constrain the architecture up front.** Stating the dependency rule as a
   rule, with the layer names, gets a layered result. Asking for
   "clean code" gets a `services/` folder.
2. **Ask for the rationale in the code.** Requiring a comment that says *why*
   makes the weak reasoning visible: where the model could not justify a
   choice, the comment was vague, and that was reliably where the bug was.
3. **Make it run what it writes.** The agentic loop matters. Three real bugs
   below were found because the model executed the suite and had to explain a
   red test rather than assert the code was correct.

### Prompt 1 — scaffold and the dependency rule

> Build a task-management REST API with FastAPI on a strict Clean
> Architecture layout. Four packages under `src/taskflow/`:
>
> - `domain/` — entities, value objects, domain events, repository ports.
>   **Must import nothing but the Python standard library.** No Pydantic, no
>   SQLAlchemy, no FastAPI.
> - `application/` — one use-case class per business operation, each with a
>   single `execute()` taking a command DTO and returning a view DTO. DTOs
>   are frozen dataclasses, not Pydantic models. Define ports (Protocols) for
>   clock, password hashing, tokens, unit of work, event publishing.
> - `infrastructure/` — SQLAlchemy 2.0 async, bcrypt, PyJWT, Celery.
>   Implements the ports. ORM models separate from the entities, with an
>   explicit mapper.
> - `presentation/` — FastAPI routers, Pydantic schemas, DI wiring. The only
>   layer allowed to know HTTP status codes.
>
> Dependencies point inwards only. Also write a test that parses the actual
> imports and fails if that rule is broken.
>
> Domain: a Task has an owner and an optional assignee. Status
> `todo/in_progress/done/cancelled` with an explicit legal-transition graph.
> Owner may edit and delete; assignee may only change status; anyone else
> cannot see it at all.
>
> Every non-obvious line gets a comment explaining *why*, not what.

### Prompt 2 — the edge cases I wanted covered on purpose

> Now handle these specifically, and comment why each matters:
>
> - PATCH must distinguish "field omitted" from "field explicitly null", so
>   `due_date` can be *cleared*. Use a sentinel, not `None`.
> - All datetimes timezone-aware UTC. Reject naive values at the domain
>   boundary. Note that SQLite returns naive datetimes even from a
>   `DateTime(timezone=True)` column — handle it so the same code works on
>   PostgreSQL and SQLite.
> - Login must not be an account-enumeration oracle: identical message and
>   comparable timing for "no such user" and "wrong password".
> - A task the caller is not party to returns 404, not 403.
> - Escape `%` and `_` in the search term before it reaches `LIKE`.
> - Sorting by priority must use business order, not alphabetical.
> - Every list query must be scoped in SQL, never post-filtered in Python.

### Prompt 3 — the review prompt (the most valuable one)

> Review what you just wrote as a hostile senior reviewer. For each finding
> give me the failure scenario — concrete inputs, wrong output. Look
> specifically for: N+1 queries; anything that publishes a side effect before
> the transaction commits; naive/aware datetime mixing; a `Protocol` an
> adapter does not actually satisfy; pagination that can show an item twice;
> and anywhere a test passes for a reason other than the code being correct.

That third prompt found more than the first two produced. It is worth more
than asking for more features.

---

## 2. Representative output

The model's first pass at the `Task` aggregate was genuinely good — the
structure below is close to what shipped:

```python
@dataclass(eq=False, slots=True)
class Task(AggregateRoot):
    id: UUID
    title: TaskTitle
    status: TaskStatus
    owner_id: UUID
    assignee_id: UUID | None = None
    due_date: datetime | None = None

    def complete(self, *, actor_id: UUID, now: datetime) -> None:
        if self.status is TaskStatus.DONE:
            raise ConflictError("Task is already completed.")
        was_overdue = self.is_overdue(now)
        self.status = TaskStatus.DONE
        self.completed_at = now
        self.record(TaskCompleted(
            occurred_at=now, task_id=self.id, completed_by=actor_id,
            owner_id=self.owner_id, was_overdue=was_overdue,
        ))

    def is_overdue(self, now: datetime) -> bool:
        return self.due_date is not None and self.status.is_open and self.due_date < now
```

Identity-based equality, an injected `now`, recorded events instead of
direct side effects — all correct first time. **Within a single well-scoped
file the model is strong.**

Where it broke down was between files and between libraries.

---

## 3. How I validated it

In this order, because each step catches what the previous cannot:

| Step | What it catches | Result here |
|---|---|---|
| Read it against the prompt | Requirements silently dropped | Caught a placeholder returning `0` |
| `mypy --strict` | Type lies, unsatisfied Protocols | 13 real errors in `src` |
| `ruff` with `DTZ`, `S`, `ASYNC`, `PL` | Naive datetimes, `assert` in production, blocking calls in async | Found `assert` used for control flow |
| Run the suite | Code that does not work | 3 genuine bugs |
| **Check the tests, not just their colour** | Tests that pass vacuously | 2 tests were asserting the wrong thing |
| Run it in Docker against PostgreSQL | SQLite-only behaviour | Caught a boolean default PostgreSQL rejects |

That fifth row is the one people skip. Two examples from this build:

**A test that passed for the wrong reason.** My LIKE-escaping test asserted
`search=_` returns nothing. It returned six rows and I nearly "fixed" the
escaping. The escaping was correct: the seeded titles contain literal
underscores (`Task to_be_overdue`), so six rows is the *right* answer. The
test was wrong. It now asserts the property that actually matters — that
`_` matches only titles containing a literal underscore, and strictly fewer
than all of them:

```python
result = await titles(client, alice, "search=_&page_size=100")
everything = await titles(client, alice, "page_size=100")
assert len(result) < len(everything)
assert all("_" in title for title in result)
```

**A test that could not fail.** An early version asserted
`{"status": "invented"}` is rejected on create. It was not — `CreateTaskRequest`
has no `status` field, and Pydantic ignores unknown keys by default. Rather
than delete the test I changed the code: request bodies now set
`extra="forbid"`. A client typo like `asignee_id` was silently dropped and
returned 200 with nothing changed; it now returns a 422 naming the field.

---

## 4. What I corrected

### 4.1 The clock abstraction was bypassed in half of one class

The model injected a `Clock` port and used it to *issue* tokens, then let
PyJWT validate expiry against `time.time()`. Both look right in isolation.

```python
# what it wrote
def issue(self, *, subject, token_type):
    issued_at = self._clock.now()                      # injected clock
    ...

def decode(self, token, *, expected_type):
    claims = jwt.decode(token, self._secret_key, ...)  # PyJWT checks exp itself
```

**Failure scenario.** A service whose clock is set to any past date issues a
token and immediately rejects it as expired. My test caught it the first time
it ran: `test_issue_then_decode_round_trip` failed because the fixed clock
was three months behind the real one.

**Fix.** Turn off PyJWT's expiry check and use the same clock on both paths,
with a 10-second leeway for NTP drift between replicas:

```python
options={"require": [...], "verify_exp": False},
...
if expires_at + self.LEEWAY <= self._clock.now():
    raise AuthenticationError("Invalid or expired token.", details={"reason": "expired"})
```

Covered by a named regression test.

**Why the model got it wrong:** each half is idiomatic. Nothing is wrong
*locally*. The inconsistency is only visible if you ask "which clock is
authoritative here?" — which is a design question, not a syntax one.

### 4.2 A Unit of Work that could not insert a parent and a child

The model declared foreign-key columns and, correctly per the prompt, no
`relationship()` (to prevent lazy loading). Adding a user and a task in one
transaction then failed:

```
IntegrityError: FOREIGN KEY constraint failed
[SQL: INSERT INTO tasks ...]
```

**Diagnosis.** `Base.metadata.sorted_tables` knew the order (`users`, then
`tasks`), but SQLAlchemy's *unit of work* sorts **mappers**, and a bare
`ForeignKey` column gives it no mapper-level dependency. It emitted the
inserts in arbitrary order. I verified this rather than guessed:

```python
print([t.name for t in Base.metadata.sorted_tables])  # ['users', 'tasks'] -- correct
# ...and the flush still inserted tasks first.
```

**Fix.** Declare the relationships *for ordering*, with `lazy="raise"` so the
original goal is preserved — reading `row.owner` raises rather than emitting
a hidden SELECT:

```python
owner: Mapped[UserModel] = relationship(foreign_keys=[owner_id], lazy="raise")
```

My own first attempt at the fix added `viewonly=True`, which is *wrong*:
view-only relationships are deliberately excluded from the dependency sort,
so it fixed nothing. The comment in the model records that, because it is a
trap someone will otherwise fall into again.

### 4.3 Alembic silently muted the application's logging

The generated `migrations/env.py` had the standard line:

```python
fileConfig(config.config_file_name)
```

**Failure scenario.** `disable_existing_loggers` defaults to **True**, so
every logger not named in `alembic.ini` — all of `taskflow.*` — is switched
off. Invisible when Alembic runs as its own process; it mutes the entire
application whenever migrations run *in-process*: from a test suite, or from
a startup hook that upgrades the schema before serving traffic.

**How I found it.** Three unrelated `caplog` tests passed alone and failed in
the full suite. I bisected by test file rather than theorising:

```bash
for f in tests/integration/*.py; do pytest "$f" "$FAILING_TEST" -q; done
# -> only test_persistence.py (the file that runs migrations) broke it
```

**Fix.** `fileConfig(config.config_file_name, disable_existing_loggers=False)`,
plus a regression test that asserts `logging.getLogger("taskflow.events").disabled`
is `False` after an upgrade.

### 4.4 Autogenerated migration that could not run

`alembic revision --autogenerate` produced a migration referencing my custom
column type with no import for it:

```python
sa.Column('created_at', taskflow.infrastructure.db.types.UTCDateTime(), ...)
#                       ^^^^^^^^ NameError on first run
```

**Fix.** `user_module_prefix="taskflow_types."` in `env.py` and a matching
import in `script.py.mako`, so every future autogenerated revision is
runnable. This is a tooling gap, not a model failure — but it is exactly the
kind of generated output that is accepted because it *looks* complete.

### 4.5 Rate limits read the wrong settings object

The model's `limit()` helper resolved its value through `get_settings()`.
Plausible, and wrong: `get_settings()` is an `lru_cache`'d process-wide
object, so an app constructed with overridden limits silently enforced the
global ones. The symptom was five rate-limit tests failing with 201 where
429 was expected.

I first checked *why* slowapi could not see the request instead of patching
around it:

```python
# slowapi/wrappers.py -- LimitGroup.__iter__
limit_raw = self.__limit_provider()   # called with no arguments
```

The provider genuinely cannot reach `request.app.state`, so a module-level
holder is the right answer — but an *explicit* one, installed by the app
factory, with a comment stating why `get_settings()` looked equivalent and
was not.

### 4.6 Smaller corrections

| What the model wrote | Why it is wrong | Fix |
|---|---|---|
| `server_default=text("1")` for a boolean | PostgreSQL rejects an integer literal as a boolean default; SQLite accepts it, so it passes locally | `text("true")` |
| `assert self._session is not None` in the UoW | Assertions are stripped under `python -O` — the check vanishes in production | Raise `RuntimeError` from a `_require_session()` helper |
| A new `Engine` per Celery task | A fresh pool per task; a busy worker exhausts PostgreSQL connections | `@lru_cache` the engine per process |
| `expires_in_seconds` returning `0` | A placeholder that type-checks and is silently wrong | Compute from `issued_at` |
| `root.handlers = [handler]` | Wipes whatever the host process installed (pytest's capture, an APM agent) | Remove only the handler this module tagged |
| `configure_logging` called before the app exists | — | Idempotent, so repeated calls do not double every log line |
| `status.HTTP_422_UNPROCESSABLE_ENTITY` | Deprecated in current Starlette; the suite runs with warnings as errors | Resolve the constant at import, tolerating both names |
| `cors_origins: tuple[str, ...]` from env | pydantic-settings JSON-decodes complex types, so `a,b` raises before the validator runs | `Annotated[tuple[str, ...], NoDecode]` |

---

## 5. Assessing performance and idiomatic quality

The model does not think about cost unless asked. Things I had to require
explicitly:

- **N+1.** The first `ListTasks` resolved owner and assignee per row — 41
  queries for a 20-item page. Replaced with one batched
  `WHERE id IN (...)` in `hydration.py`.
- **Filtering in SQL.** Early code fetched a page and filtered visibility in
  Python: short pages, wrong totals, and rows loaded that the caller may not
  see.
- **`ORDER BY priority`.** Sorts alphabetically — high, low, medium, urgent.
  Replaced with a SQL `CASE` rank.
- **A pagination tiebreaker.** Without a secondary sort on `id` the order is
  not total, so an item can appear on two pages or none. The test that proves
  it is `test_pages_do_not_overlap_or_skip`.
- **Counters in the database.** `/tasks/stats` uses `COUNT(*)`, not
  `len(rows)`.

On idiom, modern-Python suggestions were good (PEP 695 generics, `StrEnum`,
`match`, `slots=True` dataclasses). Two habits needed correcting:

- **Reaching for `Any` when a type got awkward.** `mypy --strict` surfaced
  each one; the interesting case was `_apply_assignment` re-reading a command
  field and widening a value the caller had already narrowed. The fix — pass
  the narrowed value as a parameter — is better code, not just quieter types.
- **Blanket `# noqa` to silence a linter.** Every suppression in this
  codebase now names its rule and states the reason, and the genuinely
  structural ones (FastAPI's unused `request`/`response`, Celery's `self`,
  SQLAlchemy's `dialect`) are `per-file-ignores` with an explanation in
  `pyproject.toml` instead of noise at 40 call sites.

---

## 6. What I would tell another engineer

1. **Specify the constraint, not the outcome.** "Domain imports only the
   standard library" produces a clean domain. "Write clean code" does not.
2. **The review prompt earns more than the build prompt.** Ask for failure
   scenarios with concrete inputs; a model that has to produce one either
   finds a real bug or admits there is none.
3. **Green tests are evidence about the tests.** Both of the vacuous tests
   here were written by the same tool that wrote the code, and they agreed
   with each other. Read the assertion and ask what would have to break for
   it to fail.
4. **The bugs live between libraries.** Every real defect in this build was
   at a seam — clock vs. PyJWT, FK columns vs. the ORM's flush order,
   Alembic vs. `logging`, slowapi vs. settings. Within one file the model is
   reliable; across a boundary it is confidently plausible.
5. **Make the invariant executable.** `test_architecture.py` is ~90 lines and
   it is the reason the layering will still hold in six months. An
   architecture you can only verify by reading is an architecture that
   erodes.
