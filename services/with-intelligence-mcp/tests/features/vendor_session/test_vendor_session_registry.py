"""One live vendor session per user, cached in front of the store and renewed under a lock."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from with_intelligence_mcp.features.vendor_session import VendorSessionRegistry
from with_intelligence_mcp.with_intelligence_client import VendorSession


def _session(token: str, *, age: timedelta = timedelta(0)) -> VendorSession:
    return VendorSession.model_validate(
        {
            "access_token": token,
            "refresh_token": f"refresh-{token}",
            "issued_at": datetime.now(UTC) - age,
        }
    )


class FakeFactory:
    """Counts refreshes, and can be made to fail or stall."""

    def __init__(self, *, refresh_fails: bool = False, delay: float = 0.0) -> None:
        self.refreshes: int = 0
        self._refresh_fails: bool = refresh_fails
        self._delay: float = delay

    async def refresh(self, _session_in: VendorSession) -> VendorSession:
        self.refreshes += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._refresh_fails:
            raise RuntimeError("refresh token spent")
        return _session(f"refreshed-{self.refreshes}")


class FakeStore:
    """Stands in for the encrypted row and the auth context that reads and renews it.

    `renew` mirrors `WithIntelligenceAuthContext.renew_session`: it serialises callers, returns
    the stored session if someone else already renewed it, and writes the renewal back.
    """

    def __init__(self, stored: VendorSession, *, delay: float = 0.0) -> None:
        self.stored: VendorSession = stored
        self.reads: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()
        self._delay: float = delay

    async def read(self) -> VendorSession:
        self.reads += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return self.stored

    async def renew(
        self, renew: Callable[[VendorSession], Awaitable[VendorSession]]
    ) -> VendorSession:
        async with self._lock:
            if self.stored.is_fresh:
                return self.stored
            self.stored = await renew(self.stored)
            return self.stored


def _registry(factory: FakeFactory) -> VendorSessionRegistry:
    return VendorSessionRegistry(factory)  # pyright: ignore[reportArgumentType]


class TestFirstUse:
    async def test_reads_the_stored_session_on_first_use(self) -> None:
        """The login already signed in, so the first call needs no vendor round trip."""
        factory = FakeFactory()
        store = FakeStore(_session("stored"))
        assert await _registry(factory).access_token("s1", store.read, store.renew) == "stored"
        assert factory.refreshes == 0

    async def test_reuses_a_fresh_token_without_reading_again(self) -> None:
        factory = FakeFactory()
        store = FakeStore(_session("stored"))
        registry = _registry(factory)
        first = await registry.access_token("s1", store.read, store.renew)
        assert await registry.access_token("s1", store.read, store.renew) == first
        assert store.reads == 1


class TestPerSubject:
    async def test_two_users_get_their_own_session(self) -> None:
        """A shared session would hand one user's data to another."""
        factory = FakeFactory()
        registry = _registry(factory)
        alice = FakeStore(_session("alice-token"))
        bob = FakeStore(_session("bob-token"))
        assert await registry.access_token("alice", alice.read, alice.renew) == "alice-token"
        assert await registry.access_token("bob", bob.read, bob.renew) == "bob-token"

    async def test_forgetting_one_user_leaves_the_other(self) -> None:
        factory = FakeFactory()
        registry = _registry(factory)
        alice = FakeStore(_session("alice-token"))
        bob = FakeStore(_session("bob-token"))
        _ = await registry.access_token("alice", alice.read, alice.renew)
        _ = await registry.access_token("bob", bob.read, bob.renew)
        registry.forget("bob")
        assert await registry.access_token("alice", alice.read, alice.renew) == "alice-token"
        assert alice.reads == 1


class TestRenewal:
    async def test_an_expired_session_is_refreshed(self) -> None:
        factory = FakeFactory()
        store = FakeStore(_session("old", age=timedelta(hours=2)))
        registry = _registry(factory)
        assert await registry.access_token("s1", store.read, store.renew) == "refreshed-1"
        assert factory.refreshes == 1

    async def test_the_renewal_is_written_back_to_the_store(self) -> None:
        """So the next process to read it gets the renewed session, not the spent one."""
        factory = FakeFactory()
        store = FakeStore(_session("old", age=timedelta(hours=2)))
        _ = await _registry(factory).access_token("s1", store.read, store.renew)
        assert store.stored.access_token.get_secret_value() == "refreshed-1"

    async def test_a_session_a_replica_already_renewed_is_not_refreshed_again(self) -> None:
        """The holder is stale but the row is fresh, so reading it is enough."""
        factory = FakeFactory()
        store = FakeStore(_session("renewed-elsewhere"))
        registry = _registry(factory)
        holder = await registry._holder_for("s1")  # pyright: ignore[reportPrivateUsage]
        holder.session = _session("old", age=timedelta(hours=2))
        token = await registry.access_token("s1", store.read, store.renew)
        assert token == "renewed-elsewhere"
        assert factory.refreshes == 0

    async def test_a_spent_refresh_token_surfaces(self) -> None:
        """There is no password to fall back on, so the caller has to log in again."""
        factory = FakeFactory(refresh_fails=True)
        store = FakeStore(_session("old", age=timedelta(hours=2)))
        registry = _registry(factory)
        with pytest.raises(RuntimeError):
            _ = await registry.access_token("s1", store.read, store.renew)
        assert factory.refreshes == 1

    async def test_renewed_access_token_forces_a_renewal(self) -> None:
        factory = FakeFactory()
        store = FakeStore(_session("stored"))
        registry = _registry(factory)
        _ = await registry.access_token("s1", store.read, store.renew)
        # A 401 on a token this process still believes is fresh: renew regardless.
        store.stored = _session("stored", age=timedelta(hours=2))
        assert await registry.renewed_access_token("s1", store.read, store.renew) == "refreshed-1"


class TestConcurrentRenewal:
    async def test_simultaneous_first_use_reads_once(self) -> None:
        factory = FakeFactory()
        store = FakeStore(_session("stored"), delay=0.02)
        registry = _registry(factory)
        tokens = await asyncio.gather(
            *(registry.access_token("s1", store.read, store.renew) for _ in range(5))
        )
        assert store.reads == 1
        assert set(tokens) == {"stored"}

    async def test_simultaneous_expiry_refreshes_once(self) -> None:
        """Otherwise every in-flight tool call spends its own refresh token."""
        factory = FakeFactory(delay=0.02)
        store = FakeStore(_session("old", age=timedelta(hours=2)))
        registry = _registry(factory)
        tokens = await asyncio.gather(
            *(registry.access_token("s1", store.read, store.renew) for _ in range(5))
        )
        assert factory.refreshes == 1
        assert set(tokens) == {"refreshed-1"}

    async def test_two_users_expiring_at_once_do_not_block_each_other(self) -> None:
        factory = FakeFactory()
        registry = _registry(factory)
        alice = FakeStore(_session("old-alice", age=timedelta(hours=2)))
        bob = FakeStore(_session("old-bob", age=timedelta(hours=2)))
        _ = await asyncio.gather(
            registry.access_token("alice", alice.read, alice.renew),
            registry.access_token("bob", bob.read, bob.renew),
        )
        assert factory.refreshes == 2
