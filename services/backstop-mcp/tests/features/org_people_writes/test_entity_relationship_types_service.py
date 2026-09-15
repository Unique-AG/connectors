import inspect
from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.org_people_writes import EntityRelationshipTypesService
from tests.helpers import (
    BASE_URL,
    build_employment_index_factory,
    client_factory,
    credential,
    resource,
)

type ClientBuilder = Callable[[str], BackstopClient]


@pytest.fixture
async def clients() -> AsyncGenerator[ClientBuilder]:
    built: list[BackstopClientFactory] = []

    def make(base_url: str) -> BackstopClient:
        factory = client_factory(base_url)
        built.append(factory)
        return factory.for_credential(credential("ert-bob"))

    yield make
    for factory in built:
        await factory.aclose()


def _service(
    client: BackstopClient,
    *,
    ttl_minutes: int = 60,
    employment_type_ids: Sequence[str] = (),
    employment_markers: Sequence[str] | None = None,
    former_type_ids: Sequence[str] = (),
    former_markers: Sequence[str] | None = None,
) -> EntityRelationshipTypesService:
    return EntityRelationshipTypesService.with_ttl_minutes(
        client=client,
        ttl_minutes=ttl_minutes,
        rules=build_employment_index_factory(
            employment_type_ids=employment_type_ids,
            employment_markers=employment_markers,
            former_type_ids=former_type_ids,
            former_markers=former_markers,
        ).rules,
    )


def _types_response(*rows: tuple[str, str | None]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(type_id, "entity-relationship-types", name=name) for type_id, name in rows
            ],
            "meta": {"totalResourceCount": len(rows)},
            "links": {"next": None},
        },
    )


def _age_past_failure_cooldown(service: EntityRelationshipTypesService) -> None:
    past = datetime.now(UTC) - timedelta(minutes=90)
    service._cooldown.mark(past)  # pyright: ignore[reportPrivateUsage]


class TestResolvesEmploymentTypeFromCatalog:
    @pytest.mark.asyncio
    @respx.mock
    async def test_resolves_by_marker_to_whatever_id_the_catalog_used(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ert-by-marker"
        catalog_id = "ert-current-from-mock"
        route = respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(
                (catalog_id, "is employee of"),
                ("ert-former", "is a former employee of"),
                ("ert-portal", "has portal access to"),
            )
        )

        resolved = await _service(clients(base_url)).get_employment_type()

        assert route.calls.last.request.url.params["page[limit]"] == "100"
        assert resolved.id == catalog_id
        assert resolved.name == "is employee of"

    def test_service_source_does_not_hardcode_a_tenant_type_id(self) -> None:
        source = Path(inspect.getfile(EntityRelationshipTypesService)).read_text()
        assert "456439" not in source

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_types_are_an_error_listing_options(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ert-ambiguous"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(
                ("ert-a", "is employee of"),
                ("ert-b", "is employee of (mirror)"),
                ("ert-portal", "has portal access to"),
            )
        )

        with pytest.raises(ToolError, match="ambiguous") as raised:
            await _service(clients(base_url)).get_employment_type()

        message = str(raised.value)
        assert "is employee of (ert-a)" in message
        assert "is employee of (mirror) (ert-b)" in message
        assert "has portal access to" in message
        assert "Available types:" in message

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_match_lists_available_names(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ert-none"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(
                ("ert-portal", "has portal access to"),
                ("ert-owns", "owns account"),
            )
        )

        with pytest.raises(ToolError, match="Available types:") as raised:
            await _service(clients(base_url)).get_employment_type()

        message = str(raised.value)
        assert "has portal access to" in message
        assert "owns account" in message
        assert "No employment entity-relationship type matched" in message

    @pytest.mark.asyncio
    @respx.mock
    async def test_former_types_are_excluded_even_when_they_contain_employ(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ert-former-excluded"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(
                ("ert-current", "is employee of"),
                ("ert-former", "is a former employee of"),
            )
        )

        resolved = await _service(clients(base_url)).get_employment_type()

        assert resolved.id == "ert-current"
        assert resolved.name == "is employee of"

    @pytest.mark.asyncio
    @respx.mock
    async def test_only_a_former_employ_name_is_no_match(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ert-former-only"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(("ert-former", "is a former employee of"))
        )

        with pytest.raises(ToolError, match="Available types: is a former employee of"):
            await _service(clients(base_url)).get_employment_type()

    @pytest.mark.asyncio
    @respx.mock
    async def test_configured_ids_win_when_set(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ert-configured-ids"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(
                ("chosen-id", "Works At"),
                ("ert-employ", "is employee of"),
            )
        )

        resolved = await _service(
            clients(base_url), employment_type_ids=("chosen-id",)
        ).get_employment_type()

        assert resolved.id == "chosen-id"
        assert resolved.name == "Works At"

    @pytest.mark.asyncio
    @respx.mock
    async def test_configured_former_id_is_dropped_so_the_current_id_wins(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ert-configured-former-id"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(
                ("chosen-id", "Works At"),
                ("former-id", "Placement Ended"),
            )
        )

        resolved = await _service(
            clients(base_url),
            employment_type_ids=("chosen-id", "former-id"),
            former_type_ids=("former-id",),
        ).get_employment_type()

        assert resolved.id == "chosen-id"

    @pytest.mark.asyncio
    @respx.mock
    async def test_only_a_configured_former_id_is_no_match(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ert-configured-former-only"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(("former-id", "Placement Ended"))
        )

        with pytest.raises(ToolError, match="Available types: Placement Ended"):
            await _service(
                clients(base_url),
                employment_type_ids=("former-id",),
                former_type_ids=("former-id",),
            ).get_employment_type()


class TestFetchingTheCatalog:
    @pytest.mark.asyncio
    @respx.mock
    async def test_a_row_without_a_name_is_dropped(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ert-unnamed"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            return_value=_types_response(
                ("ert-current", "is employee of"),
                ("ert-nameless", None),
            )
        )

        catalog = await _service(clients(base_url)).get_catalog()

        assert list(catalog) == ["ert-current"]


class TestFailureCooldown:
    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_fetch_propagates(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ert-cold-failure"
        respx.get(f"{base_url}/entity-relationship-types").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await _service(clients(base_url)).get_catalog()

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failure_inside_the_cooldown_reraises_without_a_second_request(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ert-cooldown"
        service = _service(clients(base_url))
        route = respx.get(f"{base_url}/entity-relationship-types").mock(
            side_effect=[
                httpx.ConnectError("backstop down"),
                _types_response(("ert-current", "is employee of")),
            ]
        )

        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()
        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()

        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failure_past_the_cooldown_is_retried(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ert-cooldown-expired"
        service = _service(clients(base_url))
        route = respx.get(f"{base_url}/entity-relationship-types").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()
        _age_past_failure_cooldown(service)
        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()

        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_success_after_a_failure_clears_the_failure(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ert-failure-then-success"
        service = _service(clients(base_url))
        route = respx.get(f"{base_url}/entity-relationship-types").mock(
            side_effect=[
                httpx.ConnectError("backstop down"),
                _types_response(("ert-current", "is employee of")),
            ]
        )

        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()
        _age_past_failure_cooldown(service)
        catalog = await service.get_catalog()

        assert route.call_count == 2
        assert catalog["ert-current"].name == "is employee of"
        assert service._failure is None  # pyright: ignore[reportPrivateUsage]
        assert service._cooldown.marked_at is None  # pyright: ignore[reportPrivateUsage]
