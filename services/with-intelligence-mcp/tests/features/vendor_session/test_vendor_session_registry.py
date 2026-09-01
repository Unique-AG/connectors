"""One live vendor session per user, renewed under a lock."""

import asyncio
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr

from with_intelligence_mcp.features.vendor_session import VendorSessionRegistry
from with_intelligence_mcp.with_intelligence_client import VendorCredential, VendorSession

CREDENTIAL = VendorCredential(username="u", password=SecretStr("pw"))


async def _credential() -> VendorCredential:
    return CREDENTIAL


def _session(token: str, *, age: timedelta = timedelta(0)) -> VendorSession:
    return VendorSession.model_validate(
        {
            "access_token": token,
            "refresh_token": f"refresh-{token}",
            "issued_at": datetime.now(UTC) - age,
        }
    )


class FakeFactory:
    """Counts the two auth calls, and can be made to fail the refresh or stall."""

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


def _registry(factory: FakeFactory) -> VendorSessionRegistry:
    return VendorSessionRegistry(factory)  # pyright: ignore[reportArgumentType]


class TestFirstUse:
    async def test_signs_in_on_first_use(self) -> None:
        factory = FakeFactory()
        assert await _registry(factory).access_token("s1", _credential) == "signed-in-1"
        assert (factory.sign_ins, factory.refreshes) == (1, 0)

    async def test_reuses_a_fresh_token(self) -> None:
        factory = FakeFactory()
        registry = _registry(factory)
        first = await registry.access_token("s1", _credential)
        assert await registry.access_token("s1", _credential) == first
        assert factory.sign_ins == 1


class TestPerSubject:
    async def test_two_users_get_their_own_session(self) -> None:
        """A shared session would hand one user's data to another."""
        factory = FakeFactory()
        registry = _registry(factory)
        first = await registry.access_token("alice", _credential)
        second = await registry.access_token("bob", _credential)
        assert first != second
        assert factory.sign_ins == 2

    async def test_forgetting_one_user_leaves_the_other(self) -> None:
        factory = FakeFactory()
        registry = _registry(factory)
        alice = await registry.access_token("alice", _credential)
        _ = await registry.access_token("bob", _credential)
        registry.forget("bob")
        assert await registry.access_token("alice", _credential) == alice
        assert factory.sign_ins == 2


class TestRenewal:
    async def test_an_expired_token_is_refreshed_not_re_signed(self) -> None:
        factory = FakeFactory()
        registry = _registry(factory)
        holder = await registry._holder_for("s1")  # pyright: ignore[reportPrivateUsage]
        holder.session = _session("old", age=timedelta(hours=2))
        assert await registry.access_token("s1", _credential) == "refreshed-1"
        assert (factory.sign_ins, factory.refreshes) == (0, 1)

    async def test_a_spent_refresh_token_falls_back_to_signing_in(self) -> None:
        """Which is why the password is what gets persisted, not the session."""
        factory = FakeFactory(refresh_fails=True)
        registry = _registry(factory)
        holder = await registry._holder_for("s1")  # pyright: ignore[reportPrivateUsage]
        holder.session = _session("old", age=timedelta(hours=2))
        assert await registry.access_token("s1", _credential) == "signed-in-1"
        assert (factory.sign_ins, factory.refreshes) == (1, 1)

    async def test_renewed_access_token_forces_a_renewal(self) -> None:
        factory = FakeFactory()
        registry = _registry(factory)
        _ = await registry.access_token("s1", _credential)
        assert await registry.renewed_access_token("s1", _credential) == "refreshed-1"


class TestConcurrentRenewal:
    async def test_simultaneous_first_use_signs_in_once(self) -> None:
        factory = FakeFactory(delay=0.02)
        registry = _registry(factory)
        tokens = await asyncio.gather(*(registry.access_token("s1", _credential) for _ in range(5)))
        assert factory.sign_ins == 1
        assert set(tokens) == {"signed-in-1"}

    async def test_simultaneous_expiry_refreshes_once(self) -> None:
        """Otherwise every in-flight tool call spends its own refresh token."""
        factory = FakeFactory(delay=0.02)
        registry = _registry(factory)
        holder = await registry._holder_for("s1")  # pyright: ignore[reportPrivateUsage]
        holder.session = _session("old", age=timedelta(hours=2))
        tokens = await asyncio.gather(*(registry.access_token("s1", _credential) for _ in range(5)))
        assert factory.refreshes == 1
        assert set(tokens) == {"refreshed-1"}

    async def test_two_users_expiring_at_once_do_not_block_each_other(self) -> None:
        factory = FakeFactory()
        registry = _registry(factory)
        for subject in ("alice", "bob"):
            holder = await registry._holder_for(subject)  # pyright: ignore[reportPrivateUsage]
            holder.session = _session(f"old-{subject}", age=timedelta(hours=2))
        _ = await asyncio.gather(
            registry.access_token("alice", _credential),
            registry.access_token("bob", _credential),
        )
        assert factory.refreshes == 2
