"""The composition root, exercised as a real ASGI app.

Everything else in this suite builds its collaborators the way `create_app` does; nothing was
testing `create_app` itself, which is where the wiring lives that is easiest to get wrong — the
`attach_auth` cycle, the nested lifespans, middleware registration, the route table.

These tests drive the app through Starlette's `TestClient` so the lifespan actually runs.
"""

from collections.abc import Iterator
from typing import Protocol, cast

import pytest
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from backstop_mcp.app import create_app, retry_settings, transport_settings
from backstop_mcp.config import (
    AppConfig,
    AuthConfig,
    BackstopConfig,
    DatabaseConfig,
    EncryptionConfig,
)
from backstop_mcp.features.auth.context import NotConnectedError
from backstop_mcp.server.runtime import get_services
from backstop_mcp.server.tools.registry import TOOLS

_BASE_URL = "https://api.backstopsolutions.com"


def _as_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


# `starlette.testclient` returns httpx responses that this repo's strict type-checking sees as
# partially unknown. Narrowed once here, so every assertion below is checked rather than
# silently `Any`.
class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def text(self) -> str: ...
    def json(self) -> dict[str, object]: ...


def _get(client: TestClient, path: str) -> _HttpResponse:
    return cast("_HttpResponse", client.get(path))  # pyright: ignore[reportUnknownMemberType]


def _checks(body: dict[str, object]) -> dict[str, object]:
    """The `checks` sub-object of a `/ready` body, narrowed for assertion."""
    checks = body["checks"]
    assert isinstance(checks, dict), f"expected a checks object, got {checks!r}"
    return cast("dict[str, object]", checks)


def _post_json(
    client: TestClient, path: str, body: dict[str, object], *, headers: dict[str, str]
) -> _HttpResponse:
    return cast(
        "_HttpResponse",
        client.post(path, json=body, headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )


def _configs(postgres: PostgresContainer) -> dict[str, object]:
    url = postgres.get_connection_url().replace("+psycopg2", "")
    return {
        "config": AppConfig.model_validate({"public_base_url": "https://backstop-mcp.example"}),
        "backstop_config": BackstopConfig(base_url=_BASE_URL),
        "database_config": DatabaseConfig.model_validate({"url": url}),
        "encryption_config": EncryptionConfig(
            encryption_key=Fernet.generate_key().decode()  # pyright: ignore[reportArgumentType]
        ),
        "auth_config": AuthConfig(),
    }


@pytest.fixture
def app_client(postgres_container: PostgresContainer) -> Iterator[TestClient]:
    """The real app, with its lifespan run.

    No `BACKSTOP_SERVICE_USERNAME` is configured, so the startup schema warm short-circuits
    without touching Backstop — see `custom_fields/warmup.py`.
    """
    app = create_app(**_configs(postgres_container))  # pyright: ignore[reportArgumentType]
    with TestClient(app) as client:
        yield client


class TestWiring:
    @pytest.mark.asyncio
    async def test_the_auth_cycle_is_closed(
        self, postgres_container: PostgresContainer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`attach_auth` must have run: without it `for_current_caller` asserts instead of working.

        The provider needs the client factory (to verify credentials at login) and the factory
        needs the provider (for the token-revocation hook), so this is the one step in the graph
        that can't be expressed by constructor order alone. If the cycle were open,
        `for_current_caller` would raise an `AssertionError` from the factory itself rather than
        reaching the credential lookup that raises `NotConnectedError` below.

        Deliberately built with `create_app` rather than taking `app_client`: `TestClient` runs
        the lifespan on its own portal thread and loop, and `cleanup_lifespan`'s sweep-on-start
        immediately queries the database, binding the engine's asyncpg pool to that loop. The
        credential lookup below runs on pytest-asyncio's function-scoped loop, so it would block
        forever waiting to check out a connection owned by the other one. `create_app` is what
        closes the cycle, so no running server is needed to assert that it did.
        """
        _ = create_app(**_configs(postgres_container))  # pyright: ignore[reportArgumentType]
        monkeypatch.setattr(
            "backstop_mcp.features.auth.context.get_access_token",
            lambda: AccessToken(
                token="access-token",
                client_id="client-1",
                scopes=[],
                subject="user-never-connected",
            ),
        )

        with pytest.raises(NotConnectedError):
            await get_services().backstop.for_current_caller()

    def test_the_factory_owns_the_settings_create_app_was_given(
        self, app_client: TestClient
    ) -> None:
        """A second `BackstopConfig()` read from the environment would silently ignore the knobs."""
        _ = app_client
        assert get_services().backstop.settings.base_url == _BASE_URL

    def test_services_are_installed_for_tools_to_reach(self, app_client: TestClient) -> None:
        _ = app_client
        services = get_services()
        assert services.custom_fields is not None
        assert services.backstop is not None

    def test_lifespan_teardown_releases_the_services(
        self, postgres_container: PostgresContainer
    ) -> None:
        """`configure_services` asserts on a second install, so teardown must actually reset.

        Two apps in sequence is what the test suite itself does, and what a reload does.
        """
        for _ in range(2):
            app = create_app(**_configs(postgres_container))  # pyright: ignore[reportArgumentType]
            with TestClient(app):
                assert get_services().backstop is not None


class TestRoutes:
    def test_health_is_unauthenticated(self, app_client: TestClient) -> None:
        response = _get(app_client, "/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_probe_is_process_up(self, app_client: TestClient) -> None:
        """`setup_ops` `/probe` is liveness-style; Postgres readiness lives on `/ready`."""
        response = _get(app_client, "/probe")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_ready_reports_the_checks_it_ran(self, app_client: TestClient) -> None:
        """Postgres is reachable here, and the schema is absent — ready, but honest about it."""
        response = _get(app_client, "/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"

        checks = _checks(body)
        assert checks["database"] is True
        # No service account and no snapshot row, so the glossary legitimately hasn't loaded —
        # and that must not gate readiness.
        assert checks["custom_field_schema"] is False

    def test_metrics_is_served(self, app_client: TestClient) -> None:
        response = _get(app_client, "/metrics")

        assert response.status_code == 200

    def test_the_login_form_is_mounted_at_the_providers_path(self, app_client: TestClient) -> None:
        """The route is registered from `auth_provider.login_path`, so the two can't disagree."""
        response = _get(app_client, "/backstop/login?request_id=nonexistent")

        # Reached the handler (which rejects the unknown request_id) rather than 404ing.
        assert response.status_code == 400
        assert "invalid or has expired" in response.text

    def test_oauth_metadata_advertises_this_service_as_the_issuer(
        self, app_client: TestClient
    ) -> None:
        response = _get(app_client, "/.well-known/oauth-authorization-server")

        assert response.status_code == 200
        issuer = _as_str(response.json()["issuer"])
        assert issuer is not None
        # The SDK models the issuer as `AnyHttpUrl`, which renders a bare origin with a trailing
        # slash (and itself strips it again to build the authorize/token URLs). What this asserts
        # is that the advertised issuer is our configured public URL rather than localhost.
        assert issuer.rstrip("/") == "https://backstop-mcp.example"


class TestReadyReportsDatabaseUnreachable:
    def test_ready_is_503_when_postgres_is_unreachable(self) -> None:
        app = create_app(
            config=AppConfig.model_validate({"public_base_url": "https://backstop-mcp.example"}),
            database_config=DatabaseConfig.model_validate(
                {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
            ),
            encryption_config=EncryptionConfig(
                encryption_key=Fernet.generate_key().decode()  # pyright: ignore[reportArgumentType]
            ),
        )
        with TestClient(app) as client:
            response = _get(client, "/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        assert _checks(body)["database"] is False


class TestToolRegistration:
    def test_mcp_endpoint_requires_authentication(self, app_client: TestClient) -> None:
        """Every tool is behind the OAuth provider — an unauthenticated call must not reach one."""
        response = _post_json(
            app_client,
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )

        assert response.status_code == 401

    def test_no_tools_are_registered_yet(self) -> None:
        """`TOOLS` is empty until the first tool lands in a later PR."""
        assert TOOLS == ()


class TestConfigTranslation:
    """`create_app` is the only place a `config` shape becomes a transport one.

    A field that stops being propagated here fails silently — the transport would just use the
    dataclass value it was constructed with — so the mapping is asserted rather than eyeballed.
    """

    def test_every_transport_setting_carries_the_configured_value(self) -> None:
        config = BackstopConfig(
            base_url="https://tenant.backstopsolutions.com",
            default_timeout_seconds=11.0,
            reports_timeout_seconds=222.0,
            max_concurrent_requests_per_user=3,
            default_page_size=33,
            report_page_size=444,
            page_limit_param="limit",
            page_offset_param="offset",
        )

        settings = transport_settings(config)

        # Every field of the settings type is named after the config field it comes from, so the
        # whole mapping can be checked at once — and a newly-added field is covered automatically.
        for name in type(settings).model_fields:
            assert getattr(settings, name) == getattr(config, name), name

    def test_retry_settings_carry_the_configured_values(self) -> None:
        """Checked by hand because these two are the only renamed pair."""
        config = BackstopConfig(max_retry_attempts=2, max_retry_wait_ms=5_000)

        settings = retry_settings(config)

        assert settings.max_attempts == config.max_retry_attempts
        assert settings.max_wait_ms == config.max_retry_wait_ms

    def test_the_transport_is_not_handed_the_service_account(self) -> None:
        """The knobs it has no business seeing must not have leaked in with the rest."""
        field_names = set(type(transport_settings(BackstopConfig())).model_fields)

        assert not field_names & {
            "service_username",
            "service_api_token",
            "custom_field_overrides",
            "custom_field_schema_ttl_minutes",
        }
