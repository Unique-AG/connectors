"""`update_custom_field_values`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields import (
    UpdateCustomFieldValuesCommand,
    UpdateCustomFieldValuesInput,
    UpdateCustomFieldValuesResponse,
    get_update_custom_field_values_command_factory,
)
from backstop_mcp.features.custom_fields.tools.update_custom_field_values import (
    update_custom_field_values,
)
from backstop_mcp.server.tools import TOOLS
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    custom_fields_service,
    recorded_json_bodies,
    resource,
)
from tests.server.tools.helpers import object_dict, tool_model

_UPDATE: TypeAdapter[UpdateCustomFieldValuesInput] = TypeAdapter(UpdateCustomFieldValuesInput)
_TEXT = 9823191


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> UpdateCustomFieldValuesCommand:
    return get_update_custom_field_values_command_factory(
        client, custom_fields_service=custom_fields_service(client)
    )


class TestUpdateCustomFieldValues:
    def test_is_registered(self) -> None:
        assert update_custom_field_values in TOOLS

    @respx.mock
    async def test_posts_the_value(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            str(_TEXT),
                            "custom-field-definitions",
                            name="Notes",
                            entityType="PersonBean",
                            isTimeSeries=False,
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )
        route = respx.post(f"{BASE_URL}/bulk-custom-field-values").mock(
            return_value=httpx.Response(
                201,
                json={
                    "data": {
                        "id": None,
                        "type": "bulk-custom-field-values",
                        "attributes": {
                            "records": [{"id": "1", "definitionId": _TEXT, "value": "hello"}],
                            "bulkLoadSummary": {
                                "totalCount": 1,
                                "successCount": 1,
                                "errorMessages": [],
                            },
                        },
                        "links": "{ }",
                    },
                    "included": [],
                },
            )
        )

        result = tool_model(
            await update_custom_field_values(
                update=_UPDATE.validate_python(
                    {
                        "entity_type": "people",
                        "entity_id": "792222599",
                        "values": [{"definition_id": _TEXT, "value": "hello"}],
                    }
                ),
                update_custom_field_values_command=make_command(client),
            ),
            UpdateCustomFieldValuesResponse,
        )

        assert result.applied_count == 1
        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert object_dict(attributes["resource"])["resourceType"] == "people"
