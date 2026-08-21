"""The custom-field definition catalog: what a definition projection keeps, and the walk.

The TTL, single-flight and serve-stale protocol behind `get` is `CachedCatalog`, exercised for
this service among the others in `tests/features/test_cached_catalog.py`.
"""

from collections.abc import AsyncGenerator, Callable, Sequence
from typing import Protocol, cast

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient, BackstopClientFactory
from backstop_mcp.features.custom_fields import (
    CustomFieldDefinitionAttributes,
    CustomFieldDefinitionDto,
    CustomFieldsService,
)
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]


class _RecordedCall(Protocol):
    @property
    def request(self) -> httpx.Request: ...


@pytest.fixture
async def clients() -> AsyncGenerator[ClientBuilder]:
    """Build a client per Backstop base URL.

    Each test uses its own sub-path as a distinct "instance" so mocked routes cannot leak
    across cases. The factory owns the base URL, so one is created per URL and all of them
    are closed together.
    """
    built: list[BackstopClientFactory] = []

    def make(base_url: str) -> BackstopClient:
        factory = client_factory(base_url)
        built.append(factory)
        return factory.for_credential(credential("schema-bob"))

    yield make
    for factory in built:
        await factory.aclose()


def _service(*, ttl_minutes: int = 60) -> CustomFieldsService:
    return CustomFieldsService.with_ttl_minutes(ttl_minutes=ttl_minutes)


def _definition_resource(
    resource_id: str,
    *,
    name: str | None = "Grade",
    entity_type: str | None = "OrganizationBean",
    **attrs: object,
) -> BackstopApiResource[CustomFieldDefinitionAttributes]:
    attributes: dict[str, object] = {**attrs}
    if name is not None:
        attributes["name"] = name
    if entity_type is not None:
        attributes["entityType"] = entity_type
    return BackstopApiResource[CustomFieldDefinitionAttributes].model_validate(
        {
            "id": resource_id,
            "type": "custom-field-definitions",
            "attributes": attributes,
        }
    )


class TestDefinitionFromResource:
    def test_skips_unknown_bean(self) -> None:
        row = _definition_resource("1", entity_type="ContactBean")
        assert CustomFieldDefinitionDto.from_resource(row) is None

    def test_skips_missing_name(self) -> None:
        assert CustomFieldDefinitionDto.from_resource(_definition_resource("1", name=None)) is None

    def test_skips_missing_entity_type(self) -> None:
        assert (
            CustomFieldDefinitionDto.from_resource(_definition_resource("1", entity_type=None))
            is None
        )

    def test_keeps_organization_bean_and_maps_layout_fields(self) -> None:
        definition = CustomFieldDefinitionDto.from_resource(
            _definition_resource(
                "42",
                name="Grade",
                entity_type="OrganizationBean",
                fieldType="picklist",
                fieldTypeDisplay="Picklist",
                isTimeSeries=False,
                selectOptions=[{"id": "1", "label": "Active"}],
                groupId="321",
                tabName="Overview",
                groupName="Status",
                layoutName="Organization",
                resourceType="organizations",
                required=True,
                clientRequired=False,
                systemDefined=False,
                description="Investor grade",
            )
        )

        assert definition is not None
        assert definition.id == "42"
        assert definition.name == "Grade"
        assert definition.entity_type == "OrganizationBean"
        assert definition.field_type == "picklist"
        assert definition.field_type_display == "Picklist"
        assert definition.is_time_series is False
        assert definition.select_options == [{"id": "1", "label": "Active"}]
        assert definition.group_id == 321
        assert definition.tab_name == "Overview"
        assert definition.group_name == "Status"
        assert definition.layout_name == "Organization"
        assert definition.resource_type == "organizations"
        assert definition.required is True
        assert definition.client_required is False
        assert definition.system_defined is False
        assert definition.description == "Investor grade"

    def test_missing_select_options_become_empty_list(self) -> None:
        definition = CustomFieldDefinitionDto.from_resource(_definition_resource("1"))
        assert definition is not None
        assert definition.select_options == []

    def test_null_select_options_become_empty_list(self) -> None:
        definition = CustomFieldDefinitionDto.from_resource(
            _definition_resource("1", selectOptions=None)
        )
        assert definition is not None
        assert definition.select_options == []

    def test_object_select_options_under_collection_key(self) -> None:
        definition = CustomFieldDefinitionDto.from_resource(
            _definition_resource("1", selectOptions={"options": [{"id": "1", "label": "Active"}]})
        )
        assert definition is not None
        assert definition.select_options == [{"id": "1", "label": "Active"}]

    def test_object_select_options_under_data_list(self) -> None:
        definition = CustomFieldDefinitionDto.from_resource(
            _definition_resource("1", selectOptions={"data": [{"id": "1", "label": "Active"}]})
        )
        assert definition is not None
        assert definition.select_options == [{"id": "1", "label": "Active"}]

    def test_object_select_options_under_data_resource(self) -> None:
        definition = CustomFieldDefinitionDto.from_resource(
            _definition_resource("1", selectOptions={"data": {"id": "1", "label": "Active"}})
        )
        assert definition is not None
        assert definition.select_options == [{"id": "1", "label": "Active"}]

    @pytest.mark.parametrize("group_id", ["", "  ", "not-an-integer"])
    def test_malformed_group_id_becomes_none(self, group_id: object) -> None:
        definition = CustomFieldDefinitionDto.from_resource(
            _definition_resource("1", groupId=group_id)
        )

        assert definition is not None
        assert definition.group_id is None


class TestCatalogGet:
    @pytest.mark.asyncio
    @respx.mock
    async def test_first_get_paginates_and_caches(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/refresh-index"
        service = _service()

        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "99",
                            "custom-field-definitions",
                            name="is1",
                            entityType="OrganizationBean",
                            fieldType="picklist",
                            isTimeSeries=False,
                            selectOptions=[{"id": "1", "label": "Active"}],
                            groupId="not-an-integer",
                            tabName="Overview",
                            groupName="Status",
                            layoutName="Organization",
                            resourceType="organizations",
                        ),
                        resource(
                            "100",
                            "custom-field-definitions",
                            entityType="OrganizationBean",
                            fieldType="text",
                        ),
                        resource(
                            "101",
                            "custom-field-definitions",
                            name="Hidden",
                            entityType="ContactBean",
                            fieldType="text",
                        ),
                    ],
                    "links": {"next": None},
                },
            )
        )

        definitions, cache = await service.get(clients(base_url))

        params = route.calls.last.request.url.params
        assert params["page[limit]"] == "1000"
        assert "include" not in params
        recorded = cast("Sequence[_RecordedCall]", respx.calls)
        assert not any("/lov-entries" in str(call.request.url) for call in recorded)

        assert cache == "ok"
        assert list(definitions) == ["99"]
        definition = definitions["99"]
        assert definition.name == "is1"
        assert definition.entity_type == "OrganizationBean"
        assert definition.select_options == [{"id": "1", "label": "Active"}]
        assert definition.group_id is None
        assert definition.tab_name == "Overview"
        assert definition.group_name == "Status"
        assert definition.layout_name == "Organization"
        assert definition.resource_type == "organizations"
