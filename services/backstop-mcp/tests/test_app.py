"""The composition root, exercised as a real ASGI app.

Everything else in this suite builds its collaborators the way `create_app` does; nothing was
testing `create_app` itself, which is where the wiring lives that is easiest to get wrong — the
`attach_auth` cycle, the lifespan, middleware registration, the route table.

These tests drive the app through Starlette's `TestClient` so the lifespan actually runs.
"""

from collections.abc import Iterator
from typing import Protocol, cast

import pytest
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from backstop_mcp.app import create_app
from backstop_mcp.backstop_client.client import SYSTEM_INFO_PATH
from backstop_mcp.config import BackstopConfig
from backstop_mcp.dependencies import (
    get_backstop_client_factory,
    retry_settings,
    transport_settings,
)
from backstop_mcp.features.activity_history import get_activity_history_settings
from backstop_mcp.features.auth import NotConnectedError
from backstop_mcp.features.custom_fields import get_custom_fields_service
from backstop_mcp.features.data_hygiene import get_employment_index_factory
from backstop_mcp.features.opportunities import get_opportunity_stages_service_factory
from backstop_mcp.server.tools import TOOLS

_BASE_URL = "https://api.backstopsolutions.com"


def _as_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


# `starlette.testclient` returns httpx responses that this repo's strict type-checking sees as
# partially unknown. Narrowed once here, the same way `features/resolution.py` narrows FastMCP's
# request context, so every assertion below is checked rather than silently `Any`.
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


def _set_app_env(monkeypatch: pytest.MonkeyPatch, postgres: PostgresContainer) -> None:
    url = postgres.get_connection_url().replace("+psycopg2", "")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://backstop-mcp.example")
    monkeypatch.setenv("BACKSTOP_BASE_URL", _BASE_URL)
    monkeypatch.setenv("DB_URL", url)
    monkeypatch.setenv("BACKSTOP_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def app_client(
    postgres_container: PostgresContainer, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """The real app, with its lifespan run."""
    _set_app_env(monkeypatch, postgres_container)
    app = create_app()
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
        reaching the credential lookup that raises `NotConnectedError` below. That lookup is
        lazy — the client is a singleton holding only a session provider — so it takes a
        request to reach it, and it raises before any HTTP call is attempted.

        Deliberately built with `create_app` rather than taking `app_client`: `TestClient` runs
        the lifespan on its own portal thread and loop, and `cleanup_lifespan`'s sweep-on-start
        immediately queries the database, binding the engine's asyncpg pool to that loop. The
        credential lookup below runs on pytest-asyncio's function-scoped loop, so it would block
        forever waiting to check out a connection owned by the other one. `create_app` is what
        closes the cycle, so no running server is needed to assert that it did.
        """
        _set_app_env(monkeypatch, postgres_container)
        _ = create_app()
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
            await (
                get_backstop_client_factory()
                .for_current_caller()
                .raw_request("GET", SYSTEM_INFO_PATH)
            )

    def test_the_factory_owns_the_settings_create_app_was_given(
        self, app_client: TestClient
    ) -> None:
        """A second `BackstopConfig()` read from the environment would silently ignore the knobs."""
        _ = app_client
        assert get_backstop_client_factory().settings.base_url == _BASE_URL

    def test_services_carry_the_configured_activity_history_settings(
        self, postgres_container: PostgresContainer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same failure shape as the transport settings above: a re-read would silently win."""
        _set_app_env(monkeypatch, postgres_container)
        monkeypatch.setenv("ACTIVITY_HISTORY_PAGE_SIZE", "25")
        monkeypatch.setenv("ACTIVITY_HISTORY_GIST_CHARS", "500")
        app = create_app()

        with TestClient(app):
            settings = get_activity_history_settings()

        assert settings.page_size == 25
        assert settings.gist_max_chars == 500

    def test_the_departed_detector_owns_the_employment_types_create_app_was_given(
        self, postgres_container: PostgresContainer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cached BackstopConfig provider is the one env read; a later change must not win.

        `get_person` used to build `BackstopConfig()` itself. The provider is now the env read,
        so the values set before `create_app` are what the detector owns — a decoy set afterwards
        must not change them.
        """
        _set_app_env(monkeypatch, postgres_container)
        monkeypatch.setenv("BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_IDS", "ert-9")
        monkeypatch.setenv("BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "placement at")
        monkeypatch.setenv("BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_IDS", "ert-10")
        monkeypatch.setenv(
            "BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "placement ended"
        )
        app = create_app()

        with TestClient(app):
            rules = get_employment_index_factory().rules

        monkeypatch.setenv("BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "from the environment")
        assert rules.employment.type_ids == frozenset({"ert-9"})
        assert rules.employment.name_markers == frozenset({"placement at"})
        assert rules.former.type_ids == frozenset({"ert-10"})
        assert rules.former.name_markers == frozenset({"placement ended"})

    def test_services_are_installed_for_tools_to_reach(self, app_client: TestClient) -> None:
        _ = app_client
        assert get_custom_fields_service() is not None
        assert get_backstop_client_factory() is not None
        assert get_opportunity_stages_service_factory is not None

    def test_lifespan_teardown_releases_the_services(
        self, postgres_container: PostgresContainer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Teardown must cache_clear: two sequential `create_app()` + `TestClient` must succeed.

        Two apps in sequence is what the test suite itself does, and what a reload does.
        """
        _set_app_env(monkeypatch, postgres_container)
        for _ in range(2):
            app = create_app()
            with TestClient(app):
                assert get_backstop_client_factory() is not None


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
        """Postgres is reachable here, so the app is ready."""
        response = _get(app_client, "/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert _checks(body) == {"database": True}

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
    def test_ready_is_503_when_postgres_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://backstop-mcp.example")
        monkeypatch.setenv("DB_URL", "postgresql://user:pass@127.0.0.1:1/nope")
        monkeypatch.setenv("BACKSTOP_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        app = create_app()
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

    def test_every_registered_tool_has_a_distinct_name(self) -> None:
        """`create_app` registers by iterating TOOLS, so a duplicate name would shadow."""
        names = [fn.__name__ for fn in TOOLS]

        assert len(names) == len(set(names))
        assert names


class TestConfigTranslation:
    """`transport_settings` / `retry_settings` map a `config` shape onto a transport one.

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
        """Checked by hand: `max_retry_wait_ms` is renamed to `max_wait_ms` on the domain type."""
        config = BackstopConfig(max_retry_attempts=2, max_retry_wait_ms=5_000)

        settings = retry_settings(config)

        assert settings.max_attempts == config.max_retry_attempts
        assert settings.max_wait_ms == config.max_retry_wait_ms

    def test_the_transport_is_not_handed_feature_ttl_knobs(self) -> None:
        """The knobs it has no business seeing must not have leaked in with the rest."""
        field_names = set(type(transport_settings(BackstopConfig())).model_fields)

        assert not field_names & {
            "activity_tag_ttl_minutes",
            "custom_field_schema_ttl_minutes",
            "opportunity_stage_ttl_minutes",
            "system_user_ttl_minutes",
        }
