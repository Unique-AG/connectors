from typing import ClassVar
import uuid

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken
from mcp_configs import shared_config
from pydantic import Field
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from mcp_skeleton.persistence.auth.tables import AuthorizationCodeRow
from mcp_skeleton.persistence.auth.tables import ClientRow
from mcp_skeleton.persistence.auth.tables import CredentialRow
from mcp_skeleton.persistence.auth.tables import FailedSignInRow
from mcp_skeleton.persistence.auth.tables import PendingSignInRow
from mcp_skeleton.persistence.auth.tables import TokenRow
from mcp_skeleton.persistence.database import Database
from mcp_skeleton.shared import IssuedCode
from mcp_skeleton.shared import IssuedToken
from mcp_skeleton.shared import PendingSignIn
from mcp_skeleton.shared import RegisteredClient
from mcp_skeleton.shared import UpstreamCredentials


class AuthStoreSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("MCP_AUTH_")

    # A Fernet key, as `cryptography.fernet.Fernet.generate_key()` makes. A new key makes every
    # stored password unreadable, so every user signs in again.
    encryption_key: SecretStr = Field(min_length=1)


class SqlAuthStore:
    """The `AuthStore` contract of `shared`, over the MCP's database. Passwords are encrypted with
    the settings' key, tokens kept as hashes by the caller."""

    def __init__(self, database: Database, settings: AuthStoreSettings) -> None:
        self._database: Database = database
        self._fernet: Fernet = Fernet(settings.encryption_key.get_secret_value())

    async def save_client(self, *, client_id: str, registration: str, now: float) -> None:
        async with self._database.begin() as session:
            session.add(ClientRow(client_id=client_id, registration=registration, created_at=now))

    async def get_client(self, client_id: str) -> RegisteredClient | None:
        async with self._database() as session:
            row = await session.get(ClientRow, client_id)
        return None if row is None else RegisteredClient.model_validate(row)

    async def save_pending_sign_in(self, pending: PendingSignIn) -> None:
        async with self._database.begin() as session:
            session.add(
                PendingSignInRow(
                    request_id=pending.request_id,
                    client_id=pending.client_id,
                    scopes=pending.scopes,
                    code_challenge=pending.code_challenge,
                    redirect_uri=pending.redirect_uri,
                    redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
                    state=pending.state,
                    resource=pending.resource,
                    expires_at=pending.expires_at,
                )
            )

    async def get_pending_sign_in(
        self, request_id: str, *, now: float
    ) -> PendingSignIn | None:
        async with self._database() as session:
            row = await session.get(PendingSignInRow, request_id)
        if row is None or row.expires_at < now:
            return None
        return PendingSignIn.model_validate(row)

    async def complete_sign_in(
        self, request_id: str, *, code: str, subject: str, code_expires_at: float, now: float
    ) -> PendingSignIn | None:
        async with self._database.begin() as session:
            pending = await session.scalar(
                delete(PendingSignInRow)
                .where(
                    PendingSignInRow.request_id == request_id, PendingSignInRow.expires_at >= now
                )
                .returning(PendingSignInRow)
            )
            if pending is None:
                return None
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
                    expires_at=code_expires_at,
                )
            )
            return PendingSignIn.model_validate(pending)

    async def get_authorization_code(
        self, code: str, *, client_id: str, now: float
    ) -> IssuedCode | None:
        async with self._database() as session:
            row = await session.get(AuthorizationCodeRow, code)
        if row is None or row.client_id != client_id or row.expires_at < now:
            return None
        return IssuedCode.model_validate(row)

    async def take_authorization_code(self, code: str, *, client_id: str, now: float) -> bool:
        async with self._database.begin() as session:
            taken = await session.scalar(
                delete(AuthorizationCodeRow)
                .where(
                    AuthorizationCodeRow.code == code,
                    AuthorizationCodeRow.client_id == client_id,
                    AuthorizationCodeRow.expires_at >= now,
                )
                .returning(AuthorizationCodeRow.code)
            )
        return taken is not None

    async def save_tokens(
        self, token: IssuedToken, *, access_hash: str, refresh_hash: str
    ) -> None:
        async with self._database.begin() as session:
            session.add(
                TokenRow(
                    id=token.id,
                    family_id=token.family_id,
                    access_token_hash=access_hash,
                    refresh_token_hash=refresh_hash,
                    client_id=token.client_id,
                    scopes=token.scopes,
                    resource=token.resource,
                    subject=token.subject,
                    access_token_expires_at=token.access_token_expires_at,
                    refresh_token_expires_at=token.refresh_token_expires_at,
                    revoked_at=token.revoked_at,
                )
            )

    async def get_token_by_access_hash(self, access_hash: str) -> IssuedToken | None:
        async with self._database() as session:
            row = await session.scalar(
                select(TokenRow).where(TokenRow.access_token_hash == access_hash)
            )
        return None if row is None else IssuedToken.model_validate(row)

    async def get_token_by_refresh_hash(self, refresh_hash: str) -> IssuedToken | None:
        async with self._database() as session:
            row = await session.scalar(
                select(TokenRow).where(TokenRow.refresh_token_hash == refresh_hash)
            )
        return None if row is None else IssuedToken.model_validate(row)

    async def revoke_token(self, token_id: str, *, now: float) -> bool:
        async with self._database.begin() as session:
            revoked = await session.scalar(
                update(TokenRow)
                .where(TokenRow.id == token_id, TokenRow.revoked_at.is_(None))
                .values(revoked_at=now)
                .returning(TokenRow.id)
            )
        return revoked is not None

    async def revoke_family(self, family_id: str, *, now: float) -> None:
        async with self._database.begin() as session:
            await session.execute(
                update(TokenRow)
                .where(TokenRow.family_id == family_id, TokenRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )

    async def revoke_subject(self, subject: str, *, now: float) -> None:
        async with self._database.begin() as session:
            await session.execute(
                update(TokenRow)
                .where(TokenRow.subject == subject, TokenRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )

    async def save_credentials(self, credentials: UpstreamCredentials) -> str:
        encrypted = self._fernet.encrypt(credentials.password.get_secret_value().encode()).decode()
        try:
            return await self._upsert_credentials(credentials.username, encrypted)
        except IntegrityError:
            # Another first sign-in of the same username inserted it in between.
            return await self._upsert_credentials(credentials.username, encrypted)

    async def _upsert_credentials(self, username: str, encrypted: str) -> str:
        async with self._database.begin() as session:
            row = await session.scalar(
                select(CredentialRow).where(CredentialRow.username == username)
            )
            if row is None:
                row = CredentialRow(id=str(uuid.uuid4()), username=username, password=encrypted)
                session.add(row)
            else:
                row.password = encrypted
            return row.id

    async def get_credentials(self, subject: str) -> UpstreamCredentials | None:
        async with self._database() as session:
            row = await session.get(CredentialRow, subject)
        if row is None:
            return None
        try:
            password = self._fernet.decrypt(row.password.encode()).decode()
        except InvalidToken:
            return None
        return UpstreamCredentials(username=row.username, password=SecretStr(password))

    async def count_failed_sign_ins(self, username: str, *, since: float) -> int:
        async with self._database() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(FailedSignInRow)
                .where(FailedSignInRow.username == username, FailedSignInRow.at >= since)
            )
        return count or 0

    async def record_failed_sign_in(self, username: str, *, now: float) -> None:
        async with self._database.begin() as session:
            session.add(FailedSignInRow(id=str(uuid.uuid4()), username=username, at=now))

    async def clear_failed_sign_ins(self, username: str) -> None:
        async with self._database.begin() as session:
            await session.execute(
                delete(FailedSignInRow).where(FailedSignInRow.username == username)
            )

    async def purge_expired(self, *, now: float, failed_sign_ins_before: float) -> None:
        live_families = select(TokenRow.family_id).where(
            TokenRow.revoked_at.is_(None), TokenRow.refresh_token_expires_at >= now
        )
        async with self._database.begin() as session:
            await session.execute(delete(PendingSignInRow).where(PendingSignInRow.expires_at < now))
            await session.execute(
                delete(AuthorizationCodeRow).where(AuthorizationCodeRow.expires_at < now)
            )
            await session.execute(delete(TokenRow).where(TokenRow.family_id.not_in(live_families)))
            await session.execute(
                delete(FailedSignInRow).where(FailedSignInRow.at < failed_sign_ins_before)
            )
