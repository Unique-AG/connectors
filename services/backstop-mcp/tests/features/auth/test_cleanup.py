import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.config import AuthConfig
from backstop_mcp.db import (
    AuthorizationCode,
    LoginAttempt,
    OAuthClient,
    OAuthToken,
    PendingAuthorization,
    read_session,
    transaction,
)
from backstop_mcp.features.auth.cleanup import purge_expired_auth_rows

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

# Exercise the shipped defaults, so a change to either lands here.
AUTH_CONFIG = AuthConfig()
NOW = datetime.now(UTC)
LONG_AGO = NOW - AUTH_CONFIG.token_retention - timedelta(days=1)


async def _register_client(
    session_factory: async_sessionmaker[AsyncSession], client_id: str
) -> None:
    async with transaction(session_factory) as session:
        session.add(OAuthClient(client_id=client_id, client_metadata={}))


def _token(
    client_id: str,
    *,
    family_id: uuid.UUID,
    access_expires_at: datetime,
    refresh_expires_at: datetime | None,
    rotated_from: uuid.UUID | None = None,
) -> OAuthToken:
    suffix = uuid.uuid4().hex
    return OAuthToken(
        id=uuid.uuid4(),
        family_id=family_id,
        access_token_hash=f"access-{suffix}",
        refresh_token_hash=f"refresh-{suffix}",
        client_id=client_id,
        scopes=[],
        subject="subject-1",
        access_token_expires_at=access_expires_at,
        refresh_token_expires_at=refresh_expires_at,
        rotated_from=rotated_from,
    )


async def _token_ids(session_factory: async_sessionmaker[AsyncSession]) -> set[uuid.UUID]:
    async with read_session(session_factory) as session:
        result = await session.execute(select(OAuthToken.id))
        return set(result.scalars().all())


class TestPurgeExpiredAuthRows:
    @pytest.mark.asyncio
    async def test_drops_expired_pending_authorizations_and_keeps_live_ones(
        self, db: DatabaseFixture
    ) -> None:
        _, session_factory = db
        await _register_client(session_factory, "cleanup-client-pending")

        async with transaction(session_factory) as session:
            for request_id, expires_at in (
                ("cleanup-pending-stale", NOW - timedelta(minutes=1)),
                ("cleanup-pending-live", NOW + timedelta(minutes=10)),
            ):
                session.add(
                    PendingAuthorization(
                        request_id=request_id,
                        client_id="cleanup-client-pending",
                        scopes=[],
                        code_challenge="challenge",
                        redirect_uri="https://client.example/callback",
                        redirect_uri_provided_explicitly=True,
                        expires_at=expires_at,
                    )
                )

        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=AUTH_CONFIG.login_attempt_window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )

        async with read_session(session_factory) as session:
            assert await session.get(PendingAuthorization, "cleanup-pending-stale") is None
            assert await session.get(PendingAuthorization, "cleanup-pending-live") is not None

    @pytest.mark.asyncio
    async def test_drops_expired_authorization_codes_and_keeps_live_ones(
        self, db: DatabaseFixture
    ) -> None:
        _, session_factory = db
        await _register_client(session_factory, "cleanup-client-codes")

        async with transaction(session_factory) as session:
            for code, expires_at in (
                ("cleanup-code-stale", NOW - timedelta(minutes=1)),
                ("cleanup-code-live", NOW + timedelta(minutes=5)),
            ):
                session.add(
                    AuthorizationCode(
                        code=code,
                        client_id="cleanup-client-codes",
                        scopes=[],
                        code_challenge="challenge",
                        redirect_uri="https://client.example/callback",
                        redirect_uri_provided_explicitly=True,
                        subject="subject-1",
                        expires_at=expires_at.timestamp(),
                    )
                )

        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=AUTH_CONFIG.login_attempt_window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )

        async with read_session(session_factory) as session:
            assert await session.get(AuthorizationCode, "cleanup-code-stale") is None
            assert await session.get(AuthorizationCode, "cleanup-code-live") is not None

    @pytest.mark.asyncio
    async def test_keeps_a_token_family_still_inside_the_retention_window(
        self, db: DatabaseFixture
    ) -> None:
        """Expiry alone isn't enough — the rows stay an audit trail for the retention window."""
        _, session_factory = db
        await _register_client(session_factory, "cleanup-client-recent")
        family_id = uuid.uuid4()

        async with transaction(session_factory) as session:
            session.add(
                _token(
                    "cleanup-client-recent",
                    family_id=family_id,
                    access_expires_at=NOW - timedelta(hours=1),
                    refresh_expires_at=NOW - timedelta(minutes=30),
                )
            )
        before = await _token_ids(session_factory)

        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=AUTH_CONFIG.login_attempt_window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )

        assert await _token_ids(session_factory) == before

    @pytest.mark.asyncio
    async def test_drops_a_whole_rotation_chain_once_every_member_is_past_retention(
        self, db: DatabaseFixture
    ) -> None:
        """Deleting by family is what keeps `rotated_from` from stranding a foreign key."""
        _, session_factory = db
        await _register_client(session_factory, "cleanup-client-old")
        family_id = uuid.uuid4()

        async with transaction(session_factory) as session:
            ancestor = _token(
                "cleanup-client-old",
                family_id=family_id,
                access_expires_at=LONG_AGO - timedelta(days=30),
                refresh_expires_at=LONG_AGO - timedelta(days=1),
            )
            session.add(ancestor)
            await session.flush()
            session.add(
                _token(
                    "cleanup-client-old",
                    family_id=family_id,
                    access_expires_at=LONG_AGO,
                    refresh_expires_at=LONG_AGO,
                    rotated_from=ancestor.id,
                )
            )

        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=AUTH_CONFIG.login_attempt_window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )

        async with read_session(session_factory) as session:
            result = await session.execute(
                select(OAuthToken).where(OAuthToken.family_id == family_id)
            )
            assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_spares_an_old_ancestor_whose_descendant_is_still_live(
        self, db: DatabaseFixture
    ) -> None:
        """The live descendant's `rotated_from` must keep pointing at a row that exists."""
        _, session_factory = db
        await _register_client(session_factory, "cleanup-client-mixed")
        family_id = uuid.uuid4()

        async with transaction(session_factory) as session:
            ancestor = _token(
                "cleanup-client-mixed",
                family_id=family_id,
                access_expires_at=LONG_AGO,
                refresh_expires_at=LONG_AGO,
            )
            session.add(ancestor)
            await session.flush()
            session.add(
                _token(
                    "cleanup-client-mixed",
                    family_id=family_id,
                    access_expires_at=NOW + timedelta(minutes=15),
                    refresh_expires_at=NOW + timedelta(days=30),
                    rotated_from=ancestor.id,
                )
            )
            ancestor_id = ancestor.id

        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=AUTH_CONFIG.login_attempt_window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )

        async with read_session(session_factory) as session:
            assert await session.get(OAuthToken, ancestor_id) is not None

    @pytest.mark.asyncio
    async def test_is_idempotent(self, db: DatabaseFixture) -> None:
        """Replicas sweep independently, so a second pass must be a no-op rather than an error."""
        _, session_factory = db
        await _register_client(session_factory, "cleanup-client-twice")

        async with transaction(session_factory) as session:
            session.add(
                _token(
                    "cleanup-client-twice",
                    family_id=uuid.uuid4(),
                    access_expires_at=LONG_AGO,
                    refresh_expires_at=LONG_AGO,
                )
            )

        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=AUTH_CONFIG.login_attempt_window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )
        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=AUTH_CONFIG.login_attempt_window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )


class TestPurgeLoginAttempts:
    """Failed-login rows are the one table an attacker can drive growth in."""

    @staticmethod
    async def _seed(
        session_factory: async_sessionmaker[AsyncSession], username: str, *, age: timedelta
    ) -> None:
        async with transaction(session_factory) as session:
            session.add(
                LoginAttempt(
                    username=username, source_ip=None, attempted_at=datetime.now(UTC) - age
                )
            )

    @staticmethod
    async def _remaining(session_factory: async_sessionmaker[AsyncSession], username: str) -> int:
        async with read_session(session_factory) as session:
            result = await session.execute(
                select(LoginAttempt).where(LoginAttempt.username == username)
            )
            return len(result.scalars().all())

    @pytest.mark.asyncio
    async def test_drops_attempts_older_than_two_windows(self, db: DatabaseFixture) -> None:
        _, session_factory = db
        username = "cleanup-attempts-old"
        window = AUTH_CONFIG.login_attempt_window
        await self._seed(session_factory, username, age=2 * window + timedelta(minutes=1))

        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )

        assert await self._remaining(session_factory, username) == 0

    @pytest.mark.asyncio
    async def test_keeps_attempts_the_throttle_still_counts(self, db: DatabaseFixture) -> None:
        """Purging inside the window would silently hand an attacker a fresh budget."""
        _, session_factory = db
        username = "cleanup-attempts-recent"
        window = AUTH_CONFIG.login_attempt_window
        await self._seed(session_factory, username, age=timedelta(minutes=1))

        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )

        assert await self._remaining(session_factory, username) == 1


class TestPurgeUnreferencedClients:
    """Dynamic client registration is open, so `oauth_clients` is the one table an
    unauthenticated caller can grow directly — and nothing used to remove a row from it."""

    @staticmethod
    async def _client_ids(session_factory: async_sessionmaker[AsyncSession]) -> set[str]:
        async with read_session(session_factory) as session:
            result = await session.execute(select(OAuthClient.client_id))
            return set(result.scalars().all())

    @staticmethod
    async def _backdate_client(
        session_factory: async_sessionmaker[AsyncSession], client_id: str, *, age: timedelta
    ) -> None:
        """Age a client past the retention floor.

        `created_at` is a `server_default`, so a freshly-inserted row is always 'now' and no
        amount of sweeping would touch it — the age has to be written explicitly.
        """
        async with transaction(session_factory) as session:
            client = await session.get(OAuthClient, client_id)
            assert client is not None
            client.created_at = datetime.now(UTC) - age

    async def _sweep(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        await purge_expired_auth_rows(
            session_factory,
            token_retention=AUTH_CONFIG.token_retention,
            login_attempt_window=AUTH_CONFIG.login_attempt_window,
            unused_client_retention=AUTH_CONFIG.unused_client_retention,
        )

    @pytest.mark.asyncio
    async def test_drops_a_client_that_registered_and_never_came_back(
        self, db: DatabaseFixture
    ) -> None:
        _, session_factory = db
        client_id = "cleanup-client-abandoned"
        await _register_client(session_factory, client_id)
        await self._backdate_client(
            session_factory, client_id, age=AUTH_CONFIG.unused_client_retention + timedelta(hours=1)
        )

        await self._sweep(session_factory)

        assert client_id not in await self._client_ids(session_factory)

    @pytest.mark.asyncio
    async def test_keeps_a_client_that_only_just_registered(self, db: DatabaseFixture) -> None:
        """The floor is what stops a client being swept mid-handshake, before its first token."""
        _, session_factory = db
        client_id = "cleanup-client-fresh"
        await _register_client(session_factory, client_id)

        await self._sweep(session_factory)

        assert client_id in await self._client_ids(session_factory)

    @pytest.mark.asyncio
    async def test_keeps_an_old_client_that_still_holds_a_live_token(
        self, db: DatabaseFixture
    ) -> None:
        """A client in continuous use is old *and* referenced.

        Only the second of those may spare it, which is what the `not_in` guards are for.
        """
        _, session_factory = db
        client_id = "cleanup-client-in-use"
        await _register_client(session_factory, client_id)
        await self._backdate_client(
            session_factory, client_id, age=AUTH_CONFIG.unused_client_retention + timedelta(days=30)
        )
        async with transaction(session_factory) as session:
            session.add(
                _token(
                    client_id,
                    family_id=uuid.uuid4(),
                    access_expires_at=NOW + timedelta(minutes=15),
                    refresh_expires_at=NOW + timedelta(days=30),
                )
            )

        await self._sweep(session_factory)

        assert client_id in await self._client_ids(session_factory)

    @pytest.mark.asyncio
    async def test_reclaims_a_client_in_the_same_sweep_that_purges_its_last_token(
        self, db: DatabaseFixture
    ) -> None:
        """Why the client sweep runs last: the token delete above is what unreferences it."""
        _, session_factory = db
        client_id = "cleanup-client-last-token"
        await _register_client(session_factory, client_id)
        await self._backdate_client(
            session_factory, client_id, age=AUTH_CONFIG.unused_client_retention + timedelta(days=1)
        )
        async with transaction(session_factory) as session:
            session.add(
                _token(
                    client_id,
                    family_id=uuid.uuid4(),
                    access_expires_at=LONG_AGO,
                    refresh_expires_at=LONG_AGO,
                )
            )

        await self._sweep(session_factory)

        assert client_id not in await self._client_ids(session_factory)

    @pytest.mark.asyncio
    async def test_keeps_a_client_with_an_authorization_still_in_flight(
        self, db: DatabaseFixture
    ) -> None:
        """A pending row is a foreign key: sweeping the client would violate it."""
        _, session_factory = db
        client_id = "cleanup-client-inflight"
        await _register_client(session_factory, client_id)
        await self._backdate_client(
            session_factory, client_id, age=AUTH_CONFIG.unused_client_retention + timedelta(days=1)
        )
        async with transaction(session_factory) as session:
            session.add(
                PendingAuthorization(
                    request_id="cleanup-client-inflight-request",
                    client_id=client_id,
                    scopes=[],
                    code_challenge="challenge",
                    redirect_uri="https://client.example/callback",
                    redirect_uri_provided_explicitly=True,
                    expires_at=NOW + timedelta(minutes=10),
                )
            )

        await self._sweep(session_factory)

        assert client_id in await self._client_ids(session_factory)
