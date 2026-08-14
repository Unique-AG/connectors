from collections.abc import Awaitable, Callable
from typing import Protocol, cast

import asyncpg
import certifi
import pytest
from asyncpg import connect_utils
from pydantic import ValidationError
from testcontainers.community.postgres import PostgresContainer

from office_mcp.config import (
    AppConfig,
    AppEnv,
    DatabaseConfig,
    LogLevel,
    asyncpg_dsn,
)


# asyncpg ships no type information, so both seams into it are narrowed once here rather than
# leaving every call below unchecked. Same idiom `tests/test_app.py` uses for httpx responses.
class _ConnectionParameters(Protocol):
    """The one field of asyncpg's parsed connection parameters these tests read."""

    @property
    def server_settings(self) -> dict[str, str] | None: ...


class _Connection(Protocol):
    async def fetchval(self, query: str, /) -> object: ...
    async def close(self) -> None: ...


type _ParseResult = tuple[object, _ConnectionParameters]

_parse_connect_dsn_and_args = cast(
    "Callable[..., _ParseResult]",
    connect_utils._parse_connect_dsn_and_args,  # pyright: ignore[reportPrivateUsage]
)
_connect = cast("Callable[[str], Awaitable[_Connection]]", asyncpg.connect)


def _parse_connect_args(dsn: str) -> _ParseResult:
    """Run asyncpg's own connection-string parser over `dsn`.

    This is the parser `asyncpg.connect` runs before it opens a socket, so it answers "what
    would asyncpg make of this string" without needing a server. Called on the private helper
    deliberately: it is the single place asyncpg turns a DSN into connection arguments, and
    going through `asyncpg.connect` would mean an attempted TCP connection per case.
    """
    return _parse_connect_dsn_and_args(
        dsn=dsn,
        host=None,
        port=None,
        user=None,
        password=None,
        passfile=None,
        database=None,
        ssl=None,
        service=None,
        servicefile=None,
        direct_tls=False,
        server_settings=None,
        target_session_attrs="any",
        krbsrvname=None,
        gsslib="gssapi",
    )


def _asyncpg_parses(dsn: str) -> bool:
    """Whether asyncpg's parser accepts `dsn` at all.

    `TypeError` is deliberately *not* caught. It means the call above no longer matches
    asyncpg's signature, and swallowing it would turn every assertion below into "asyncpg
    rejects everything" — which quietly passes the rejection tests and fails the acceptance ones
    for a reason that has nothing to do with the DSNs.
    """
    try:
        _ = _parse_connect_args(dsn)
    except TypeError:
        raise
    except Exception:
        return False
    return True


# Every row of the DSN contract, as (input, expected output). asyncpg is the authority on what
# the output has to look like, and `TestAsyncpgItselfAcceptsWhatWeProduce` below holds each of
# these against asyncpg's own parser rather than against this table alone.
_DSN_MATRIX: list[tuple[str, str]] = [
    # Already the asyncpg spelling — untouched.
    ("postgresql://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
    # SQLAlchemy's driver-qualified form. asyncpg rejects the `+asyncpg` suffix.
    ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
    # libpq's short form, emitted by Heroku/Azure and many operator-generated secrets.
    ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
    # `verify` is libpq's alias for `verify-full`; asyncpg only knows the long spelling.
    (
        "postgresql://u:p@h:5432/db?sslmode=verify",
        "postgresql://u:p@h:5432/db?sslmode=verify-full",
    ),
    # Every other libpq sslmode is a name asyncpg already knows — passed through verbatim.
    ("postgresql://u:p@h:5432/db?sslmode=disable", "postgresql://u:p@h:5432/db?sslmode=disable"),
    ("postgresql://u:p@h:5432/db?sslmode=allow", "postgresql://u:p@h:5432/db?sslmode=allow"),
    ("postgresql://u:p@h:5432/db?sslmode=prefer", "postgresql://u:p@h:5432/db?sslmode=prefer"),
    ("postgresql://u:p@h:5432/db?sslmode=require", "postgresql://u:p@h:5432/db?sslmode=require"),
    # NOT widened to verify-full: verify-ca checks the CA chain but deliberately not the
    # hostname, so promoting it would silently strengthen what the operator asked for.
    (
        "postgresql://u:p@h:5432/db?sslmode=verify-ca",
        "postgresql://u:p@h:5432/db?sslmode=verify-ca",
    ),
    (
        "postgresql://u:p@h:5432/db?sslmode=verify-full",
        "postgresql://u:p@h:5432/db?sslmode=verify-full",
    ),
    # asyncpg has no channel_binding equivalent and does not ignore it either — it forwards the
    # unrecognised key as a server setting, which Postgres then refuses. So it is dropped.
    ("postgresql://u:p@h:5432/db?channel_binding=require", "postgresql://u:p@h:5432/db"),
    (
        "postgresql://u:p@h:5432/db?sslmode=verify&channel_binding=require",
        "postgresql://u:p@h:5432/db?sslmode=verify-full",
    ),
    # A percent-encoded password stays encoded: decoding `p%40ss` to `p@ss` would put a second
    # `@` in the netloc and reparse the host as `ss@h`.
    ("postgresql://u:p%40ss@h:5432/db", "postgresql://u:p%40ss@h:5432/db"),
    ("postgresql://u:p%3Ass%25x@h:5432/db", "postgresql://u:p%3Ass%25x@h:5432/db"),
    # An IPv6 literal keeps its brackets — without them the colons read as a port separator.
    ("postgresql://u:p@[::1]:5432/db", "postgresql://u:p@[::1]:5432/db"),
    (
        "postgresql://u:p@[::1]:5432/db?sslmode=verify",
        "postgresql://u:p@[::1]:5432/db?sslmode=verify-full",
    ),
    # No port at all: not defaulted to 5432 here, so asyncpg applies its own default.
    ("postgresql://u:p@h/db", "postgresql://u:p@h/db"),
    (
        "postgres://u:p%40ss@h/db?sslmode=verify&channel_binding=require",
        "postgresql://u:p%40ss@h/db?sslmode=verify-full",
    ),
]

_DSN_IDS = [dsn_in for dsn_in, _ in _DSN_MATRIX]


class TestAsyncpgDsn:
    @pytest.mark.parametrize(("given", "expected"), _DSN_MATRIX, ids=_DSN_IDS)
    def test_rewrites_to_the_dsn_asyncpg_accepts(self, given: str, expected: str) -> None:
        assert asyncpg_dsn(given) == expected

    def test_rejects_non_postgres_schemes(self) -> None:
        with pytest.raises(ValueError, match="PostgreSQL"):
            asyncpg_dsn("mysql://user:pass@db:3306/office")

    def test_rejects_an_sslmode_that_is_neither_libpqs_nor_asyncpgs(self) -> None:
        """An unknown sslmode is an operator typo. Passing it through would surface as a
        connection error at the first request instead of at startup."""
        with pytest.raises(ValueError, match="sslmode"):
            asyncpg_dsn("postgresql://u:p@h:5432/db?sslmode=verify-everything")


@pytest.fixture
def _sslroot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point asyncpg at a real CA bundle for the duration of one test.

    For `sslmode=verify-ca`/`verify-full` asyncpg loads a root certificate while *parsing*, and
    defaults to `~/.postgresql/root.crt` — which exists on no CI runner and on few laptops. Left
    unset, every verifying DSN in the matrix would look rejected for a reason that has nothing
    to do with the DSN. `PGSSLROOTCERT` is asyncpg's own override for that path.
    """
    monkeypatch.setenv("PGSSLROOTCERT", certifi.where())


class TestAsyncpgItselfAcceptsWhatWeProduce:
    """The matrix above asserts against a table; this asserts against asyncpg.

    Every rewritten DSN must parse, and the rewrites that exist because asyncpg refuses the
    input must be shown to be refusals rather than cosmetic tidying.
    """

    @pytest.mark.parametrize(("given", "expected"), _DSN_MATRIX, ids=_DSN_IDS)
    @pytest.mark.usefixtures("_sslroot")
    def test_asyncpg_parses_every_rewritten_dsn(self, given: str, expected: str) -> None:
        assert _asyncpg_parses(asyncpg_dsn(given))
        assert _asyncpg_parses(expected)

    @pytest.mark.parametrize(
        "rejected",
        [
            # libpq's `verify` alias — the one sslmode spelling asyncpg does not know.
            "postgresql://u:p@h:5432/db?sslmode=verify",
            # SQLAlchemy's driver-qualified scheme.
            "postgresql+asyncpg://u:p@h:5432/db",
        ],
    )
    @pytest.mark.usefixtures("_sslroot")
    def test_asyncpg_rejects_the_raw_form_each_rewrite_exists_for(self, rejected: str) -> None:
        assert not _asyncpg_parses(rejected)
        assert _asyncpg_parses(asyncpg_dsn(rejected))

    def test_channel_binding_survives_parsing_as_a_server_setting(self) -> None:
        """Why `channel_binding` is dropped rather than left alone.

        asyncpg's parser *accepts* it — it does not recognise the key, so it forwards it as a
        server setting in the startup packet, and Postgres then refuses the connection with
        `unrecognized configuration parameter`. A parse check alone would call this DSN fine;
        `TestTheDsnReachesARealPostgres` below holds the same case against a real server.
        """
        _, params = _parse_connect_args(
            "postgresql://u:p@h:5432/db?channel_binding=require",
        )
        assert params.server_settings == {"channel_binding": "require"}

        _, rewritten = _parse_connect_args(
            asyncpg_dsn("postgresql://u:p@h:5432/db?channel_binding=require"),
        )
        assert not rewritten.server_settings


class TestPublicBaseUrl:
    """The OAuth issuer clients get redirected to, so a leftover local default is a dead deploy."""

    def test_the_local_default_is_allowed_outside_production(self) -> None:
        config = AppConfig(app_env=AppEnv.DEVELOPMENT)

        assert config.issuer == "http://localhost:9544"

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:9544",
            "http://127.0.0.1:9544",
            "http://[::1]:9544",
            # A bind address, not somewhere a client can reach this service.
            "http://0.0.0.0:9544",
            "http://[::]:9544",
        ],
    )
    def test_production_rejects_a_url_no_client_can_reach(self, url: str) -> None:
        with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
            AppConfig.model_validate({"app_env": AppEnv.PRODUCTION, "public_base_url": url})

    def test_rejects_malformed_public_base_url(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig.model_validate(
                {"app_env": AppEnv.DEVELOPMENT, "public_base_url": "not-a-url"}
            )

    def test_production_accepts_a_real_public_url(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": AppEnv.PRODUCTION, "public_base_url": "https://office-mcp.example"}
        )

        assert config.issuer == "https://office-mcp.example"

    def test_the_issuer_never_carries_a_trailing_slash(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": AppEnv.PRODUCTION, "public_base_url": "https://office-mcp.example/"}
        )

        assert config.issuer == "https://office-mcp.example"

    def test_the_parsed_url_is_available_for_host_and_scheme_checks(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": AppEnv.PRODUCTION, "public_base_url": "https://office-mcp.example"}
        )

        assert config.public_base_url.scheme == "https"
        assert config.public_base_url.host == "office-mcp.example"

    def test_production_is_the_default_env_so_the_bare_default_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app_env` defaults to production, so an unconfigured deploy fails at startup."""
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

        with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
            AppConfig()


class TestCaseInsensitiveEnumFields:
    """Pydantic's `StrEnum` coercion is case-sensitive, but the canonical spellings
    (`LOG_LEVEL=INFO`, `APP_ENV=Production`) are what operators reach for."""

    def test_log_level_accepts_the_canonical_uppercase_spelling(self) -> None:
        config = AppConfig.model_validate({"app_env": AppEnv.DEVELOPMENT, "log_level": "INFO"})

        assert config.log_level == LogLevel.INFO

    def test_app_env_accepts_mixed_case(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": "Production", "public_base_url": "https://office-mcp.example"}
        )

        assert config.app_env == AppEnv.PRODUCTION


class TestDatabaseConfigDriverDsn:
    """`driver_dsn` is the whole database surface, so every input path is checked to land on it."""

    @pytest.mark.usefixtures("_sslroot")
    def test_db_url_is_rewritten_the_same_way_asyncpg_dsn_rewrites_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("DB_URL", "postgres://user:pass@db:5432/office?sslmode=verify")

        config = DatabaseConfig()

        assert config.driver_dsn == "postgresql://user:pass@db:5432/office?sslmode=verify-full"
        assert _asyncpg_parses(config.driver_dsn)

    def test_accepts_the_database_url_alias_the_base_helm_chart_injects(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DB_URL", raising=False)
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql://user:pass@db:5432/office?sslmode=verify-full",
        )

        config = DatabaseConfig()

        assert config.driver_dsn == "postgresql://user:pass@db:5432/office?sslmode=verify-full"

    def test_builds_a_dsn_from_discrete_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # DATABASE_URL no longer needs to be cleared here: supplying any discrete field makes
        # `accept_database_url` skip the env fallback entirely, regardless of what's ambient.
        monkeypatch.delenv("DB_URL", raising=False)

        config = DatabaseConfig(
            host="db",
            port=5432,
            name="office",
            user="user",
            password="p@ss",
        )

        assert config.driver_dsn == "postgresql://user:p%40ss@db:5432/office"
        assert _asyncpg_parses(config.driver_dsn)

    def test_percent_encodes_every_reserved_character_in_an_assembled_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`@`, `:` and `%` are all delimiters or escapes in userinfo. Left raw, the DSN
        reparses with the wrong host, user or password."""
        monkeypatch.delenv("DB_URL", raising=False)

        config = DatabaseConfig(
            host="db", port=5432, name="office", user="user", password="p@:s%s/x"
        )

        assert config.driver_dsn == "postgresql://user:p%40%3As%25s%2Fx@db:5432/office"
        assert _asyncpg_parses(config.driver_dsn)

    def test_explicit_discrete_fields_beat_a_set_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A DATABASE_URL left over in the ambient environment must not silently override
        explicit constructor arguments — the composition-root contract is that nothing
        downstream re-reads the environment."""
        monkeypatch.delenv("DB_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://envuser:envpass@envhost:5432/envdb")

        config = DatabaseConfig(
            host="explicit",
            port=5432,
            name="office",
            user="user",
            password="p@ss",
        )

        assert config.driver_dsn == "postgresql://user:p%40ss@explicit:5432/office"

    def test_an_explicit_url_argument_also_beats_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://envuser:envpass@envhost:5432/envdb")

        config = DatabaseConfig.model_validate({"url": "postgresql://u:p@explicit:5432/office"})

        assert config.driver_dsn == "postgresql://u:p@explicit:5432/office"

    def test_rejects_a_non_postgres_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_URL", raising=False)

        with pytest.raises(ValidationError):
            DatabaseConfig.model_validate({"url": "mysql://user:pass@db:3306/office"})

    def test_missing_parts_list_all_absent_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_URL", raising=False)

        with pytest.raises(ValidationError, match="DB_HOST"):
            DatabaseConfig()


class TestTheDsnReachesARealPostgres:
    """The matrix proves asyncpg *parses* the DSN; this proves one actually connects.

    Covers the round trip the deleted engine tests covered: container URL in, working connection
    out, no rewriting step in between that only looked right.
    """

    async def test_asyncpg_connects_on_the_dsn_the_config_produced(
        self, postgres_container: PostgresContainer
    ) -> None:
        url = postgres_container.get_connection_url().replace("+psycopg2", "")
        config = DatabaseConfig.model_validate({"url": url})

        assert await _select_one(config.driver_dsn) == 1

    async def test_the_postgres_short_form_reaches_the_same_server(
        self, postgres_container: PostgresContainer
    ) -> None:
        """`postgres://` and `postgresql+asyncpg://` are rewrites, not cosmetic ones: both are
        forms an operator or a Helm chart really supplies, and asyncpg takes neither."""
        url = postgres_container.get_connection_url().replace("+psycopg2", "")

        for supplied in (url.replace("postgresql://", "postgres://", 1), url):
            config = DatabaseConfig.model_validate({"url": supplied})
            assert await _select_one(config.driver_dsn) == 1

    async def test_a_left_in_channel_binding_would_break_the_connection(
        self, postgres_container: PostgresContainer
    ) -> None:
        """The whole reason `channel_binding` is dropped, against a real server.

        asyncpg's parser accepts the raw form (it forwards the unknown key as a server setting),
        so only an actual connection shows the failure — Postgres rejects the startup packet.
        """
        url = postgres_container.get_connection_url().replace("+psycopg2", "")
        raw = f"{url}?channel_binding=require"

        with pytest.raises(asyncpg.PostgresError):
            _ = await _select_one(raw)

        assert await _select_one(asyncpg_dsn(raw)) == 1


async def _select_one(dsn: str) -> object:
    connection = await _connect(dsn)
    try:
        return await connection.fetchval("SELECT 1")
    finally:
        await connection.close()
