"""Holding one vendor session: renewal under contention, and the fall back to signing in."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from with_intelligence_mcp.features.vendor_session import ServiceAccountSession
from with_intelligence_mcp.with_intelligence_client import VendorCredential, VendorSession

CREDENTIAL = VendorCredential.model_validate({"username": "u", "password": "p"})


def _session(token: str, *, age: timedelta = timedelta(0)) -> VendorSession:
    return VendorSession.model_validate(
        {
            "access_token": token,
            "refresh_token": f"refresh-{token}",
            "issued_at": datetime.now(UTC) - age,
        }
    )


class FakeFactory:
    """Counts the two auth calls and can be made to fail the refresh."""

    def __init__(self, *, refresh_fails: bool = False, delay: float = 0.0) -> None:
        self.sign_ins: int = 0
        self.refreshes: int = 0
        self._refresh_fails: bool = refresh_fails
        self._delay: float = delay

    async def sign_in(self, _credential: VendorCredential) -> VendorSession:
        self.sign_ins += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return _session(f"signed-in-{self.sign_ins}")

    async def refresh(self, _session_in: VendorSession) -> VendorSession:
        self.refreshes += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._refresh_fails:
            raise RuntimeError("refresh token spent")
        return _session(f"refreshed-{self.refreshes}")


def build(factory: FakeFactory) -> ServiceAccountSession:
    # The holder needs only the two auth calls off the factory.
    return ServiceAccountSession(factory, CREDENTIAL)  # pyright: ignore[reportArgumentType]


class TestFirstUse:
    async def test_signs_in_on_the_first_token_request(self) -> None:
        factory = FakeFactory()
        assert await build(factory).access_token() == "signed-in-1"
        assert (factory.sign_ins, factory.refreshes) == (1, 0)

    async def test_reuses_a_fresh_token(self) -> None:
        factory = FakeFactory()
        holder = build(factory)
        first = await holder.access_token()
        assert await holder.access_token() == first
        assert factory.sign_ins == 1


class TestRenewal:
    async def test_an_expired_token_is_refreshed_not_re_signed(self) -> None:
        factory = FakeFactory()
        holder = build(factory)
        holder._session = _session("old", age=timedelta(hours=2))  # pyright: ignore[reportPrivateUsage]
        assert await holder.access_token() == "refreshed-1"
        assert (factory.sign_ins, factory.refreshes) == (0, 1)

    async def test_a_spent_refresh_token_falls_back_to_signing_in(self) -> None:
        factory = FakeFactory(refresh_fails=True)
        holder = build(factory)
        holder._session = _session("old", age=timedelta(hours=2))  # pyright: ignore[reportPrivateUsage]
        assert await holder.access_token() == "signed-in-1"
        assert (factory.sign_ins, factory.refreshes) == (1, 1)

    async def test_renewed_access_token_forces_a_renewal(self) -> None:
        factory = FakeFactory()
        holder = build(factory)
        _ = await holder.access_token()
        assert await holder.renewed_access_token() == "refreshed-1"


class TestConcurrentRenewal:
    async def test_simultaneous_first_use_signs_in_once(self) -> None:
        """Without the lock every caller spends its own sign-in."""
        factory = FakeFactory(delay=0.02)
        holder = build(factory)
        tokens = await asyncio.gather(*(holder.access_token() for _ in range(5)))
        assert factory.sign_ins == 1
        assert set(tokens) == {"signed-in-1"}

    async def test_simultaneous_expiry_refreshes_once(self) -> None:
        """The case that would otherwise spend one refresh token per in-flight tool call."""
        factory = FakeFactory(delay=0.02)
        holder = build(factory)
        holder._session = _session("old", age=timedelta(hours=2))  # pyright: ignore[reportPrivateUsage]
        tokens = await asyncio.gather(*(holder.access_token() for _ in range(5)))
        assert factory.refreshes == 1
        assert set(tokens) == {"refreshed-1"}

    async def test_a_renewal_after_someone_elses_still_renews(self) -> None:
        """A 401 on a token another caller already replaced must not loop forever."""
        factory = FakeFactory()
        holder = build(factory)
        stale = await holder.access_token()
        again = await holder.renewed_access_token()
        assert again != stale
        assert factory.refreshes == 1


class TestSubject:
    async def test_every_caller_shares_the_one_subject(self) -> None:
        """Which is exactly what the per-user login replaces."""
        assert build(FakeFactory()).subject() == "service-account"


class TestUnconfigured:
    async def test_a_missing_credential_says_which_variables_to_set(self) -> None:
        """FastMCP renders this as the tool's error, so it has to be the actionable sentence."""
        from with_intelligence_mcp.with_intelligence_client import SignInFailed

        holder = ServiceAccountSession(FakeFactory(), None)  # pyright: ignore[reportArgumentType]
        with pytest.raises(SignInFailed, match="WITH_INTELLIGENCE_USERNAME"):
            _ = await holder.access_token()
