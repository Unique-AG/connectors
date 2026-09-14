import hashlib
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Literal, override

from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken as OAuthTokenResponse
from pydantic import AnyUrl, BaseModel, ConfigDict
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth.database import read_session, transaction
from mcp_credential_auth.models import (
    AuthorizationCode as AuthorizationCodeRow,
)
from mcp_credential_auth.models import (
    OAuthClient as OAuthClientRow,
)
from mcp_credential_auth.models import (
    OAuthToken as OAuthTokenRow,
)
from mcp_credential_auth.models import PendingAuthorization

type SubjectFactory = Callable[[AsyncSession], Awaitable[str]]


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class _RefreshRotated(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    scopes: list[str]


class _RefreshRejected(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    error: Literal["invalid_grant", "invalid_scope"]
    description: str


type _RefreshOutcome = _RefreshRotated | _RefreshRejected

_UNKNOWN_TOKEN = _RefreshRejected(error="invalid_grant", description="Unknown refresh token")
_REUSED_TOKEN = _RefreshRejected(
    error="invalid_grant", description="Refresh token has already been used"
)
_EXPIRED_TOKEN = _RefreshRejected(error="invalid_grant", description="Refresh token has expired")
_INVALID_SCOPE = _RefreshRejected(
    error="invalid_scope", description="Requested scope exceeds originally granted scopes"
)


class CredentialOAuthProvider(OAuthProvider):
    ACCESS_TOKEN_TTL: ClassVar[timedelta] = timedelta(minutes=15)
    REFRESH_TOKEN_TTL: ClassVar[timedelta] = timedelta(days=30)
    AUTHORIZATION_CODE_TTL: ClassVar[timedelta] = timedelta(minutes=5)
    PENDING_AUTHORIZATION_TTL: ClassVar[timedelta] = timedelta(minutes=10)

    _session_factory: async_sessionmaker[AsyncSession]
    _issuer: str
    login_path: str
    access_token_ttl: timedelta
    refresh_token_ttl: timedelta
    authorization_code_ttl: timedelta
    pending_authorization_ttl: timedelta

    def __init__(
        self,
        *,
        base_url: str,
        session_factory: async_sessionmaker[AsyncSession],
        login_path: str,
        access_token_ttl: timedelta | None = None,
        refresh_token_ttl: timedelta | None = None,
        authorization_code_ttl: timedelta | None = None,
        pending_authorization_ttl: timedelta | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
        self._session_factory = session_factory
        self.login_path = login_path
        self._issuer = base_url
        self.access_token_ttl = (
            self.ACCESS_TOKEN_TTL if access_token_ttl is None else access_token_ttl
        )
        self.refresh_token_ttl = (
            self.REFRESH_TOKEN_TTL if refresh_token_ttl is None else refresh_token_ttl
        )
        self.authorization_code_ttl = (
            self.AUTHORIZATION_CODE_TTL
            if authorization_code_ttl is None
            else authorization_code_ttl
        )
        self.pending_authorization_ttl = (
            self.PENDING_AUTHORIZATION_TTL
            if pending_authorization_ttl is None
            else pending_authorization_ttl
        )

    @override
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with read_session(self._session_factory) as session:
            row = await session.get(OAuthClientRow, client_id)
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate(row.client_metadata)

    @override
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None, "client_id must be assigned before registration"
        async with transaction(self._session_factory) as session:
            session.add(
                OAuthClientRow(
                    client_id=client_info.client_id,
                    client_metadata=client_info.model_dump(mode="json"),
                )
            )

    @override
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        assert client.client_id is not None
        request_id = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + self.pending_authorization_ttl

        async with transaction(self._session_factory) as session:
            session.add(
                PendingAuthorization(
                    request_id=request_id,
                    client_id=client.client_id,
                    scopes=params.scopes or [],
                    code_challenge=params.code_challenge,
                    redirect_uri=str(params.redirect_uri),
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    state=params.state,
                    resource=params.resource,
                    expires_at=expires_at,
                )
            )

        return f"{self._issuer}{self.login_path}?request_id={request_id}"

    async def load_pending_authorization(self, request_id: str) -> PendingAuthorization | None:
        if not request_id:
            return None
        async with read_session(self._session_factory) as session:
            pending = await session.get(PendingAuthorization, request_id)
        if pending is None or pending.expires_at < datetime.now(UTC):
            return None
        return pending

    async def complete_authorization(
        self,
        pending: PendingAuthorization,
        subject_factory: SubjectFactory,
    ) -> str | None:
        code = secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + self.authorization_code_ttl).timestamp()

        async with transaction(self._session_factory) as session:
            claim = await session.execute(
                delete(PendingAuthorization)
                .where(PendingAuthorization.request_id == pending.request_id)
                .returning(PendingAuthorization.request_id)
            )
            if claim.scalar_one_or_none() is None:
                return None
            subject = await subject_factory(session)
            session.add(
                AuthorizationCodeRow(
                    code=code,
                    client_id=pending.client_id,
                    scopes=pending.scopes,
                    code_challenge=pending.code_challenge,
                    redirect_uri=pending.redirect_uri,
                    redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
                    resource=pending.resource,
                    subject=subject,
                    expires_at=expires_at,
                )
            )

        return construct_redirect_uri(pending.redirect_uri, code=code, state=pending.state)

    @override
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with read_session(self._session_factory) as session:
            row = await session.get(AuthorizationCodeRow, authorization_code)
        if row is None or row.client_id != client.client_id or row.expires_at < time.time():
            return None
        return AuthorizationCode(
            code=row.code,
            scopes=row.scopes,
            expires_at=row.expires_at,
            client_id=row.client_id,
            code_challenge=row.code_challenge,
            redirect_uri=AnyUrl(row.redirect_uri),
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            resource=row.resource,
            subject=row.subject,
        )

    @override
    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthTokenResponse:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        already_consumed = False

        async with transaction(self._session_factory) as session:
            result = await session.execute(
                delete(AuthorizationCodeRow)
                .where(AuthorizationCodeRow.code == authorization_code.code)
                .returning(AuthorizationCodeRow.code)
            )
            if result.scalar_one_or_none() is None:
                already_consumed = True
            else:
                session.add(
                    OAuthTokenRow(
                        family_id=uuid.uuid4(),
                        access_token_hash=_hash_token(access_token),
                        refresh_token_hash=_hash_token(refresh_token),
                        client_id=client.client_id,
                        scopes=authorization_code.scopes,
                        resource=authorization_code.resource,
                        subject=authorization_code.subject,
                        access_token_expires_at=now + self.access_token_ttl,
                        refresh_token_expires_at=now + self.refresh_token_ttl,
                    )
                )

        if already_consumed:
            raise TokenError(
                error="invalid_grant",
                error_description="Authorization code has already been used",
            )

        return OAuthTokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=int(self.access_token_ttl.total_seconds()),
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
            refresh_token=refresh_token,
        )

    @override
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        token_hash = _hash_token(refresh_token)
        async with read_session(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(OAuthTokenRow.refresh_token_hash == token_hash)
            )
            row = result.scalar_one_or_none()

        if row is None or row.client_id != client.client_id:
            return None

        return RefreshToken(
            token=refresh_token,
            client_id=row.client_id,
            scopes=row.scopes,
            expires_at=(
                int(row.refresh_token_expires_at.timestamp())
                if row.refresh_token_expires_at
                else None
            ),
            subject=row.subject,
        )

    @override
    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthTokenResponse:
        outcome = await self._rotate_refresh_token(refresh_token, scopes)

        if isinstance(outcome, _RefreshRejected):
            raise TokenError(error=outcome.error, error_description=outcome.description)

        return OAuthTokenResponse(
            access_token=outcome.access_token,
            token_type="Bearer",
            expires_in=int(self.access_token_ttl.total_seconds()),
            scope=" ".join(outcome.scopes) if outcome.scopes else None,
            refresh_token=outcome.refresh_token,
        )

    async def _rotate_refresh_token(
        self, refresh_token: RefreshToken, scopes: list[str]
    ) -> _RefreshOutcome:
        token_hash = _hash_token(refresh_token.token)
        now = datetime.now(UTC)

        async with transaction(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(OAuthTokenRow.refresh_token_hash == token_hash)
            )
            row = result.scalar_one_or_none()

            if row is None:
                return _UNKNOWN_TOKEN

            if row.revoked_at is not None:
                await self._revoke_family(session, family_id=row.family_id, now=now)
                return _REUSED_TOKEN

            if row.refresh_token_expires_at is not None and row.refresh_token_expires_at < now:
                return _EXPIRED_TOKEN

            if scopes and not set(scopes).issubset(row.scopes):
                return _INVALID_SCOPE

            claim = await session.execute(
                update(OAuthTokenRow)
                .where(
                    OAuthTokenRow.id == row.id,
                    OAuthTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=now)
                .returning(OAuthTokenRow.id)
            )
            if claim.scalar_one_or_none() is None:
                await self._revoke_family(session, family_id=row.family_id, now=now)
                return _REUSED_TOKEN

            access_token = secrets.token_urlsafe(32)
            new_refresh_token = secrets.token_urlsafe(32)
            effective_scopes = scopes or row.scopes

            session.add(
                OAuthTokenRow(
                    family_id=row.family_id,
                    access_token_hash=_hash_token(access_token),
                    refresh_token_hash=_hash_token(new_refresh_token),
                    client_id=row.client_id,
                    scopes=effective_scopes,
                    resource=row.resource,
                    subject=row.subject,
                    access_token_expires_at=now + self.access_token_ttl,
                    refresh_token_expires_at=now + self.refresh_token_ttl,
                    rotated_from=row.id,
                )
            )
            return _RefreshRotated(
                access_token=access_token,
                refresh_token=new_refresh_token,
                scopes=effective_scopes,
            )

    @staticmethod
    async def _revoke_family(session: AsyncSession, *, family_id: uuid.UUID, now: datetime) -> None:
        await session.execute(
            update(OAuthTokenRow)
            .where(
                OAuthTokenRow.family_id == family_id,
                OAuthTokenRow.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    @override
    async def load_access_token(self, token: str) -> AccessToken | None:
        token_hash = _hash_token(token)
        async with read_session(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(OAuthTokenRow.access_token_hash == token_hash)
            )
            row = result.scalar_one_or_none()

        if (
            row is None
            or row.revoked_at is not None
            or row.access_token_expires_at < datetime.now(UTC)
        ):
            return None

        return AccessToken(
            token=token,
            client_id=row.client_id,
            scopes=row.scopes,
            expires_at=int(row.access_token_expires_at.timestamp()),
            resource=row.resource,
            subject=row.subject,
        )

    @override
    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_hash = _hash_token(token.token)
        async with transaction(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(
                    (OAuthTokenRow.access_token_hash == token_hash)
                    | (OAuthTokenRow.refresh_token_hash == token_hash)
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                row.revoked_at = datetime.now(UTC)

    async def revoke_all_tokens_for_subject(self, subject: str) -> None:
        async with transaction(self._session_factory) as session:
            await session.execute(
                update(OAuthTokenRow)
                .where(
                    OAuthTokenRow.subject == subject,
                    OAuthTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
