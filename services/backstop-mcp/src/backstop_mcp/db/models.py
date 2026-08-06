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
    (it has ~15 optional RFC 7591 fields) rather than mapping each field to its own column, so
    nothing is lost or needs re-deriving when reconstructing the client for `get_client()`.
    """

    __tablename__: str = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String, primary_key=True)
    client_metadata: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAuthorization(Base):
    """An in-flight `/authorize` request, waiting on the Backstop login form to be submitted.

    `authorize()` persists the incoming `AuthorizationParams` here and redirects the browser to
    our own login form, keyed by `request_id`; the form's POST handler looks this row back up
    to know which client/redirect_uri/PKCE-challenge to mint the eventual authorization code for.
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
    """A short-lived code minted after a successful Backstop login, pending token exchange.

    Field shape mirrors `mcp.server.auth.provider.AuthorizationCode` exactly. `subject` is the
    resolved `user_id` — the SDK's own term for "resource owner", propagated through to the
    issued access/refresh tokens so `auth/context.py` can resolve "whose Backstop credential".
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

    Tokens are bearer credentials — unlike `BackstopCredential.encrypted_blob`, which needs the
    Fernet key to be useful, a leaked plaintext token here would be directly usable. So only a
    SHA-256 hash of each token is stored; lookups hash the presented token and query by hash.

    `rotated_from` links a refresh to the token row it replaced (audit trail). `family_id` is
    shared by every rotation descending from the same original grant, so a replayed
    (already-rotated-away) refresh token can revoke the *entire* family in one query, without
    walking the `rotated_from` chain.
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


class BackstopCredential(Base):
    """A user's Backstop username + personal API token, encrypted at rest."""

    __tablename__: str = "backstop_credentials"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    backstop_username: Mapped[str] = mapped_column(String, unique=True, index=True)
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LoginAttempt(Base):
    """One *failed* Backstop login submission, for rate-limiting the hosted login form.

    Only failures are recorded, and a successful login deletes the username's rows — so a
    legitimate user who mistypes twice and then succeeds carries no penalty.

    Rows rather than a counter column: a counter needs a window boundary baked in at write time,
    while rows let the window be a pure read (`attempted_at >= now - window`) and make the limit
    hold across replicas without any coordination. `auth/cleanup.py` purges old rows.

    `source_ip` is recorded for diagnosis only and is deliberately *not* rate-limited on — see
    `auth/throttle.py` for why.
    """

    __tablename__: str = "login_attempts"

    # Kept in step with the indexes created in
    # `migrations/versions/b2c3d4e5f6a7_add_login_attempts.py`: the composite serves the
    # throttle's `username = ? AND attempted_at >= ?` read, `attempted_at` alone serves the
    # cleanup sweep's range delete.
    __table_args__: tuple[Index, ...] = (
        Index("ix_login_attempts_username_attempted_at", "username", "attempted_at"),
        Index("ix_login_attempts_attempted_at", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String)
    source_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomFieldSchemaSnapshot(Base):
    """Cached Backstop custom-field definitions for one API base_url (one instance)."""

    __tablename__: str = "custom_field_schema_snapshots"

    base_url: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[object] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
