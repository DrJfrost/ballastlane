"""Rate limiting.

Limiting is off for the rest of the suite -- otherwise a test that logs in a
few times would start failing for unrelated reasons. These tests build their
own app with it switched on.
"""

from __future__ import annotations

from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from taskflow.infrastructure.config.settings import Settings
from taskflow.infrastructure.db.models import Base
from taskflow.main import create_app
from taskflow.presentation.dependencies.container import Container
from taskflow.presentation.rate_limit import limiter, rate_limit_key
from tests.conftest import DEMO_PASSWORD, auth

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def limited_client(settings: Settings):
    """An app with a deliberately tiny login limit."""
    limited = settings.model_copy(
        update={
            "rate_limit_enabled": True,
            "rate_limit_login": "3/minute",
            "rate_limit_register": "2/minute",
            "rate_limit_write": "5/minute",
            "rate_limit_default": "1000/minute",
        }
    )

    container = Container(limited)
    async with container.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    app = create_app(limited)
    app.state.container = container

    # slowapi keeps counters in a module-level store shared across tests;
    # resetting it keeps each test independent of execution order.
    limiter.reset()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client
    finally:
        limiter.reset()
        limiter.enabled = False
        await container.dispose()


class TestLoginThrottling:
    async def test_repeated_failures_are_throttled(self, limited_client) -> None:
        payload = {"email": "victim@example.com", "password": "wrong-password"}

        statuses = [
            (await limited_client.post("/api/v1/auth/login", json=payload)).status_code
            for _ in range(6)
        ]

        # The first three are honest 401s; the rest are refused outright.
        assert statuses[:3] == [401, 401, 401]
        assert statuses[3:] == [429, 429, 429]

    async def test_the_429_uses_the_standard_error_envelope(self, limited_client) -> None:
        payload = {"email": "victim@example.com", "password": "wrong-password"}
        for _ in range(4):
            response = await limited_client.post("/api/v1/auth/login", json=payload)

        assert response.status_code == 429
        body = response.json()
        assert body["code"] == "rate_limit_exceeded"
        assert body["status"] == 429
        # Tell the client when to come back rather than leaving it to guess.
        assert response.headers["Retry-After"] == "60"

    async def test_rate_limit_headers_are_advertised(self, limited_client) -> None:
        """Advertise the budget so a client can back off before it is refused.

        The headers are injected after the handler returns, so they appear on
        successful responses -- not on one that raised (a 401 login), and not
        on the 429 itself, which carries ``Retry-After`` instead.
        """
        await limited_client.post(
            "/api/v1/auth/register",
            json={
                "email": "headers@example.com",
                "full_name": "Header Reader",
                "password": DEMO_PASSWORD,
            },
        )
        response = await limited_client.post(
            "/api/v1/auth/login",
            json={"email": "headers@example.com", "password": DEMO_PASSWORD},
        )

        assert response.status_code == 200
        assert response.headers["X-RateLimit-Limit"] == "3"
        assert "X-RateLimit-Remaining" in response.headers


class TestRegisterThrottling:
    async def test_signup_is_throttled(self, limited_client) -> None:
        statuses = []
        for index in range(4):
            response = await limited_client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"signup{index}@example.com",
                    "full_name": f"Person {index}",
                    "password": DEMO_PASSWORD,
                },
            )
            statuses.append(response.status_code)

        assert statuses[:2] == [201, 201]
        assert statuses[2:] == [429, 429]


class TestWriteThrottling:
    async def test_authenticated_writes_are_throttled(self, limited_client) -> None:
        await limited_client.post(
            "/api/v1/auth/register",
            json={
                "email": "writer@example.com",
                "full_name": "Busy Writer",
                "password": DEMO_PASSWORD,
            },
        )
        login = await limited_client.post(
            "/api/v1/auth/login",
            json={"email": "writer@example.com", "password": DEMO_PASSWORD},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        statuses = []
        for index in range(7):
            response = await limited_client.post(
                "/api/v1/tasks", headers=headers, json={"title": f"Task number {index}"}
            )
            statuses.append(response.status_code)

        assert statuses.count(201) == 5
        assert statuses.count(429) == 2

    async def test_reads_are_not_throttled_by_the_write_limit(self, limited_client) -> None:
        await limited_client.post(
            "/api/v1/auth/register",
            json={
                "email": "reader@example.com",
                "full_name": "Busy Reader",
                "password": DEMO_PASSWORD,
            },
        )
        login = await limited_client.post(
            "/api/v1/auth/login",
            json={"email": "reader@example.com", "password": DEMO_PASSWORD},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        statuses = [
            (await limited_client.get("/api/v1/tasks", headers=headers)).status_code
            for _ in range(10)
        ]
        assert set(statuses) == {200}


class TestBucketKey:
    def test_anonymous_requests_are_bucketed_by_ip(self) -> None:
        class _Request:
            class state:  # noqa: N801
                pass

            client = type("C", (), {"host": "203.0.113.9"})()
            headers: dict[str, str] = {}

        # A structural stand-in: ``rate_limit_key`` only reads ``state`` and
        # ``client``, so a full Starlette Request is unnecessary here.
        assert rate_limit_key(cast("Request", _Request())).startswith("ip:")

    def test_authenticated_requests_are_bucketed_by_user(self) -> None:
        """Per-user buckets, not per-IP.

        Keying only on IP throttles a whole office behind one NAT because of
        a single heavy user.
        """

        class _Request:
            class state:  # noqa: N801
                user_id = "1234"

            client = type("C", (), {"host": "203.0.113.9"})()
            headers: dict[str, str] = {}

        assert rate_limit_key(cast("Request", _Request())) == "user:1234"


class TestDisabledByDefault:
    async def test_the_main_suite_is_not_throttled(self, client, alice) -> None:
        # Guards the fixture itself: if limiting leaked into the default
        # settings, dozens of unrelated tests would start flaking.
        statuses = [
            (
                await client.post(
                    "/api/v1/tasks", headers=auth(alice), json={"title": f"Bulk {i}"}
                )
            ).status_code
            for i in range(25)
        ]
        assert set(statuses) == {201}
