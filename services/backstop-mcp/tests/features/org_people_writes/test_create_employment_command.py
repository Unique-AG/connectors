"""`CreateEmploymentCommand`: resource-id attributes, catalog type, no write on error."""

import inspect
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    CreatedEmploymentResponse,
    CreateEmploymentCommand,
    EntityRelationshipTypesService,
    get_create_employment_command_factory,
)
from tests.helpers import (
    BASE_URL,
    build_employment_index_factory,
    client_factory,
    credential,
    recorded_json_bodies,
    resource,
)
from tests.server.tools.helpers import object_dict

_PERSON_ID = "p1"
_ORG_ID = "o1"
_REL_ID = "127921501"
_START = date(2026, 1, 15)
_CATALOG_ID = "ert-current-from-mock"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> CreateEmploymentCommand:
    return get_create_employment_command_factory(
        client,
        entity_relationship_types_service=EntityRelationshipTypesService.with_ttl_minutes(
            client=client,
            ttl_minutes=60,
            rules=build_employment_index_factory().rules,
        ),
    )


def _data(body: dict[str, object]) -> dict[str, object]:
    return object_dict(body["data"])


def _attributes(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["attributes"])


def _relationships(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["relationships"])


def _types_catalog(*rows: tuple[str, str | None]) -> httpx.Response:
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


def _current_catalog() -> httpx.Response:
    return _types_catalog(
        (_CATALOG_ID, "is employee of"),
        ("ert-former", "is a former employee of"),
        ("ert-portal", "has portal access to"),
    )


def _relationship_document(*, status: int = 200, start_date: str | None = None) -> httpx.Response:
    attributes: dict[str, object] = {}
    if start_date is not None:
        attributes["startDate"] = start_date
    return httpx.Response(
        status,
        json={
            "data": {
                "id": _REL_ID,
                "type": "entity-relationships",
                "attributes": attributes,
            }
        },
    )


def _mock_catalog(response: httpx.Response | None = None) -> respx.Route:
    return respx.get(f"{BASE_URL}/entity-relationship-types").mock(
        return_value=response if response is not None else _current_catalog()
    )


async def _run(
    client: BackstopClient, *, person_search_type: str = "people"
) -> CreatedEmploymentResponse:
    result = await make_command(client).run(
        person_id=_PERSON_ID,
        person_search_type=person_search_type,
        organization_id=_ORG_ID,
        start_date=_START,
    )
    assert isinstance(result, CreatedEmploymentResponse)
    return result


class TestCreateEmploymentCommand:
    @respx.mock
    @pytest.mark.parametrize("person_search_type", ["people", "contacts", "employees"])
    async def test_create_employment_sends_entities_as_resource_id_attributes(
        self, client: BackstopClient, person_search_type: str
    ) -> None:
        _mock_catalog()
        route = respx.post(f"{BASE_URL}/entity-relationships").mock(
            return_value=_relationship_document(status=201, start_date=_START.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(start_date=_START.isoformat())
        )

        await _run(client, person_search_type=person_search_type)

        body = recorded_json_bodies(route)[0]
        attributes = _attributes(body)
        relationships = _relationships(body)
        assert object_dict(attributes["sourceEntity"]) == {
            "resourceId": _PERSON_ID,
            "resourceType": person_search_type,
        }
        assert object_dict(attributes["destinationEntity"]) == {
            "resourceId": _ORG_ID,
            "resourceType": "organizations",
        }
        assert "entityRelationshipType" not in attributes
        assert "sourceEntity" not in relationships
        assert "destinationEntity" not in relationships
        type_data = object_dict(object_dict(relationships["entityRelationshipType"])["data"])
        assert type_data == {"type": "entity-relationship-types", "id": _CATALOG_ID}
        assert "resourceId" not in type_data
        assert "resourceType" not in type_data

    @respx.mock
    async def test_start_date_is_sent_as_start_date(self, client: BackstopClient) -> None:
        _mock_catalog()
        route = respx.post(f"{BASE_URL}/entity-relationships").mock(
            return_value=_relationship_document(status=201, start_date=_START.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(start_date=_START.isoformat())
        )

        await _run(client)

        assert _attributes(recorded_json_bodies(route)[0])["startDate"] == _START.isoformat()

    @respx.mock
    async def test_employment_type_is_resolved_from_the_catalog_not_hardcoded(
        self, client: BackstopClient
    ) -> None:
        catalog_id = "ert-tenant-catalog-id"
        _mock_catalog(
            _types_catalog(
                (catalog_id, "is employee of"),
                ("ert-former", "is a former employee of"),
            )
        )
        route = respx.post(f"{BASE_URL}/entity-relationships").mock(
            return_value=_relationship_document(status=201, start_date=_START.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(start_date=_START.isoformat())
        )

        await _run(client)

        type_data = object_dict(
            object_dict(_relationships(recorded_json_bodies(route)[0])["entityRelationshipType"])[
                "data"
            ]
        )
        assert type_data["id"] == catalog_id
        assert catalog_id != "456439"
        command_source = Path(inspect.getfile(CreateEmploymentCommand)).read_text()
        service_source = Path(inspect.getfile(EntityRelationshipTypesService)).read_text()
        assert "456439" not in command_source
        assert "456439" not in service_source

    @respx.mock
    async def test_ambiguous_employment_type_lists_options_and_does_not_write(
        self, client: BackstopClient
    ) -> None:
        _mock_catalog(
            _types_catalog(
                ("ert-a", "is employee of"),
                ("ert-b", "is employee of (mirror)"),
                ("ert-portal", "has portal access to"),
            )
        )
        route = respx.post(f"{BASE_URL}/entity-relationships")

        with pytest.raises(ToolError, match="ambiguous") as raised:
            await _run(client)

        message = str(raised.value)
        assert "is employee of (ert-a)" in message
        assert "is employee of (mirror) (ert-b)" in message
        assert "Available types:" in message
        assert route.call_count == 0

    @respx.mock
    async def test_no_matching_employment_type_does_not_write(self, client: BackstopClient) -> None:
        _mock_catalog(
            _types_catalog(
                ("ert-portal", "has portal access to"),
                ("ert-owns", "owns account"),
            )
        )
        route = respx.post(f"{BASE_URL}/entity-relationships")

        with pytest.raises(ToolError, match="No employment entity-relationship type matched"):
            await _run(client)

        assert route.call_count == 0

    @respx.mock
    async def test_former_types_are_excluded_so_the_current_one_is_used(
        self, client: BackstopClient
    ) -> None:
        _mock_catalog()
        route = respx.post(f"{BASE_URL}/entity-relationships").mock(
            return_value=_relationship_document(status=201, start_date=_START.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(start_date=_START.isoformat())
        )

        await _run(client)

        type_data = object_dict(
            object_dict(_relationships(recorded_json_bodies(route)[0])["entityRelationshipType"])[
                "data"
            ]
        )
        assert type_data["id"] == _CATALOG_ID
        assert type_data["id"] != "ert-former"

    @respx.mock
    async def test_created_values_come_from_the_reread(self, client: BackstopClient) -> None:
        _mock_catalog()
        respx.post(f"{BASE_URL}/entity-relationships").mock(
            return_value=_relationship_document(status=201, start_date="2020-01-01")
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(start_date=_START.isoformat())
        )

        result = await _run(client)

        assert result.id == _REL_ID
        assert result.resource_type == "entity-relationships"
        assert result.start_date == _START
        assert result.created_mirror_row is True
        assert result.warnings == ()
