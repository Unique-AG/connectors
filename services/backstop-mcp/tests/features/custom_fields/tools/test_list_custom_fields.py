import logging
from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from backstop_mcp.features.custom_fields import CustomFieldEntityType, ListCustomFieldsResponse
from backstop_mcp.features.custom_fields.tools.list_custom_fields import list_custom_fields
from tests.features.party_resolver.helpers import BASE_URL, resource
from tests.helpers import custom_fields_service, recorded_requests, tool_client
from tests.server.tools.helpers import tool_model, tool_payload

# The published input schema: the tool's signature with the `Depends(...)` collaborators and
# `Context` stripped, which is what FastMCP validates a call against.
_INPUT: TypeAdapter[object] = TypeAdapter(without_injected_parameters(list_custom_fields))
_FETCH_LOGGER = "backstop_mcp.features.custom_fields.custom_fields_service"


def tenant(name: str) -> str:
    """A distinct Backstop base URL per test so mocked routes cannot leak across cases."""
    return f"{BASE_URL}/{name}"


def _definitions_page(
    *definitions: dict[str, object], next_url: str | None = None
) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(definitions), "links": {"next": next_url}},
    )


def _definitions_route(base_url: str, *definitions: dict[str, object]) -> respx.Route:
    return respx.get(f"{base_url}/custom-field-definitions").mock(
        return_value=_definitions_page(*definitions)
    )


def _investor_status(**extra: object) -> dict[str, object]:
    return resource(
        "99",
        "custom-field-definitions",
        name="is1",
        entityType="OrganizationBean",
        fieldType="picklist",
        isTimeSeries=False,
        selectOptions=[{"label": "Active"}],
        tabName="Overview",
        groupName="Status",
        layoutName="Organization",
        resourceType="organizations",
        **extra,
    )


def _person_grade(**extra: object) -> dict[str, object]:
    return resource(
        "100",
        "custom-field-definitions",
        name="grade",
        entityType="PersonBean",
        fieldType="text",
        isTimeSeries=False,
        **extra,
    )


def _account_name(**extra: object) -> dict[str, object]:
    return resource(
        "101",
        "custom-field-definitions",
        name="accountName",
        entityType="AccountBean",
        fieldType="text",
        isTimeSeries=False,
        **extra,
    )


class TestListCustomFieldsTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_lists_definitions_for_requested_types(self) -> None:
        base_url = tenant("cf-list")
        _definitions_route(base_url, _investor_status(), _person_grade(), _account_name())

        async with tool_client(base_url) as client:
            result = tool_model(
                await list_custom_fields(
                    entity_types=[
                        CustomFieldEntityType.ORGANIZATIONS,
                        CustomFieldEntityType.PEOPLE,
                    ],
                    refresh=True,
                    custom_fields=custom_fields_service(client),
                ),
                ListCustomFieldsResponse,
            )

        assert result.status == "ok"
        assert result.cache == "ok"
        assert list(result.definitions_by_entity) == [
            CustomFieldEntityType.ORGANIZATIONS,
            CustomFieldEntityType.PEOPLE,
        ]
        organizations = result.definitions_by_entity[CustomFieldEntityType.ORGANIZATIONS]
        people = result.definitions_by_entity[CustomFieldEntityType.PEOPLE]
        assert [item.id for item in organizations] == ["99"]
        assert [item.id for item in people] == ["100"]
        assert organizations[0].entity_type == "OrganizationBean"
        assert people[0].entity_type == "PersonBean"
        assert organizations[0].select_options == [{"label": "Active"}]
        assert organizations[0].tab_name == "Overview"
        assert organizations[0].group_name == "Status"
        assert organizations[0].layout_name == "Organization"
        assert organizations[0].resource_type == "organizations"

    @pytest.mark.asyncio
    @respx.mock
    async def test_collapses_equivalent_duplicates_across_pages_without_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        base_url = tenant("cf-list-deduplicated")
        definition = _investor_status(groupId=321)
        next_url = (
            f"{base_url}/custom-field-definitions?"
            "page[offset]=1000&page[limit]=1000&sentinel=literal-next"
        )
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=[
                _definitions_page(
                    definition,
                    next_url=next_url,
                ),
                _definitions_page(_investor_status(groupId=321)),
            ]
        )

        async with tool_client(base_url) as client:
            with caplog.at_level(logging.WARNING, logger=_FETCH_LOGGER):
                result = tool_model(
                    await list_custom_fields(
                        entity_types=[CustomFieldEntityType.ORGANIZATIONS],
                        refresh=True,
                        custom_fields=custom_fields_service(client),
                    ),
                    ListCustomFieldsResponse,
                )

        assert route.call_count == 2
        requests = recorded_requests(route.calls)
        assert requests[0].url.params["page[offset]"] == "0"
        assert requests[0].url.params["page[limit]"] == "1000"
        assert str(requests[1].url) == next_url
        assert not any(
            record.name == _FETCH_LOGGER and record.levelno >= logging.WARNING
            for record in caplog.records
        )
        assert tool_payload(result) == {
            "status": "ok",
            "cache": "ok",
            "definitions_by_entity": {
                "organizations": [
                    {
                        "id": "99",
                        "name": "is1",
                        "entity_type": "OrganizationBean",
                        "field_type": "picklist",
                        "field_type_display": None,
                        "is_time_series": False,
                        "select_options": [{"label": "Active"}],
                        "tab_name": "Overview",
                        "group_name": "Status",
                        "group_id": 321,
                        "layout_name": "Organization",
                        "resource_type": "organizations",
                        "required": None,
                        "client_required": None,
                        "system_defined": None,
                        "description": None,
                    }
                ]
            },
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_warns_and_retains_first_conflicting_definition(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        base_url = tenant("cf-list-conflicting-duplicates")
        first_definition = _investor_status(groupId=321)
        conflicting_definition = _investor_status(groupId=999)
        next_url = (
            f"{base_url}/custom-field-definitions?"
            "page[offset]=1000&page[limit]=1000&sentinel=literal-next"
        )
        route = _definitions_route(base_url, first_definition)
        async with tool_client(base_url) as client:
            service = custom_fields_service(client)
            first = tool_model(
                await list_custom_fields(
                    entity_types=[CustomFieldEntityType.ORGANIZATIONS],
                    refresh=True,
                    custom_fields=service,
                ),
                ListCustomFieldsResponse,
            )
            route.mock(
                side_effect=[
                    _definitions_page(first_definition, next_url=next_url),
                    _definitions_page(conflicting_definition),
                ]
            )
            with caplog.at_level(logging.WARNING, logger=_FETCH_LOGGER):
                refreshed = tool_model(
                    await list_custom_fields(
                        entity_types=[CustomFieldEntityType.ORGANIZATIONS],
                        refresh=True,
                        custom_fields=service,
                    ),
                    ListCustomFieldsResponse,
                )

        assert first.cache == "ok"
        assert first.definitions_by_entity[CustomFieldEntityType.ORGANIZATIONS][0].group_id == 321
        assert route.call_count == 3
        requests = recorded_requests(route.calls)
        assert requests[1].url.params["page[offset]"] == "0"
        assert requests[1].url.params["page[limit]"] == "1000"
        assert str(requests[2].url) == next_url
        assert refreshed.status == "ok"
        assert refreshed.cache == "ok"
        definitions = refreshed.definitions_by_entity[CustomFieldEntityType.ORGANIZATIONS]
        assert len(definitions) == 1
        assert definitions[0].group_id == 321
        assert [
            record.getMessage() for record in caplog.records if record.name == _FETCH_LOGGER
        ] == [
            "Conflicting custom-field definitions for duplicate id '99'; retaining first definition"
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_preserves_request_order(self) -> None:
        base_url = tenant("cf-list-order")
        _definitions_route(base_url, _investor_status(), _person_grade())

        async with tool_client(base_url) as client:
            result = tool_model(
                await list_custom_fields(
                    entity_types=[
                        CustomFieldEntityType.PEOPLE,
                        CustomFieldEntityType.ORGANIZATIONS,
                    ],
                    refresh=True,
                    custom_fields=custom_fields_service(client),
                ),
                ListCustomFieldsResponse,
            )
        assert list(result.definitions_by_entity) == [
            CustomFieldEntityType.PEOPLE,
            CustomFieldEntityType.ORGANIZATIONS,
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_requested_type_is_present(self) -> None:
        base_url = tenant("cf-list-empty")
        _definitions_route(base_url, _investor_status())

        async with tool_client(base_url) as client:
            result = tool_model(
                await list_custom_fields(
                    entity_types=[CustomFieldEntityType.PEOPLE],
                    refresh=True,
                    custom_fields=custom_fields_service(client),
                ),
                ListCustomFieldsResponse,
            )

        assert list(result.definitions_by_entity) == [CustomFieldEntityType.PEOPLE]
        assert result.definitions_by_entity[CustomFieldEntityType.PEOPLE] == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_surfaces_stale_cache(self) -> None:
        base_url = tenant("cf-list-stale")
        route = _definitions_route(base_url, _investor_status())
        async with tool_client(base_url) as client:
            service = custom_fields_service(client)
            first = tool_model(
                await list_custom_fields(
                    entity_types=[CustomFieldEntityType.ORGANIZATIONS],
                    refresh=True,
                    custom_fields=service,
                ),
                ListCustomFieldsResponse,
            )
            assert first.cache == "ok"

            route.mock(side_effect=httpx.ConnectError("backstop down"))

            result = tool_model(
                await list_custom_fields(
                    entity_types=[CustomFieldEntityType.ORGANIZATIONS],
                    refresh=True,
                    custom_fields=service,
                ),
                ListCustomFieldsResponse,
            )
        assert result.cache == "stale"
        assert result.definitions_by_entity[CustomFieldEntityType.ORGANIZATIONS][0].id == "99"


class TestListCustomFieldsInput:
    def test_rejects_contacts_and_employees(self) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"entity_types": ["contacts"]})
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"entity_types": ["employees"]})

    def test_rejects_empty_entity_types(self) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"entity_types": []})

    def test_refresh_is_only_for_a_user_reported_missing_field(self) -> None:
        doc = list_custom_fields.__doc__ or ""
        assert "refresh=true" in doc
        assert "missing field" in doc
        assert "Backstop custom-field catalog" in doc
        assert "party or a concrete Backstop entity resource" in doc
        assert "tenant" not in doc.casefold()

        annotations = cast("dict[str, object]", list_custom_fields.__annotations__)
        field_info = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["refresh"]))
            if isinstance(item, FieldInfo)
        )
        assert field_info.description is not None
        assert "missing field" in field_info.description
