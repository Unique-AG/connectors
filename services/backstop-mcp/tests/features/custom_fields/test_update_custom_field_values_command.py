"""`UpdateCustomFieldValuesCommand`: catalog validation and bulkLoadSummary outcomes."""

from collections.abc import AsyncGenerator
from datetime import date

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields import (
    UpdateCustomFieldValuesCommand,
    UpdateCustomFieldValuesInput,
    get_update_custom_field_values_command_factory,
)
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    custom_fields_service,
    recorded_json_bodies,
    resource,
)
from tests.server.tools.helpers import object_dict, object_list

_UPDATE: TypeAdapter[UpdateCustomFieldValuesInput] = TypeAdapter(UpdateCustomFieldValuesInput)
_TEXT = 9823191
_DROPDOWN = 9910127
_TIME_SERIES = 8746199


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> UpdateCustomFieldValuesCommand:
    return get_update_custom_field_values_command_factory(
        client, custom_fields_service=custom_fields_service(client)
    )


def _update(
    *values: dict[str, object],
    entity_type: str = "people",
    entity_id: str = "792222599",
) -> UpdateCustomFieldValuesInput:
    return _UPDATE.validate_python(
        {"entity_type": entity_type, "entity_id": entity_id, "values": list(values)}
    )


def _value(
    definition_id: int, value: object, *, effective_date: date | None = None
) -> dict[str, object]:
    row: dict[str, object] = {"definition_id": definition_id, "value": value}
    if effective_date is not None:
        row["effective_date"] = effective_date
    return row


def _definition(
    definition_id: int,
    *,
    name: str,
    entity_type: str = "PersonBean",
    is_time_series: bool = False,
    select_options: list[object] | None = None,
    required: bool = False,
    max_length: int | None = None,
) -> dict[str, object]:
    return resource(
        str(definition_id),
        "custom-field-definitions",
        name=name,
        entityType=entity_type,
        isTimeSeries=is_time_series,
        selectOptions=select_options or [],
        required=required,
        **({} if max_length is None else {"maxLength": max_length}),
    )


def _catalog(*definitions: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(definitions), "links": {"next": None}})


def _written(definition_id: int, value: object) -> dict[str, object]:
    return {"id": f"row-{definition_id}", "definitionId": definition_id, "value": value}


def _bulk_document(
    *,
    total: int,
    success: int,
    errors: list[dict[str, object]],
    records: list[dict[str, object]],
) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "data": {
                "id": None,
                "type": "bulk-custom-field-values",
                "attributes": {
                    "records": records,
                    "bulkLoadSummary": {
                        "totalCount": total,
                        "successCount": success,
                        "errorMessages": errors,
                    },
                },
                "links": "{ }",
            },
            "included": [],
        },
    )


class TestUpdateCustomFieldValuesCommand:
    @respx.mock
    async def test_unknown_definition_id_is_rejected_without_writing(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes"))
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(total=1, success=1, errors=[], records=[])
        )

        with pytest.raises(ToolError, match="list_custom_fields"):
            await make_command(client).run(update=_update(_value(999999999, "x")))

        assert route.call_count == 0

    @respx.mock
    async def test_a_people_field_cannot_be_written_on_an_organization(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes", entity_type="PersonBean"))
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values")

        with pytest.raises(ToolError, match="PersonBean, not organizations"):
            await make_command(client).run(
                update=_update(_value(_TEXT, "hello"), entity_type="organizations")
            )

        assert route.call_count == 0

    @respx.mock
    async def test_a_party_field_can_be_written_on_a_person(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes", entity_type="PartyBean"))
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=1, success=1, errors=[], records=[_written(_TEXT, "hello")]
            )
        )

        result = await make_command(client).run(update=_update(_value(_TEXT, "hello")))

        assert result.applied_count == 1
        assert route.call_count == 1

    @respx.mock
    async def test_time_series_field_requires_an_effective_date(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TIME_SERIES, name="TS", is_time_series=True))
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(total=1, success=1, errors=[], records=[])
        )

        with pytest.raises(ToolError, match="need effectiveDate"):
            await make_command(client).run(update=_update(_value(_TIME_SERIES, "Direct")))

        assert route.call_count == 0

    @respx.mock
    async def test_regular_field_rejects_an_effective_date(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes"))
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(total=1, success=1, errors=[], records=[])
        )

        with pytest.raises(ToolError, match="does not need effectiveDate"):
            await make_command(client).run(
                update=_update(_value(_TEXT, "hello", effective_date=date(2026, 9, 14)))
            )

        assert route.call_count == 0

    @respx.mock
    async def test_invalid_picklist_value_lists_allowed_options_and_does_not_write(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(
                _definition(
                    _DROPDOWN,
                    name="Source",
                    select_options=[{"label": "Direct"}, {"label": "Portal"}],
                )
            )
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(total=1, success=1, errors=[], records=[])
        )

        with pytest.raises(ToolError, match=r"valid options are \[Direct, Portal\]"):
            await make_command(client).run(update=_update(_value(_DROPDOWN, "NotARealOption")))

        assert route.call_count == 0

    @respx.mock
    async def test_opportunity_entity_type_is_sent_as_the_resource_type(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes", entity_type="OpportunityBean"))
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=1,
                success=1,
                errors=[],
                records=[_written(_TEXT, "hello")],
            )
        )

        result = await make_command(client).run(
            update=_update(_value(_TEXT, "hello"), entity_type="opportunities", entity_id="5755101")
        )

        assert result.applied_count == 1
        body = recorded_json_bodies(route)[0]
        attributes = object_dict(object_dict(body["data"])["attributes"])
        assert object_dict(attributes["resource"]) == {
            "resourceId": "5755101",
            "resourceType": "opportunities",
        }
        row = object_dict(object_list(attributes["records"])[0])
        assert row["definitionId"] == _TEXT
        assert row["value"] == "hello"

    @respx.mock
    async def test_partial_bulk_failure_is_reported_per_record(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(
                _definition(_TEXT, name="Notes"),
                _definition(_DROPDOWN, name="Source"),
            )
        )
        respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=2,
                success=1,
                errors=[{"index": 1, "message": "Resource custom-field-definitions not found"}],
                records=[_written(_TEXT, "hello")],
            )
        )

        result = await make_command(client).run(
            update=_update(_value(_TEXT, "hello"), _value(_DROPDOWN, "Direct"))
        )

        assert result.total_count == 2
        assert result.applied_count == 1
        assert result.records[0].status == "applied"
        assert result.records[1].status == "failed"
        assert result.records[1].error is not None

    @respx.mock
    async def test_total_failure_on_201_is_not_reported_as_success(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes"))
        )
        respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=1,
                success=0,
                errors=[{"message": "batch rejected"}],
                records=[],
            )
        )

        result = await make_command(client).run(update=_update(_value(_TEXT, "hello")))

        assert result.applied_count == 0
        assert result.records[0].status == "failed"
        assert result.records[0].error == "batch rejected"

    @respx.mock
    async def test_total_failure_carries_the_indexed_message_backstop_actually_sends(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_DROPDOWN, name="Source", select_options=["Direct"]))
        )
        respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=1,
                success=0,
                errors=[{"index": 0, "message": "Error load record #0, Invalid value"}],
                records=[],
            )
        )

        result = await make_command(client).run(update=_update(_value(_DROPDOWN, "Direct")))

        assert result.applied_count == 0
        assert result.records[0].status == "failed"
        assert result.records[0].error == "Error load record #0, Invalid value"
        assert result.warnings == ()

    @respx.mock
    async def test_an_indexed_error_without_a_message_still_fails_the_record(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes"))
        )
        respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=1,
                success=1,
                errors=[{"index": 0}],
                records=[_written(_TEXT, "hello")],
            )
        )

        result = await make_command(client).run(update=_update(_value(_TEXT, "hello")))

        assert result.records[0].status == "failed"
        assert result.applied_count == 0

    @respx.mock
    async def test_an_unattributable_message_is_surfaced_as_a_warning(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes"))
        )
        respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=1,
                success=1,
                errors=[{"message": "partial commit warning"}],
                records=[_written(_TEXT, "hello")],
            )
        )

        result = await make_command(client).run(update=_update(_value(_TEXT, "hello")))

        assert result.records[0].status == "applied"
        assert result.warnings == ("partial commit warning",)

    @respx.mock
    async def test_a_required_field_cannot_be_written_blank(self, client: BackstopClient) -> None:
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values")
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes", required=True))
        )

        with pytest.raises(ToolError, match="required"):
            await make_command(client).run(update=_update(_value(_TEXT, "   ")))

        assert route.call_count == 0

    @respx.mock
    async def test_clearing_an_optional_field_sends_an_explicit_null_value(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes"))
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=1, success=1, errors=[], records=[_written(_TEXT, None)]
            )
        )

        result = await make_command(client).run(update=_update(_value(_TEXT, None)))

        assert result.applied_count == 1
        body = recorded_json_bodies(route)[0]
        attributes = object_dict(object_dict(body["data"])["attributes"])
        row = object_dict(object_list(attributes["records"])[0])
        assert "value" in row
        assert row["value"] is None
        assert "effectiveDate" not in row

    @respx.mock
    async def test_an_over_length_value_is_rejected_before_writing(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values")
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TEXT, name="Notes", max_length=5))
        )

        with pytest.raises(ToolError, match="maxLength 5"):
            await make_command(client).run(update=_update(_value(_TEXT, "far too long")))

        assert route.call_count == 0

    @respx.mock
    async def test_a_time_series_value_sends_its_effective_date(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=_catalog(_definition(_TIME_SERIES, name="AUM", is_time_series=True))
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=_bulk_document(
                total=1, success=1, errors=[], records=[_written(_TIME_SERIES, "10")]
            )
        )

        await make_command(client).run(
            update=_update(_value(_TIME_SERIES, "10", effective_date=date(2026, 2, 1)))
        )

        body = recorded_json_bodies(route)[0]
        attributes = object_dict(object_dict(body["data"])["attributes"])
        written = object_list(attributes["records"])
        assert object_dict(written[0])["effectiveDate"] == "2026-02-01"
