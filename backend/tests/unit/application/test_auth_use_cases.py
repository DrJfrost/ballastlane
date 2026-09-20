"""Authentication use cases."""

from __future__ import annotations

import pytest

from taskflow.application.dto import (
    LoginCommand,
    RefreshTokenCommand,
    RegisterUserCommand,
)
from taskflow.application.ports.token_service import TokenType
from taskflow.application.use_cases.auth import (
    AuthenticateUser,
    RefreshAccessToken,
    RegisterUser,
    ResolveCurrentUser,
)
from taskflow.domain.errors import (
    AlreadyExistsError,
    AuthenticationError,
    ValidationError,
)
from taskflow.domain.value_objects import Email
from tests.conftest import NOW, make_user
from tests.fakes import StubTokenService

pytestmark = pytest.mark.unit

GOOD_PASSWORD = "a-long-enough-passphrase"


@pytest.fixture
def tokens() -> StubTokenService:
    return StubTokenService()


@pytest.fixture
def register(uow, hasher, clock) -> RegisterUser:
    return RegisterUser(uow=uow, hasher=hasher, clock=clock)


@pytest.fixture
def login(uow, hasher, tokens, clock) -> AuthenticateUser:
    return AuthenticateUser(uow=uow, hasher=hasher, tokens=tokens, clock=clock)


class TestRegisterUser:
    async def test_creates_a_user_and_never_returns_the_hash(self, register, uow) -> None:
        view = await register.execute(
            RegisterUserCommand(
                email="  New.User@Example.COM ",
                full_name="  New   User ",
                password=GOOD_PASSWORD,
            )
        )

        assert view.email == "new.user@example.com"
        assert view.full_name == "New User"
        assert view.initials == "NU"
        assert view.is_active
        # The read model has no field for it, so it cannot leak.
        assert not hasattr(view, "hashed_password")
        assert uow.committed == 1

    async def test_stores_a_hash_not_the_plaintext(self, register, uow) -> None:
        await register.execute(
            RegisterUserCommand(
                email="new@example.com", full_name="New User", password=GOOD_PASSWORD
            )
        )
        stored = await uow.users.get_by_email(Email("new@example.com"))
        assert stored is not None
        assert stored.hashed_password != GOOD_PASSWORD
        assert GOOD_PASSWORD in stored.hashed_password or stored.hashed_password.startswith(
            "fake$"
        )

    async def test_duplicate_email_is_rejected_case_insensitively(self, register, uow) -> None:
        await register.execute(
            RegisterUserCommand(
                email="taken@example.com", full_name="First User", password=GOOD_PASSWORD
            )
        )
        with pytest.raises(AlreadyExistsError, match="already exists"):
            await register.execute(
                RegisterUserCommand(
                    email="TAKEN@EXAMPLE.COM",
                    full_name="Second User",
                    password=GOOD_PASSWORD,
                )
            )
        assert uow.committed == 1

    @pytest.mark.parametrize(
        ("password", "message"),
        [
            ("short", "at least 10"),
            ("x" * 129, "at most 128"),
            ("  padded-password  ", "whitespace"),
            ("password123", "too common"),
        ],
    )
    async def test_password_policy(self, register, password, message) -> None:
        with pytest.raises(ValidationError, match=message):
            await register.execute(
                RegisterUserCommand(
                    email="new@example.com", full_name="New User", password=password
                )
            )

    async def test_invalid_email_is_rejected_before_any_write(self, register, uow) -> None:
        with pytest.raises(ValidationError):
            await register.execute(
                RegisterUserCommand(
                    email="not-an-email", full_name="New User", password=GOOD_PASSWORD
                )
            )
        assert uow.committed == 0


class TestAuthenticateUser:
    @pytest.fixture(autouse=True)
    async def _account(self, uow, hasher):
        self.user = make_user(
            email="user@example.com",
            hashed_password=hasher.hash(GOOD_PASSWORD),
        )
        await uow.users.add(self.user)

    async def test_returns_a_token_pair(self, login, tokens) -> None:
        view = await login.execute(
            LoginCommand(email="user@example.com", password=GOOD_PASSWORD)
        )

        assert view.token_type == "bearer"
        assert view.expires_in == 900
        assert view.access_token != view.refresh_token
        # Both an access and a refresh token, in that order.
        assert [kind for _, kind in tokens.issued] == ["access", "refresh"]

    async def test_email_is_matched_case_insensitively(self, login) -> None:
        view = await login.execute(
            LoginCommand(email="USER@EXAMPLE.COM", password=GOOD_PASSWORD)
        )
        assert view.access_token

    @pytest.mark.parametrize(
        ("email", "password"),
        [
            ("user@example.com", "wrong-password"),
            ("nobody@example.com", GOOD_PASSWORD),
            ("not-an-email", GOOD_PASSWORD),
        ],
    )
    async def test_every_failure_gives_the_same_message(self, login, email, password) -> None:
        # Wrong password, unknown account and malformed input must be
        # indistinguishable, otherwise login becomes an account-enumeration
        # oracle.
        with pytest.raises(AuthenticationError) as exc_info:
            await login.execute(LoginCommand(email=email, password=password))
        assert exc_info.value.message == "Incorrect email or password."

    async def test_unknown_account_still_performs_a_verification(
        self, login, hasher, monkeypatch
    ) -> None:
        """Timing equalisation: a missing user must not short-circuit."""
        calls: list[str] = []
        original = hasher.verify

        def counting_verify(plain: str, hashed: str) -> bool:
            calls.append(hashed)
            return bool(original(plain, hashed))

        monkeypatch.setattr(hasher, "verify", counting_verify)

        with pytest.raises(AuthenticationError):
            await login.execute(
                LoginCommand(email="nobody@example.com", password=GOOD_PASSWORD)
            )
        assert len(calls) == 1

    async def test_deactivated_account_is_told_so(self, login, uow) -> None:
        self.user.deactivate(now=NOW)
        await uow.users.update(self.user)

        with pytest.raises(AuthenticationError) as exc_info:
            await login.execute(LoginCommand(email="user@example.com", password=GOOD_PASSWORD))
        # Distinguishing this one *is* safe: the credentials were correct, so
        # the caller already knows the account exists.
        assert exc_info.value.details["reason"] == "inactive"

    async def test_stale_hash_is_upgraded_on_successful_login(
        self, uow, hasher, tokens, clock
    ) -> None:
        stale = make_user(email="legacy@example.com", hashed_password=f"old${GOOD_PASSWORD}")
        await uow.users.add(stale)
        use_case = AuthenticateUser(uow=uow, hasher=hasher, tokens=tokens, clock=clock)

        await use_case.execute(LoginCommand(email="legacy@example.com", password=GOOD_PASSWORD))

        upgraded = await uow.users.get(stale.id)
        assert upgraded is not None
        assert upgraded.hashed_password.startswith("fake$")
        assert uow.committed == 1


class TestRefreshAccessToken:
    async def test_rotates_both_tokens(self, uow, tokens) -> None:
        user = make_user()
        await uow.users.add(user)
        use_case = RefreshAccessToken(uow=uow, tokens=tokens)

        view = await use_case.execute(RefreshTokenCommand(refresh_token=f"refresh:{user.id}"))

        assert view.access_token == f"access:{user.id}"
        # A new refresh token too: rotation shortens the window in which a
        # leaked one is useful.
        assert view.refresh_token == f"refresh:{user.id}"
        assert [kind for _, kind in tokens.issued] == ["access", "refresh"]

    async def test_an_access_token_is_not_accepted_as_a_refresh_token(
        self, uow, tokens
    ) -> None:
        user = make_user()
        await uow.users.add(user)
        use_case = RefreshAccessToken(uow=uow, tokens=tokens)

        with pytest.raises(AuthenticationError):
            await use_case.execute(RefreshTokenCommand(refresh_token=f"access:{user.id}"))

    async def test_deleted_account_cannot_refresh(self, uow, tokens) -> None:
        use_case = RefreshAccessToken(uow=uow, tokens=tokens)
        with pytest.raises(AuthenticationError, match="no longer exists"):
            await use_case.execute(
                RefreshTokenCommand(
                    refresh_token="refresh:aaaaaaaa-0000-4000-8000-00000000dead"
                )
            )

    async def test_deactivated_account_cannot_refresh(self, uow, tokens) -> None:
        """Revocation must actually revoke.

        Tokens are stateless, so if the user were trusted from the claims a
        deactivated account would keep minting access tokens for days.
        """
        user = make_user()
        user.deactivate(now=NOW)
        await uow.users.add(user)
        use_case = RefreshAccessToken(uow=uow, tokens=tokens)

        with pytest.raises(AuthenticationError, match="deactivated"):
            await use_case.execute(RefreshTokenCommand(refresh_token=f"refresh:{user.id}"))


class TestResolveCurrentUser:
    async def test_resolves_an_active_user(self, uow, tokens) -> None:
        user = make_user(email="me@example.com")
        await uow.users.add(user)
        use_case = ResolveCurrentUser(uow=uow, tokens=tokens)

        view = await use_case.execute(f"{TokenType.ACCESS}:{user.id}")

        assert view.id == user.id
        assert view.email == "me@example.com"
        assert not hasattr(view, "hashed_password")

    async def test_refresh_token_is_rejected_on_the_access_path(self, uow, tokens) -> None:
        user = make_user()
        await uow.users.add(user)
        use_case = ResolveCurrentUser(uow=uow, tokens=tokens)

        with pytest.raises(AuthenticationError):
            await use_case.execute(f"refresh:{user.id}")

    async def test_garbage_token_is_rejected(self, uow, tokens) -> None:
        use_case = ResolveCurrentUser(uow=uow, tokens=tokens)
        with pytest.raises(AuthenticationError):
            await use_case.execute("not-even-close")
