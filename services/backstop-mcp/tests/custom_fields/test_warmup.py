import asyncio

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.config import BackstopConfig
from backstop_mcp.custom_fields import create_custom_fields_service
from backstop_mcp.custom_fields.warmup import warm_custom_field_schema, warmup_lifespan
from tests.party_resolver.helpers import resource

type DatabaseFixture = tuple[AsyncEngine, AsyncSession | async_sessionmaker[AsyncSession]]

WARMUP_BASE_URL = "https://example.backstopsolutions.com/warmup"


def _definitions_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(
                    "700",
                    "custom-field-definitions",
                    name="Investor Status",
                    entityType="Organization",
                    fieldType="text",
                    isTimeSeries=False,
                )
            ],
            "links": {"next": None},
        },
    )


class TestWarmCustomFieldSchema:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_with_service_account(
        self, db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
    ) -> None:
        _, factory = db
        base_url = f"{WARMUP_BASE_URL}/fetches"
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=_definitions_response()
        )

        await warm_custom_field_schema(
            service,
            BackstopConfig(
                base_url=base_url,
                service_username="svc-bot",
                service_api_token=SecretStr("svc-token"),
            ),
        )

        assert route.call_count == 1
        assert [d.display_name for d in service.definitions_for("organizations")] == [
            "Investor Status"
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_without_service_account(
        self, db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
    ) -> None:
        _, factory = db
        base_url = f"{WARMUP_BASE_URL}/skips"
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=_definitions_response()
        )

        await warm_custom_field_schema(service, BackstopConfig(base_url=base_url))

        assert route.call_count == 0
        assert service.definitions_for("organizations") == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_swallows_backstop_failure(
        self, db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
    ) -> None:
        """A Backstop outage at boot must not propagate — the app still has to start."""
        _, factory = db
        base_url = f"{WARMUP_BASE_URL}/outage"
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        await warm_custom_field_schema(
            service,
            BackstopConfig(
                base_url=base_url,
                service_username="svc-bot",
                service_api_token=SecretStr("svc-token"),
            ),
        )

        assert service.definitions_for("organizations") == []


class TestWarmupLifespan:
    @pytest.mark.asyncio
    @respx.mock
    async def test_startup_does_not_wait_but_warming_completes(
        self, db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
    ) -> None:
        _, factory = db
        base_url = f"{WARMUP_BASE_URL}/lifespan"
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=_definitions_response()
        )
        config = BackstopConfig(
            base_url=base_url,
            service_username="svc-bot",
            service_api_token=SecretStr("svc-token"),
        )

        async with warmup_lifespan(service, config):
            # Startup handed control back before the fetch could even be issued.
            assert route.call_count == 0
            async with asyncio.timeout(10):
                while not service.definitions_for("organizations"):
                    await asyncio.sleep(0.01)

        assert route.call_count == 1
        assert [d.display_name for d in service.definitions_for("organizations")] == [
            "Investor Status"
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_immediate_shutdown_cancels_warming_cleanly(
        self, db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
    ) -> None:
        """Shutting down before warming finishes must not raise or leave a pending task."""
        _, factory = db
        base_url = f"{WARMUP_BASE_URL}/lifespan-cancel"
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=_definitions_response()
        )
        config = BackstopConfig(
            base_url=base_url,
            service_username="svc-bot",
            service_api_token=SecretStr("svc-token"),
        )

        async with warmup_lifespan(service, config):
            pass

        assert route.call_count == 0
        assert service.definitions_for("organizations") == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_shutdown_survives_failing_warmup(
        self, db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
    ) -> None:
        _, factory = db
        base_url = f"{WARMUP_BASE_URL}/lifespan-fail"
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )
        config = BackstopConfig(
            base_url=base_url,
            service_username="svc-bot",
            service_api_token=SecretStr("svc-token"),
        )

        async with warmup_lifespan(service, config):
            async with asyncio.timeout(10):
                while route.call_count == 0:
                    await asyncio.sleep(0.01)

        assert service.definitions_for("organizations") == []
