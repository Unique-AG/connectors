"""The custom-field definition catalog: what a definition projection keeps, and the walk.

The TTL, single-flight and serve-stale protocol behind `get` is `CachedCatalog`, exercised for
this service among the others in `tests/features/test_cached_catalog.py`.
"""

import logging
from collections.abc import AsyncGenerator, Callable, Sequence
from typing import Protocol, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient, BackstopClientFactory
from backstop_mcp.features.custom_fields import (
    CustomFieldDefinitionAttributes,
    CustomFieldDefinitionDto,
    CustomFieldFilters,
    CustomFieldsService,
    CustomFieldValueAttributes,
    RegularCustomFieldValuesAttributes,
    ResolvedCustomFieldValueResponse,
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


def _probability_definition() -> CustomFieldDefinitionDto:
    return CustomFieldDefinitionDto(
        id="8648265",
        name="Probability",
        entity_type="OpportunityBean",
        field_type="PERCENT",
        field_type_display="Percent",
        tab_name="Master Pipeline",
        group_name="Pipeline Entries",
        group_id=1,
    )


def _fees_definition() -> CustomFieldDefinitionDto:
    return CustomFieldDefinitionDto(
        id="1",
        name="Estimated Fees",
        entity_type="OpportunityBean",
        field_type="MONEY",
        tab_name="Master Pipeline",
        group_name="Pipeline Entries",
        group_id=1,
    )


def _two_field_catalog() -> dict[str, CustomFieldDefinitionDto]:
    return {"8648265": _probability_definition(), "1": _fees_definition()}


def _two_stored_rows() -> list[CustomFieldValueAttributes]:
    return RegularCustomFieldValuesAttributes.model_validate(
        {
            "regularCustomFieldValues": [
                {"definitionId": "8648265", "value": 0.3},
                {"definitionId": "1", "value": 50000},
            ]
        }
    ).regular_custom_field_values


def _rows(*items: object) -> list[CustomFieldValueAttributes]:
    return RegularCustomFieldValuesAttributes.model_validate(
        {"regularCustomFieldValues": list(items)}
    ).regular_custom_field_values


async def _join(
    catalog: dict[str, CustomFieldDefinitionDto],
    custom_fields: Sequence[CustomFieldValueAttributes] | None,
    *,
    filters: CustomFieldFilters | None = None,
) -> list[ResolvedCustomFieldValueResponse]:
    service = _service()
    service.load_catalog = AsyncMock(return_value=catalog)
    return await service.join_values(
        cast(BackstopClient, MagicMock()),
        custom_fields,
        filters=filters if filters is not None else CustomFieldFilters(),
    )


class TestRegularCustomFieldValues:
    def test_non_list_dump_becomes_empty(self) -> None:
        parsed = RegularCustomFieldValuesAttributes.model_validate(
            {"regularCustomFieldValues": "not-a-list"}
        )
        assert parsed.regular_custom_field_values == []

    def test_missing_dump_becomes_empty(self) -> None:
        parsed = RegularCustomFieldValuesAttributes.model_validate({})
        assert parsed.regular_custom_field_values == []

    def test_malformed_row_is_dropped_and_the_rest_kept(self) -> None:
        parsed = RegularCustomFieldValuesAttributes.model_validate(
            {
                "regularCustomFieldValues": [
                    "not-a-row",
                    {"definitionId": "8648265", "value": 0.3},
                ]
            }
        )
        assert [row.value for row in parsed.regular_custom_field_values] == [0.3]


class TestJoinValues:
    @pytest.mark.asyncio
    async def test_joins_stored_rows_to_field_type(self) -> None:
        catalog = {"8648265": _probability_definition()}
        stored = _rows({"definitionId": 8648265, "name": "Probability", "value": 0.3})

        published = await _join(catalog, stored)

        assert len(published) == 1
        assert published[0].definition_id == "8648265"
        assert published[0].name == "Probability"
        assert published[0].field_type == "PERCENT"
        assert published[0].value == 0.3

    @pytest.mark.asyncio
    async def test_name_filter_keeps_only_that_field(self) -> None:
        published = await _join(
            _two_field_catalog(),
            _two_stored_rows(),
            filters=CustomFieldFilters(names=("Probability",)),
        )
        assert [row.name for row in published] == ["Probability"]

    @pytest.mark.asyncio
    async def test_definition_id_filter_keeps_only_that_field(self) -> None:
        published = await _join(
            _two_field_catalog(),
            _two_stored_rows(),
            filters=CustomFieldFilters(definition_ids=("1",)),
        )
        assert [row.name for row in published] == ["Estimated Fees"]

    @pytest.mark.asyncio
    async def test_name_and_definition_id_filters_and_together(self) -> None:
        published = await _join(
            _two_field_catalog(),
            _two_stored_rows(),
            filters=CustomFieldFilters(names=("Probability",), definition_ids=("1",)),
        )
        assert published == []

    @pytest.mark.asyncio
    async def test_a_definition_missing_from_the_catalog_is_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        stored = _rows(
            {"definitionId": "999", "value": "x"},
            {"definitionId": "8648265", "value": 0.3},
        )
        with caplog.at_level(logging.WARNING):
            published = await _join({"8648265": _probability_definition()}, stored)

        assert [row.value for row in published] == [0.3]
        matching = [
            record
            for record in caplog.records
            if record.message == "custom_fields.values.definition_missing"
        ]
        assert len(matching) == 1
        extras = matching[0].__dict__
        assert extras["definition_id"] == "999"
        assert extras["remedy"] == "list_custom_fields(refresh=true)"

    @pytest.mark.asyncio
    async def test_empty_dump_yields_no_rows(self) -> None:
        catalog = {"8648265": _probability_definition()}
        assert await _join(catalog, None) == []
        assert await _join(catalog, []) == []


class TestLoadCatalog:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_the_walk_fails(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/catalog-down"
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "down"}]})
        )

        catalog = await _service().load_catalog(clients(base_url))

        assert catalog is None


class TestJoinValuesCatalog:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_empty_when_catalog_is_unavailable(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/resolve-down"
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "down"}]})
        )

        published = await _service().join_values(
            clients(base_url),
            _rows({"definitionId": "8648265", "value": 0.3}),
        )

        assert published == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_joins_through_a_loaded_catalog(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/resolve-join"
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "8648265",
                            "custom-field-definitions",
                            name="Probability",
                            entityType="OpportunityBean",
                            fieldType="PERCENT",
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        published = await _service().join_values(
            clients(base_url),
            _rows({"definitionId": 8648265, "value": 0.3}),
        )

        assert len(published) == 1
        assert published[0].field_type == "PERCENT"
        assert published[0].value == 0.3
