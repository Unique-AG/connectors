import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OAuthClient(Base):
    """A dynamically-registered (RFC 7591) MCP client allowed to talk to this auth server.

    `client_metadata` stores the full `mcp.shared.auth.OAuthClientInformationFull` document
    rather than mapping each of its ~15 optional fields to a column, so nothing is lost when
    reconstructing the client for `get_client()`.
    """

    __tablename__: str = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String, primary_key=True)
    client_metadata: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAuthorization(Base):
    """An in-flight `/authorize`, waiting on the hosted login form to be submitted.

    `authorize()` persists the incoming `AuthorizationParams` here and redirects the browser to
    our own form, keyed by `request_id`; the POST handler looks this row back up to know which
    client, redirect_uri and PKCE challenge to mint a code for.
    """

    __tablename__: str = "pending_authorizations"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id"))
    scopes: Mapped[list[str]] = mapped_column(JSON)
    code_challenge: Mapped[str] = mapped_column(String)
    redirect_uri: Mapped[str] = mapped_column(String)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    resource: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthorizationCode(Base):
    """A short-lived code minted after a successful vendor login, pending token exchange.

    Field shape mirrors `mcp.server.auth.provider.AuthorizationCode`. `subject` is the resolved
    `user_id`, propagated into the issued tokens so `auth/context.py` can resolve whose vendor
    credential to use.
    """

    __tablename__: str = "authorization_codes"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id"))
    scopes: Mapped[list[str]] = mapped_column(JSON)
    code_challenge: Mapped[str] = mapped_column(String)
    redirect_uri: Mapped[str] = mapped_column(String)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean)
    resource: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    expires_at: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthToken(Base):
    """An issued MCP-facing access/refresh token pair.

    Only a SHA-256 hash of each token is stored: unlike the credential blob, which is useless
    without the Fernet key, a leaked plaintext token here would be directly usable.

    `family_id` is shared by every rotation descending from one grant, so a replayed
    already-rotated refresh token can revoke the whole family in one query rather than walking
    the `rotated_from` chain.
    """

    __tablename__: str = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    access_token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    refresh_token_hash: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id"))
    scopes: Mapped[list[str]] = mapped_column(JSON)
    resource: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rotated_from: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("oauth_tokens.id"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WithIntelligenceCredential(Base):
    """A user's With Intelligence username and password, encrypted at rest.

    The password rather than a vendor session: their access token lives an hour and the refresh
    token 30 days, so a stored session would expire while a stored password keeps working. The
    session itself is held in memory (see `features/vendor_session`) and re-obtained after a
    restart.
    """

    __tablename__: str = "with_intelligence_credentials"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    wi_username: Mapped[str] = mapped_column(String, unique=True, index=True)
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LoginAttempt(Base):
    """One *failed* login submission, for rate-limiting the hosted form.

    Only failures are recorded and a success deletes the username's rows, so a user who mistypes
    twice and then succeeds carries no penalty. Rows rather than a counter: the window becomes a
    pure read and the limit holds across replicas with no coordination.

    `source_ip` is for diagnosis only and is deliberately not rate-limited on — see
    `auth/throttle.py`.
    """

    __tablename__: str = "login_attempts"

    __table_args__: tuple[Index, ...] = (
        Index("ix_login_attempts_username_attempted_at", "username", "attempted_at"),
        Index("ix_login_attempts_attempted_at", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String)
    source_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
