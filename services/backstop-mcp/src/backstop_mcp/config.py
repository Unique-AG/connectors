import os
import ssl
from datetime import timedelta
from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import Annotated, ClassVar, Self, TypedDict, cast

from pydantic import (
    BeforeValidator,
    Field,
    HttpUrl,
    PostgresDsn,
    PrivateAttr,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine.url import URL, make_url

PKG_VERSION = pkg_version("backstop-mcp")

_HTTP_URL = TypeAdapter(HttpUrl)


def _http_url_str(value: object) -> str:
    """Validate as an HTTP(S) URL, then keep a plain string without a trailing slash.

    `HttpUrl` always stringifies with a trailing `/`, which is a bad contract for OAuth issuers
    and for call sites that join paths. Validate with pydantic, store what operators typed.
    """
    return str(_HTTP_URL.validate_python(value)).rstrip("/")


HttpUrlStr = Annotated[str, BeforeValidator(_http_url_str)]

_CUSTOM_FIELD_SCHEMA_TTL_MAX_MINUTES = 24 * 60


def _cap_custom_field_schema_ttl_minutes(value: object) -> object:
    """Clamp leftover week-long TTL env values to 24h instead of failing startup."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return min(value, _CUSTOM_FIELD_SCHEMA_TTL_MAX_MINUTES)
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return value
        return min(parsed, _CUSTOM_FIELD_SCHEMA_TTL_MAX_MINUTES)
    return value


class AsyncpgConnectArgs(TypedDict, total=False):
    ssl: ssl.SSLContext


def _ssl_connect_arg(sslmode: str) -> ssl.SSLContext | None:
    """Map a libpq `sslmode` value to an asyncpg `ssl` connect argument."""
    if sslmode in ("disable", "allow"):
        return None
    if sslmode in ("require", "prefer"):
        # Encrypt the connection but do not verify the server certificate.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if sslmode == "verify-ca":
        # Libpq verify-ca checks the CA chain only — not the hostname (that is verify-full).
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        return ctx
    if sslmode in ("verify", "verify-full"):
        return ssl.create_default_context()
    raise ValueError(f"Unsupported sslmode={sslmode!r} in database URL")


def _query_param(query: dict[str, str | tuple[str, ...]], key: str) -> str | None:
    value = query.get(key)
    if value is None:
        return None
    if isinstance(value, tuple):
        return value[0] if value else None
    return value


def normalize_asyncpg_url(url: str) -> tuple[str, AsyncpgConnectArgs]:
    """Rewrite a libpq Postgres URL for SQLAlchemy/asyncpg.

    Helm injects `DATABASE_URL` with libpq query params (`sslmode=...`). asyncpg rejects
    those params, so strip them and return equivalent `connect_args` instead.
    """
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+asyncpg")
    elif not parsed.drivername.startswith("postgresql"):
        raise ValueError("DB_URL must be a PostgreSQL connection string (postgresql://...)")

    sslmode = _query_param(dict(parsed.query), "sslmode")
    parsed = parsed.difference_update_query(["sslmode", "channel_binding"])

    connect_args: AsyncpgConnectArgs = {}
    if sslmode is not None:
        ssl_arg = _ssl_connect_arg(sslmode)
        if ssl_arg is not None:
            connect_args["ssl"] = ssl_arg
    return parsed.render_as_string(hide_password=False), connect_args


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


# Hosts that can't be what an external MCP client reaches this service on. `0.0.0.0`/`::` are a
# bind address rather than a destination, so they're just as wrong as loopback here.
# `[::1]` is included because pydantic's `HttpUrl.host` keeps IPv6 brackets.
_NON_PUBLIC_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "::"})


class LogLevel(StrEnum):
    """Matches `unique_mcp.logging.configure_logging` accepted names (case-insensitive)."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    app_env: AppEnv = AppEnv.PRODUCTION
    version: str = PKG_VERSION
    port: int = Field(default=9010, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO

    # The externally-reachable URL of this service — used as the OAuth issuer/base URL
    # (discovery metadata, /authorize, /token, and the Backstop login form all hang off it).
    # The local default is only usable in development; `_reject_local_base_url_in_production`
    # below enforces that.
    # Kept as the validated `HttpUrl` rather than a string: `host` and `scheme` are both read
    # downstream (here, and for the login cookie's `Secure` flag in `auth/provider.py`), and one
    # parse serving all of them is why none of those places re-parse it.
    public_base_url: HttpUrl = HttpUrl("http://localhost:9010")

    @model_validator(mode="after")
    def _reject_local_base_url_in_production(self) -> Self:
        """Fail fast when a production deploy never set `PUBLIC_BASE_URL`.

        Left at the default, this service advertises a loopback issuer in its OAuth discovery
        metadata and redirects browsers to a login form on the client's own machine. Nothing
        errors server-side — clients just fail to connect for a reason nothing here reports. So
        it's rejected at startup, the same way a missing encryption key is.
        """
        if self.app_env != AppEnv.PRODUCTION:
            return self
        host = self.public_base_url.host
        assert host is not None, f"validated HttpUrl without a host: {self.public_base_url}"
        if host in _NON_PUBLIC_HOSTS:
            raise ValueError(
                "PUBLIC_BASE_URL must be this service's externally-reachable URL in "
                + f"{AppEnv.PRODUCTION} (got {self.public_base_url}); it is the OAuth issuer "
                + "clients are redirected to"
            )
        return self

    @property
    def issuer(self) -> str:
        """`public_base_url` as a string with no trailing slash, for joining paths onto.

        `HttpUrl` renders a bare origin with a trailing `/`, so interpolating a path straight
        onto it yields `https://host//backstop/login`. The provider builds its login redirect
        that way, so the slash is stripped once here rather than at each call site. Note the
        OAuth discovery document is not this value: the MCP SDK re-parses the issuer into an
        `AnyHttpUrl` and advertises it with the slash restored.
        """
        return str(self.public_base_url).rstrip("/")


class BackstopConfig(BaseSettings):
    """Where to reach the Backstop REST API.

    Credentials are NOT configured here: each connecting MCP client completes the hosted
    login form (username + personal API token), which is verified against Backstop and then
    stored encrypted in Postgres. Tool calls load that per-user credential and send
    `Authorization: Basic ...` + `token: true` to Backstop. See `auth/provider.py`,
    `backstop_client/`, and https://backstopsolutions.elevio.help/en/articles/1018 /
    .../236.

    Also carries the tuning knobs for the shared HTTP client: timeouts, per-user concurrency
    limits, retry behavior for 429s, and default pagination sizes.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="BACKSTOP_")

    base_url: HttpUrlStr = "https://api.backstopsolutions.com"

    # httpx's undocumented default is ~5s; ordinary CRUD calls get a saner explicit timeout.
    default_timeout_seconds: float = Field(default=30.0, gt=0)
    # /reports and /{entity}/{id}/analytics can legitimately take up to ~30s per 500 records.
    reports_timeout_seconds: float = Field(default=120.0, gt=0)

    # Backstop hard-limits each user token to 5 concurrent connections.
    max_concurrent_requests_per_user: int = Field(default=5, ge=1)

    # Retry tuning for 429 (rate-limit) responses.
    max_retry_attempts: int = Field(default=5, ge=1)
    max_retry_wait_ms: int = Field(default=30_000, ge=0)

    # Default page size for `.paginate()` on ordinary CRUD collections.
    default_page_size: int = Field(default=100, ge=1)
    # Default page size for /reports and /analytics pagination; Backstop recommends not
    # exceeding 500 records per report page.
    report_page_size: int = Field(default=500, ge=1, le=500)

    # JSON:API pagination parameter names. Defaults come from the Backstop swagger, which
    # spells the only paginated example as
    # `/quick-search/?...&page[offset]={value4}&page[limit]={value5}`
    # (.docs-local/backstop/backstop-api-swagger.json). Overridable because getting these
    # wrong is silent: Backstop ignores an unknown query param, so `report_page_size` would
    # stop bounding report pages without any error to notice.
    page_limit_param: str = Field(default="page[limit]", min_length=1)
    page_offset_param: str = Field(default="page[offset]", min_length=1)

    # How long a fetched custom-field catalog stays usable before it is re-fetched. Measured
    # against fb-rm-lg-26: 3,274 definitions, 2.77 MiB, 6.15 s per unfiltered walk. Two hours
    # bounds how long a CRM-admin-added field stays invisible; `list_custom_fields(refresh=true)`
    # (and the groups list) force a refetch. Capped at 24 hours. Values above the cap (including
    # the previous documented example of 10080) are clamped so existing deploys still boot.
    custom_field_schema_ttl_minutes: Annotated[
        int, BeforeValidator(_cap_custom_field_schema_ttl_minutes)
    ] = Field(
        default=120,
        ge=1,
        le=_CUSTOM_FIELD_SCHEMA_TTL_MAX_MINUTES,
    )

    # Whether the custom-field catalogs (definitions and groups) are held between calls.
    # On: every party and product read otherwise pays that 6.15 s walk. Cold start
    # and TTL expiry still cost one caller the walk (~12 times a day per process);
    # CachedCatalog's single-flight pin shares it with concurrent callers. After one successful
    # load, a failed refresh re-serves the previous catalog.
    #
    # The held catalog is process-wide, so whichever caller loads it serves every other caller
    # until the TTL expires — which is only sound because the definitions collection is tenant
    # schema, not a per-caller projection. What was checked: `/custom-field-definitions` carries
    # no permission attribute (`fieldClassification`, the only candidate, is null on all 3,274
    # rows), the API publishes no permission, role or field-security endpoint, and Backstop's own
    # per-caller marker — `restricted` on an inline `ResourceRef` — sits on the *value*, which
    # arrives on the caller's own GET, never on the definition. Not proven by a second
    # credential: one narrower user loading the catalog first would make `join_values` skip a
    # definition a broader user can see, logged as `custom_fields.values.definition_missing` and
    # invisible in the response. If that log ever fires for a definition `list_custom_fields`
    # can show, this cache needs a per-caller key.
    #
    # Covers both custom-field catalogs, mirroring `custom_field_schema_ttl_minutes`. The
    # histograms label the two separately (`catalog="custom-field"` and
    # `catalog="custom-field group"`), so if they diverge, splitting this flag is the next step.
    # Set `BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED=false` to turn it off.
    custom_field_schema_cache_enabled: bool = True

    # How long a fetched opportunity-stage vocabulary stays usable. Seven rows on the instance
    # this was built against, and a stage is added about as often as a custom field, so the same
    # one-hour default and 24-hour cap apply. No cache flag: `OpportunityStagesService` does not
    # use `CachedCatalog` and always holds its vocabulary.
    opportunity_stage_ttl_minutes: int = Field(default=60, ge=1, le=24 * 60)

    # How long a fetched activity-tag catalog stays usable before it is re-fetched. Tags change
    # rarely; the default is 24 hours. Capped at 24 hours so a stale catalog cannot sit for days
    # after a CRM admin adds a tag. `list_activity_tags(refresh=true)` forces a refetch when a
    # tag is missing. Distinct from `custom_field_schema_ttl_minutes`: tags are a different
    # collection.
    activity_tag_ttl_minutes: int = Field(default=24 * 60, ge=1, le=24 * 60)

    # Whether the activity-tag catalog is held between calls. Off by default: unlike the
    # custom-field walk, this one has not been measured as expensive enough to justify the
    # staleness. Set `BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED=true` once its histograms say so.
    activity_tag_cache_enabled: bool = False

    # How long a fetched system-user catalog stays usable before it is re-fetched. The roster
    # changes rarely; the default is 24 hours. Capped at 24 hours so a stale catalog cannot sit
    # for days after a colleague is added or disabled. `list_system_users(refresh=true)` forces
    # a refetch when someone is missing.
    system_user_ttl_minutes: int = Field(default=24 * 60, ge=1, le=24 * 60)

    # Whether the system-user catalog is held between calls. Off by default: unlike the
    # custom-field walk, this one has not been measured as expensive enough to justify the
    # staleness. Set `BACKSTOP_SYSTEM_USER_CACHE_ENABLED=true` once its histograms say so.
    system_user_cache_enabled: bool = False

    # Which entity-relationship types mean employment, and which of those mean it has ended,
    # for departed-contact detection (UN-23678). Comma-separated env values. Ids match a type id
    # exactly; markers match case-insensitively as substrings of the type's name.
    #
    # The FORMER half is what actually detects a departure. A tenant models one as a separate
    # relationship type rather than as a date: the instance this was built against carries both
    # `is employee of` and `is a former employee of`, and fills in `endDate` on well under one
    # percent of records. Which is also why the two marker lists must not overlap — matching
    # "employee" cannot tell those two type names apart, so the departure word is the marker.
    #
    # Ids are exact but per-instance (an admin's numeric ids mean nothing on another deployment)
    # and so have no default; `GET /entity-relationship-types` lists the ones a deployment can
    # set, with `entityRestrictions` showing which link people to organizations. Setting a
    # markers env var *replaces* its defaults; setting it empty leaves ids as that bucket's only
    # signal. They live here rather than inside the feature so that every knob a deployment can
    # turn is visible in one place — the detector itself has no built-in vocabulary.
    #
    # `NoDecode` keeps pydantic-settings from JSON-decoding the CSV before our validator runs.
    employment_relationship_type_ids: Annotated[tuple[str, ...], NoDecode] = Field(default=())
    employment_relationship_type_markers: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("employ",)
    )
    former_employment_relationship_type_ids: Annotated[tuple[str, ...], NoDecode] = Field(
        default=()
    )
    former_employment_relationship_type_markers: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("former", "previous", "ex-", "no longer")
    )

    @field_validator(
        "employment_relationship_type_ids",
        "employment_relationship_type_markers",
        "former_employment_relationship_type_ids",
        "former_employment_relationship_type_markers",
        mode="before",
    )
    @classmethod
    def _split_csv_tuple(cls, value: object) -> object:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        if isinstance(value, list):
            items = cast(list[object], value)
            return tuple(str(item).strip() for item in items if str(item).strip())
        return value


class ActivityHistoryConfig(BaseSettings):
    """Tuning knobs for the activity-history feature (meetings/calls/notes/documents + email).

    `page_size` is a PER-STREAM page size: each active stream (up to five — four activity types
    plus email) is fetched with this same `page[limit]`, and the merge step does not cap the
    combined result. A page can therefore return up to `page_size * number of active streams`
    records — a deliberate simplification (UN-23680) rather than a hard total-output cap.

    `gist_chars` is the character budget `extract_gist_from_html` truncates each record's
    body to.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="ACTIVITY_HISTORY_")

    page_size: int = Field(default=10, gt=0)
    gist_chars: int = Field(default=300, gt=0)


class ResolutionConfig(BaseSettings):
    """Tuning knobs for the shared ambiguity policy in `features/resolution.py`.

    `elicit_timeout_seconds` bounds how long a tool waits for the user to pick between
    candidates before degrading to the structured candidate list (policy step 4). It exists
    because `ctx.elicit` has no deadline of its own: an unanswered prompt otherwise blocks the
    tool until the *client* cancels the call, which discards the candidates already fetched and
    returns nothing at all.

    It must stay below the calling client's tool-call deadline — 60s for the Unique chat client
    that prompted this knob — and the margin has to cover the upstream search that runs before
    the prompt. Configurable so that deadline can be matched per deployment without a release.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="RESOLUTION_")

    elicit_timeout_seconds: float = Field(default=45.0, gt=0)


class DatabaseConfig(BaseSettings):
    """Where backstop-mcp stores OAuth clients/tokens and encrypted Backstop credentials.

    Provide either `url` / `DB_URL` (or Helm's `DATABASE_URL` alias) **or** the discrete
    `host`/`name`/`user`/`password` fields. The discrete fields may be `None` when a URL is
    set — `_resolve_connection_url` only requires them when building a DSN from parts.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="DB_")

    url: PostgresDsn | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None
    _connection_url: str = PrivateAttr(default="")
    _connect_args: AsyncpgConnectArgs = PrivateAttr(default_factory=lambda: AsyncpgConnectArgs())

    @model_validator(mode="before")
    @classmethod
    def accept_database_url(cls, data: object) -> object:
        """Accept DATABASE_URL (injected by the base Helm chart) as an alias for DB_URL."""
        if not isinstance(data, dict):
            return data
        values = cast(dict[str, object], data)
        if values.get("url") is None:
            database_url = os.environ.get("DATABASE_URL")
            if database_url:
                return {**values, "url": database_url}
        return values

    @model_validator(mode="after")
    def _resolve_connection_url(self) -> Self:
        if self.url is not None:
            self._connection_url, self._connect_args = normalize_asyncpg_url(str(self.url))
            return self

        missing = [
            name
            for name, val in (
                ("DB_HOST", self.host),
                ("DB_NAME", self.name),
                ("DB_USER", self.user),
                ("DB_PASSWORD", self.password),
            )
            if val is None
        ]
        if missing:
            raise ValueError(f"DB_URL not set; missing required fields: {', '.join(missing)}")

        self._connection_url = URL.create(
            drivername="postgresql+asyncpg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.name,
        ).render_as_string(hide_password=False)
        self._connect_args = AsyncpgConnectArgs()
        return self

    @property
    def connection_url(self) -> str:
        """SQLAlchemy/asyncpg URL after driver rewrite and libpq-param stripping."""
        return self._connection_url

    @property
    def connect_args(self) -> AsyncpgConnectArgs:
        """asyncpg connect args derived from libpq query params (e.g. sslmode)."""
        return self._connect_args


class AuthConfig(BaseSettings):
    """Retention and sweep cadence for the OAuth rows this service issues.

    See `auth/cleanup.py`: without a periodic sweep, `pending_authorizations`,
    `authorization_codes` and — chiefly — `oauth_tokens` grow without bound.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="AUTH_")

    # How long a fully-expired token family is kept. `rotated_from` makes those rows an audit
    # trail of one grant's rotations, so they outlive their usefulness as credentials.
    token_retention_days: int = Field(default=30, ge=1)

    # How long a registered OAuth client with nothing left referencing it is kept. Dynamic client
    # registration is open (RFC 7591), so every client that ever connected — and anyone who
    # merely called /register — leaves an `oauth_clients` row behind. A client in use always has a
    # live token family and so is never reachable by the sweep; this bounds registration spam and
    # clients that registered but never finished a login. Comfortably longer than
    # `BackstopOAuthProvider.PENDING_AUTHORIZATION_TTL`, so a client waiting on its user to fill
    # in the login form can't be swept mid-handshake.
    unused_client_retention_hours: float = Field(default=24.0, gt=0)

    # How often the sweep runs. Rows are unusable the moment they expire, so this bounds only
    # how long dead rows linger — never whether an expired token is accepted.
    cleanup_interval_hours: float = Field(default=6.0, gt=0)

    # Failed-login throttling for the hosted Backstop login form (see `auth/throttle.py`).
    # Without it, `POST /backstop/login` forwards any username/token pair to Backstop, which
    # makes it a credential-testing oracle for anyone who can start an OAuth flow.
    login_max_attempts: int = Field(default=10, ge=1)
    login_attempt_window_minutes: int = Field(default=15, ge=1)

    @property
    def token_retention(self) -> timedelta:
        return timedelta(days=self.token_retention_days)

    @property
    def unused_client_retention(self) -> timedelta:
        return timedelta(hours=self.unused_client_retention_hours)

    @property
    def cleanup_interval(self) -> timedelta:
        return timedelta(hours=self.cleanup_interval_hours)

    @property
    def login_attempt_window(self) -> timedelta:
        return timedelta(minutes=self.login_attempt_window_minutes)


class EncryptionConfig(BaseSettings):
    """Key used to encrypt Backstop credentials (username + personal API token) at rest."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="BACKSTOP_MCP_")

    encryption_key: SecretStr | None = None

    @model_validator(mode="after")
    def _require_encryption_key(self) -> Self:
        if self.encryption_key is None:
            raise ValueError("BACKSTOP_MCP_ENCRYPTION_KEY not set")
        return self
