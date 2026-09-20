"""The real bcrypt and PyJWT adapters.

The use-case tests run against fakes for speed, so these are what actually
prove the production adapters behave. Without them, a bug in the real hasher
or token service would pass a fully green suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from taskflow.application.ports.token_service import TokenType
from taskflow.domain.errors import AuthenticationError
from taskflow.infrastructure.security import BcryptPasswordHasher, JwtTokenService
from taskflow.infrastructure.services import FixedClock, SystemClock

pytestmark = pytest.mark.unit

# 4 rounds: the bcrypt minimum. Enough to exercise the real algorithm without
# paying 250 ms per call.
ROUNDS = 4
SECRET = "a-test-secret-key-long-enough-for-hs256-signing"


@pytest.fixture
def hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher(rounds=ROUNDS)


class TestBcryptPasswordHasher:
    def test_hash_then_verify_round_trip(self, hasher) -> None:
        hashed = hasher.hash("correct horse battery staple")
        assert hasher.verify("correct horse battery staple", hashed)

    def test_hash_is_not_the_plaintext(self, hasher) -> None:
        hashed = hasher.hash("my-password")
        assert "my-password" not in hashed
        assert hashed.startswith("$2b$")

    def test_the_same_password_hashes_differently_each_time(self, hasher) -> None:
        # Per-hash salt: two users with the same password must not share a
        # hash, otherwise the database leaks who reused passwords.
        assert hasher.hash("same-password") != hasher.hash("same-password")

    def test_wrong_password_fails(self, hasher) -> None:
        hashed = hasher.hash("right-password")
        assert not hasher.verify("wrong-password", hashed)

    @pytest.mark.parametrize("stored", ["", "not-a-hash", "$2b$corrupt", "null"])
    def test_malformed_stored_hash_reads_as_wrong_password(self, hasher, stored) -> None:
        # Must not raise: a corrupt row should fail the login, not 500 the
        # whole endpoint.
        assert hasher.verify("anything", stored) is False

    def test_unicode_passwords_round_trip(self, hasher) -> None:
        password = "contraseña-con-ñ-y-emoji-🔐"
        assert hasher.verify(password, hasher.hash(password))

    def test_input_is_truncated_at_the_bcrypt_limit(self, hasher) -> None:
        """Documents a real bcrypt limitation rather than pretending it away.

        bcrypt ignores bytes past 72. Two passwords sharing the first 72
        bytes therefore authenticate each other -- which is why the
        application layer separately caps password length at 128 characters.
        """
        base = "x" * 72
        hashed = hasher.hash(base + "-ignored-tail")
        assert hasher.verify(base + "-completely-different-tail", hashed)

    def test_needs_rehash_detects_a_weaker_cost(self) -> None:
        weak = BcryptPasswordHasher(rounds=4).hash("password-to-upgrade")
        assert BcryptPasswordHasher(rounds=10).needs_rehash(weak) is True
        assert BcryptPasswordHasher(rounds=4).needs_rehash(weak) is False

    def test_needs_rehash_on_garbage_asks_for_a_rehash(self, hasher) -> None:
        assert hasher.needs_rehash("garbage") is True


class TestJwtTokenService:
    @pytest.fixture
    def clock(self) -> FixedClock:
        return FixedClock(datetime(2026, 6, 15, 12, 0, tzinfo=UTC))

    @pytest.fixture
    def service(self, clock) -> JwtTokenService:
        return JwtTokenService(
            secret_key=SECRET,
            algorithm="HS256",
            issuer="taskflow",
            access_ttl=timedelta(minutes=15),
            refresh_ttl=timedelta(days=7),
            clock=clock,
        )

    def test_issue_then_decode_round_trip(self, service) -> None:
        subject = uuid4()
        issued = service.issue(subject=subject, token_type=TokenType.ACCESS)
        payload = service.decode(issued.value, expected_type=TokenType.ACCESS)

        assert payload.subject == subject
        assert payload.token_type is TokenType.ACCESS
        assert payload.jti == issued.jti

    def test_expires_in_matches_the_configured_ttl(self, service) -> None:
        issued = service.issue(subject=uuid4(), token_type=TokenType.ACCESS)
        assert issued.expires_in_seconds == 15 * 60

    def test_refresh_tokens_live_longer(self, service) -> None:
        access = service.issue(subject=uuid4(), token_type=TokenType.ACCESS)
        refresh = service.issue(subject=uuid4(), token_type=TokenType.REFRESH)
        assert refresh.expires_at > access.expires_at

    def test_each_token_gets_a_unique_jti(self, service) -> None:
        subject = uuid4()
        first = service.issue(subject=subject, token_type=TokenType.ACCESS)
        second = service.issue(subject=subject, token_type=TokenType.ACCESS)
        assert first.jti != second.jti

    def test_a_refresh_token_is_not_a_valid_access_token(self, service) -> None:
        """The ``typ`` claim, which is the point of having it.

        Without this check the 7-day refresh token would be accepted on every
        authenticated endpoint, silently cancelling the 15-minute access
        token lifetime.
        """
        refresh = service.issue(subject=uuid4(), token_type=TokenType.REFRESH)
        with pytest.raises(AuthenticationError):
            service.decode(refresh.value, expected_type=TokenType.ACCESS)

    def test_expired_token_is_rejected(self, service, clock) -> None:
        issued = service.issue(subject=uuid4(), token_type=TokenType.ACCESS)
        # Expiry is judged by the injected clock, so this is deterministic
        # rather than dependent on how long the test took to run.
        clock.advance(minutes=16)
        with pytest.raises(AuthenticationError, match="Invalid or expired"):
            service.decode(issued.value, expected_type=TokenType.ACCESS)

    def test_token_signed_with_another_key_is_rejected(self, clock) -> None:
        attacker = JwtTokenService(
            secret_key="a-completely-different-secret-key-of-good-length",
            algorithm="HS256",
            issuer="taskflow",
            access_ttl=timedelta(minutes=15),
            refresh_ttl=timedelta(days=7),
            clock=clock,
        )
        forged = attacker.issue(subject=uuid4(), token_type=TokenType.ACCESS)

        legitimate = JwtTokenService(
            secret_key=SECRET,
            algorithm="HS256",
            issuer="taskflow",
            access_ttl=timedelta(minutes=15),
            refresh_ttl=timedelta(days=7),
            clock=clock,
        )
        with pytest.raises(AuthenticationError):
            legitimate.decode(forged.value, expected_type=TokenType.ACCESS)

    def test_unsigned_alg_none_token_is_rejected(self, service) -> None:
        """The canonical JWT attack.

        A token with ``"alg": "none"`` and no signature must be refused. It
        is, because ``decode`` passes an explicit algorithm allow-list rather
        than trusting the header.
        """
        forged = jwt.encode(
            {
                "sub": str(uuid4()),
                "jti": str(uuid4()),
                "typ": "access",
                "iat": 1_800_000_000,
                "exp": 4_000_000_000,
                "iss": "taskflow",
            },
            key="",
            algorithm="none",
        )
        with pytest.raises(AuthenticationError):
            service.decode(forged, expected_type=TokenType.ACCESS)

    def test_token_from_another_issuer_is_rejected(self, service, clock) -> None:
        other = JwtTokenService(
            secret_key=SECRET,
            algorithm="HS256",
            issuer="some-other-service",
            access_ttl=timedelta(minutes=15),
            refresh_ttl=timedelta(days=7),
            clock=clock,
        )
        foreign = other.issue(subject=uuid4(), token_type=TokenType.ACCESS)
        with pytest.raises(AuthenticationError):
            service.decode(foreign.value, expected_type=TokenType.ACCESS)

    def test_token_missing_required_claims_is_rejected(self, service) -> None:
        incomplete = jwt.encode(
            {"sub": str(uuid4()), "typ": "access"}, SECRET, algorithm="HS256"
        )
        with pytest.raises(AuthenticationError):
            service.decode(incomplete, expected_type=TokenType.ACCESS)

    def test_non_uuid_subject_is_rejected(self, service) -> None:
        malformed = jwt.encode(
            {
                "sub": "not-a-uuid",
                "jti": str(uuid4()),
                "typ": "access",
                "iat": 1_800_000_000,
                "exp": 4_000_000_000,
                "iss": "taskflow",
            },
            SECRET,
            algorithm="HS256",
        )
        with pytest.raises(AuthenticationError):
            service.decode(malformed, expected_type=TokenType.ACCESS)

    def test_expiry_is_judged_by_the_injected_clock(self, clock) -> None:
        """Regression test.

        ``issue`` used the injected clock while ``decode`` delegated expiry to
        PyJWT, which reads the real system time. A service whose clock was set
        to any past date therefore rejected tokens it had just minted. Both
        paths now read the same clock.
        """
        past = FixedClock(datetime(2020, 1, 1, tzinfo=UTC))
        service = JwtTokenService(
            secret_key=SECRET,
            algorithm="HS256",
            issuer="taskflow",
            access_ttl=timedelta(minutes=15),
            refresh_ttl=timedelta(days=7),
            clock=past,
        )
        issued = service.issue(subject=uuid4(), token_type=TokenType.ACCESS)
        payload = service.decode(issued.value, expected_type=TokenType.ACCESS)
        assert payload.jti == issued.jti

    def test_leeway_tolerates_small_clock_drift(self, service, clock) -> None:
        issued = service.issue(subject=uuid4(), token_type=TokenType.ACCESS)
        clock.advance(minutes=15, seconds=5)
        # Just past expiry but inside the 10-second allowance.
        assert service.decode(issued.value, expected_type=TokenType.ACCESS)

    @pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer token"])
    def test_garbage_input_is_rejected(self, service, garbage) -> None:
        with pytest.raises(AuthenticationError):
            service.decode(garbage, expected_type=TokenType.ACCESS)

    def test_error_messages_do_not_distinguish_failure_modes(self, service, clock) -> None:
        expired = service.issue(subject=uuid4(), token_type=TokenType.ACCESS)
        clock.advance(minutes=20)

        messages = set()
        for token in (expired.value, "total-garbage"):
            with pytest.raises(AuthenticationError) as exc_info:
                service.decode(token, expected_type=TokenType.ACCESS)
            messages.add(exc_info.value.message)

        # One message for every cause: an attacker learns nothing about
        # which part of the token to change.
        assert messages == {"Invalid or expired token."}


class TestClocks:
    def test_system_clock_is_timezone_aware_utc(self) -> None:
        moment = SystemClock().now()
        assert moment.tzinfo is not None
        assert moment.utcoffset() == timedelta(0)

    def test_fixed_clock_does_not_move_on_its_own(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
        assert clock.now() == clock.now()

    def test_fixed_clock_can_be_advanced_and_set(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
        clock.advance(hours=3)
        assert clock.now() == datetime(2026, 1, 1, 3, tzinfo=UTC)
        clock.set(datetime(2027, 5, 5, tzinfo=UTC))
        assert clock.now() == datetime(2027, 5, 5, tzinfo=UTC)

    def test_fixed_clock_refuses_a_naive_datetime(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            FixedClock(datetime(2026, 1, 1))
