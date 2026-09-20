"""Auth endpoints, end to end through the real ASGI app and a real database."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import DEMO_PASSWORD, auth, register_and_login

pytestmark = [pytest.mark.integration]


class TestRegister:
    async def test_creates_an_account(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "New.Person@Example.com",
                "full_name": "New Person",
                "password": DEMO_PASSWORD,
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "new.person@example.com"
        assert body["initials"] == "NP"
        assert body["is_active"] is True
        # The response shape is the contract: no credentials, ever.
        assert "hashed_password" not in body
        assert "password" not in body

    async def test_duplicate_email_returns_409_with_a_stable_code(
        self, client: AsyncClient
    ) -> None:
        payload = {
            "email": "dup@example.com",
            "full_name": "First Person",
            "password": DEMO_PASSWORD,
        }
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201

        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 409
        assert response.json()["code"] == "already_exists"
        assert response.headers["content-type"].startswith("application/problem+json")

    @pytest.mark.parametrize(
        ("payload", "bad_field"),
        [
            ({"email": "nope", "full_name": "A Person", "password": DEMO_PASSWORD}, "email"),
            ({"email": "a@b.co", "full_name": "A", "password": DEMO_PASSWORD}, "full_name"),
            ({"email": "a@b.co", "full_name": "A Person", "password": "short"}, "password"),
        ],
    )
    async def test_validation_errors_name_the_offending_field(
        self, client: AsyncClient, payload: dict, bad_field: str
    ) -> None:
        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "validation_error"
        assert bad_field in " ".join(body["errors"])

    async def test_missing_body_is_a_422_not_a_500(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/auth/register", json={})
        assert response.status_code == 422


class TestLogin:
    async def test_returns_a_usable_token_pair(self, client: AsyncClient) -> None:
        await register_and_login(client, email="login@example.com")

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": DEMO_PASSWORD},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 900
        assert body["access_token"] and body["refresh_token"]

    async def test_email_is_case_insensitive(self, client: AsyncClient) -> None:
        await register_and_login(client, email="mixed@example.com")
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "MIXED@EXAMPLE.COM", "password": DEMO_PASSWORD},
        )
        assert response.status_code == 200

    @pytest.mark.parametrize(
        ("email", "password"),
        [
            ("login@example.com", "definitely-wrong"),
            ("ghost@example.com", DEMO_PASSWORD),
        ],
    )
    async def test_wrong_credentials_and_unknown_user_are_indistinguishable(
        self, client: AsyncClient, email: str, password: str
    ) -> None:
        await register_and_login(client, email="login@example.com")

        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password."
        assert response.headers["www-authenticate"] == "Bearer"

    async def test_oauth2_form_endpoint_works_for_swagger(self, client: AsyncClient) -> None:
        await register_and_login(client, email="form@example.com")

        response = await client.post(
            "/api/v1/auth/token",
            data={"username": "form@example.com", "password": DEMO_PASSWORD},
        )
        assert response.status_code == 200
        assert response.json()["access_token"]


class TestMe:
    async def test_describes_the_caller(self, client: AsyncClient, alice) -> None:
        response = await client.get("/api/v1/auth/me", headers=auth(alice))

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "alice@taskflow.dev"
        assert body["full_name"] == "Alice Owner"
        assert body["initials"] == "AO"
        assert body["created_at"]

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Authorization": "Bearer not-a-real-token"},
            {"Authorization": "Basic dXNlcjpwYXNz"},
            {"Authorization": "Bearer "},
        ],
    )
    async def test_rejects_missing_or_malformed_credentials(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["code"] == "authentication_failed"


class TestRefresh:
    async def test_rotates_the_pair(self, client: AsyncClient, alice) -> None:
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": alice["X-Test-Refresh"]}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"]

        # The new access token actually works.
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200

    async def test_an_access_token_cannot_be_used_to_refresh(
        self, client: AsyncClient, alice
    ) -> None:
        access_token = alice["Authorization"].removeprefix("Bearer ")
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": access_token}
        )
        assert response.status_code == 401

    async def test_garbage_refresh_token_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nonsense"})
        assert response.status_code == 401


class TestErrorEnvelope:
    async def test_every_error_uses_the_same_shape(self, client: AsyncClient) -> None:
        """One documented error contract for the whole API.

        The frontend has a single error parser; if some endpoints answered
        with a different shape it would need per-endpoint special cases.
        """
        responses = [
            await client.get("/api/v1/auth/me"),
            await client.post("/api/v1/auth/register", json={}),
            await client.post(
                "/api/v1/auth/login",
                json={"email": "ghost@example.com", "password": DEMO_PASSWORD},
            ),
            await client.get("/api/v1/does-not-exist"),
        ]

        for response in responses:
            body = response.json()
            assert {"title", "status", "detail", "code"} <= set(body), body
            assert body["status"] == response.status_code
            assert isinstance(body["detail"], str)

    async def test_responses_carry_a_correlation_id(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/auth/me")
        assert response.headers["X-Request-ID"]
        assert response.json()["request_id"] == response.headers["X-Request-ID"]

    async def test_an_inbound_request_id_is_preserved(self, client: AsyncClient) -> None:
        # Lets a trace span the frontend, a proxy and this service.
        response = await client.get("/health/live", headers={"X-Request-ID": "trace-me-12345"})
        assert response.headers["X-Request-ID"] == "trace-me-12345"

    async def test_security_headers_are_present(self, client: AsyncClient) -> None:
        response = await client.get("/health/live")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
