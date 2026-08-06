"""The composition root, exercised as a real ASGI app.

Everything else in this suite builds its collaborators the way `create_app` does; nothing was
testing `create_app` itself, which is where the wiring lives that is easiest to get wrong — the
`attach_auth` cycle, the nested lifespans, middleware registration, the route table.

These tests drive the app through Starlette's `TestClient` so the lifespan actually runs.
"""

import base64
import dataclasses
import os
from collections.abc import Iterator
from typing import Protocol, cast

import pytest
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from backstop_mcp.app import create_app, retry_settings, transport_settings
from backstop_mcp.coerce import as_clean_str, as_object_dict
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
        "config": AppConfig(public_base_url="https://backstop-mcp.example"),
        "backstop_config": BackstopConfig(base_url=_BASE_URL),
        "database_config": DatabaseConfig(url=url),
        "encryption_config": EncryptionConfig(
            encryption_key=base64.b64encode(os.urandom(32)).decode()  # pyright: ignore[reportArgumentType]
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
        self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`attach_auth` must have run: without it `for_current_caller` asserts instead of working.

        The provider needs the client factory (to verify credentials at login) and the factory
        needs the provider (for the token-revocation hook), so this is the one step in the graph
        that can't be expressed by constructor order alone. If the cycle were open,
        `for_current_caller` would raise an `AssertionError` from the factory itself rather than
        reaching the credential lookup that raises `NotConnectedError` below.
        """
        _ = app_client  # the app is built and started by the fixture
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

    def test_the_departed_detector_owns_the_employment_types_create_app_was_given(
        self, postgres_container: PostgresContainer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`get_person` used to build `BackstopConfig()` itself, discarding what was injected.

        Same failure as `test_the_factory_owns_the_settings_create_app_was_given`, and just as
        silent: a tenant's configured relationship types would be ignored while the env-parsed
        defaults quietly took over. The env var is set to something else entirely so a re-read
        would produce a visibly different answer.
        """
        monkeypatch.setenv("BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "from the environment")
        monkeypatch.setenv(
            "BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "from the environment"
        )
        configs = {
            **_configs(postgres_container),
            "backstop_config": BackstopConfig(
                base_url=_BASE_URL,
                employment_relationship_type_ids=("ert-9",),
                employment_relationship_type_markers=("placement at",),
                former_employment_relationship_type_ids=("ert-10",),
                former_employment_relationship_type_markers=("placement ended",),
            ),
        }
        app = create_app(**configs)  # pyright: ignore[reportArgumentType]

        with TestClient(app):
            rules = get_services().employment_index_factory.rules

        assert rules.employment.type_ids == frozenset({"ert-9"})
        assert rules.employment.name_markers == frozenset({"placement at"})
        assert rules.former.type_ids == frozenset({"ert-10"})
        assert rules.former.name_markers == frozenset({"placement ended"})

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

        checks = as_object_dict(body["checks"])
        assert checks is not None
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
        issuer = as_clean_str(response.json()["issuer"])
        assert issuer is not None
        assert issuer.rstrip("/") == "https://backstop-mcp.example"


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
        for field in dataclasses.fields(settings):
            assert getattr(settings, field.name) == getattr(config, field.name), field.name

    def test_retry_settings_carry_the_configured_values(self) -> None:
        """Checked by hand because these two are the only renamed pair."""
        config = BackstopConfig(max_retry_attempts=2, max_retry_wait_ms=5_000)

        settings = retry_settings(config)

        assert settings.max_attempts == config.max_retry_attempts
        assert settings.max_wait_ms == config.max_retry_wait_ms

    def test_the_transport_is_not_handed_the_service_account(self) -> None:
        """The knobs it has no business seeing must not have leaked in with the rest."""
        field_names = {
            field.name for field in dataclasses.fields(transport_settings(BackstopConfig()))
        }

        assert not field_names & {
            "service_username",
            "service_api_token",
            "custom_field_overrides",
            "custom_field_schema_ttl_minutes",
        }
