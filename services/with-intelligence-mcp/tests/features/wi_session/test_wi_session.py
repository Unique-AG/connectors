"""One live With Intelligence session per user, cached in this process and renewed under a lock."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from with_intelligence_mcp.features.wi_session import WiSessionCache
from with_intelligence_mcp.with_intelligence_client import WiSession


def _session(token: str, *, age: timedelta = timedelta(0)) -> WiSession:
    return WiSession.model_validate(
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

    async def refresh(self, _session_in: WiSession) -> WiSession:
        self.refreshes += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._refresh_fails:
            raise RuntimeError("refresh token spent")
        return _session(f"refreshed-{self.refreshes}")


class FakeStore:
    def __init__(self, stored: WiSession, *, delay: float = 0.0) -> None:
        self.stored: WiSession = stored
        self.reads: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()
        self._delay: float = delay

    async def read(self) -> WiSession:
        self.reads += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return self.stored.model_copy()

    async def renew(
        self,
        renew: Callable[[WiSession], Awaitable[WiSession]],
        stale: WiSession | None = None,
    ) -> WiSession:
        async with self._lock:
            if self.stored.is_fresh and self.stored.has_different_access_token(stale):
                return self.stored
            self.stored = await renew(self.stored)
            return self.stored


def _cache(factory: FakeFactory) -> WiSessionCache:
    return WiSessionCache(factory)  # pyright: ignore[reportArgumentType]


class TestFirstUse:
    async def test_reads_the_stored_session_on_first_use(self) -> None:
        """The login already signed in, so the first call needs no WI round trip."""
        factory = FakeFactory()
        store = FakeStore(_session("stored"))
        assert await _cache(factory).access_token("s1", store.read, store.renew) == "stored"
        assert factory.refreshes == 0

    async def test_observes_a_reconnect_handled_by_another_replica(self) -> None:
        factory = FakeFactory()
        store = FakeStore(_session("stored"))
        wi = _cache(factory)
        assert await wi.access_token("s1", store.read, store.renew) == "stored"
        store.stored = _session("reconnected")
        assert await wi.access_token("s1", store.read, store.renew) == "reconnected"
        assert store.reads == 2


class TestPerSubject:
    async def test_two_users_get_their_own_session(self) -> None:
        """A shared session would hand one user's data to another."""
        factory = FakeFactory()
        wi = _cache(factory)
        alice = FakeStore(_session("alice-token"))
        bob = FakeStore(_session("bob-token"))
        assert await wi.access_token("alice", alice.read, alice.renew) == "alice-token"
        assert await wi.access_token("bob", bob.read, bob.renew) == "bob-token"


class TestRenewal:
    async def test_an_expired_session_is_refreshed(self) -> None:
        factory = FakeFactory()
        store = FakeStore(_session("old", age=timedelta(hours=2)))
        wi = _cache(factory)
        assert await wi.access_token("s1", store.read, store.renew) == "refreshed-1"
        assert factory.refreshes == 1

    async def test_the_renewal_is_written_back_to_the_store(self) -> None:
        """So the next process to read it gets the renewed session, not the spent one."""
        factory = FakeFactory()
        store = FakeStore(_session("old", age=timedelta(hours=2)))
        _ = await _cache(factory).access_token("s1", store.read, store.renew)
        assert store.stored.access_token.get_secret_value() == "refreshed-1"

    async def test_a_session_a_replica_already_renewed_is_not_refreshed_again(self) -> None:
        """The holder is stale but the row is fresh, so reading it is enough."""
        factory = FakeFactory()
        store = FakeStore(_session("renewed-elsewhere"))
        wi = _cache(factory)
        holder = await wi._holder_for("s1")  # pyright: ignore[reportPrivateUsage]
        holder.session = _session("old", age=timedelta(hours=2))
        token = await wi.access_token("s1", store.read, store.renew)
        assert token == "renewed-elsewhere"
        assert factory.refreshes == 0

    async def test_a_spent_refresh_token_surfaces(self) -> None:
        """There is no password to fall back on, so the caller has to log in again."""
        factory = FakeFactory(refresh_fails=True)
        store = FakeStore(_session("old", age=timedelta(hours=2)))
        wi = _cache(factory)
        with pytest.raises(RuntimeError):
            _ = await wi.access_token("s1", store.read, store.renew)
        assert factory.refreshes == 1

    async def test_renewed_access_token_forces_a_renewal(self) -> None:
        factory = FakeFactory()
        store = FakeStore(_session("stored"))
        wi = _cache(factory)
        _ = await wi.access_token("s1", store.read, store.renew)
        assert await wi.renewed_access_token("s1", store.read, store.renew) == "refreshed-1"


class TestConcurrentRenewal:
    async def test_simultaneous_first_use_reads_once(self) -> None:
        factory = FakeFactory()
        store = FakeStore(_session("stored"), delay=0.02)
        wi = _cache(factory)
        tokens = await asyncio.gather(
            *(wi.access_token("s1", store.read, store.renew) for _ in range(5))
        )
        assert store.reads == 1
        assert set(tokens) == {"stored"}

    async def test_simultaneous_expiry_refreshes_once(self) -> None:
        """Otherwise every in-flight tool call spends its own refresh token."""
        factory = FakeFactory(delay=0.02)
        store = FakeStore(_session("old", age=timedelta(hours=2)))
        wi = _cache(factory)
        tokens = await asyncio.gather(
            *(wi.access_token("s1", store.read, store.renew) for _ in range(5))
        )
        assert factory.refreshes == 1
        assert set(tokens) == {"refreshed-1"}

    async def test_two_users_expiring_at_once_do_not_block_each_other(self) -> None:
        factory = FakeFactory()
        wi = _cache(factory)
        alice = FakeStore(_session("old-alice", age=timedelta(hours=2)))
        bob = FakeStore(_session("old-bob", age=timedelta(hours=2)))
        _ = await asyncio.gather(
            wi.access_token("alice", alice.read, alice.renew),
            wi.access_token("bob", bob.read, bob.renew),
        )
        assert factory.refreshes == 2
