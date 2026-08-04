import httpx
import pytest
import respx
from pydantic import SecretStr

from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.backstop_client import create_backstop_client
from backstop_mcp.custom_fields.types import CustomFieldDefinition
from backstop_mcp.custom_fields.values import read_custom_field_value
from tests.party_resolver.helpers import BASE_URL

_CRED = BackstopCredentialSecret(username="values-bob", api_token=SecretStr("token"))


class TestReadCustomFieldValue:
    @pytest.mark.asyncio
    @respx.mock
    async def test_regular_path_uses_regular_custom_field_values(self) -> None:
        definition = CustomFieldDefinition(
            definition_id="55",
            entity_type="organizations",
            crm_name="Grade",
            display_name="Grade",
            is_time_series=False,
        )
        route = respx.get(f"{BASE_URL}/organizations/o1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "o1",
                        "attributes": {
                            "regularCustomFieldValues": [
                                {"definitionId": "55", "value": "A"},
                                {"definitionId": "9", "value": "other"},
                            ]
                        },
                    }
                },
            )
        )

        async with create_backstop_client(BASE_URL, _CRED) as client:
            value = await read_custom_field_value(
                client,
                entity_type="organizations",
                entity_id="o1",
                definition=definition,
            )

        assert value == "A"
        sent_url = str(route.calls.last.request.url)
        assert "regularCustomFieldValues" in sent_url
        assert "timeSeriesCustomFieldValues" not in sent_url

    @pytest.mark.asyncio
    @respx.mock
    async def test_time_series_path_not_regular(self) -> None:
        definition = CustomFieldDefinition(
            definition_id="77",
            entity_type="organizations",
            crm_name="Status History",
            display_name="Status History",
            is_time_series=True,
        )
        route = respx.get(f"{BASE_URL}/organizations/o1/timeSeriesCustomFieldValues").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "type": "timeSeriesCustomFieldValues",
                            "id": "t1",
                            "attributes": {
                                "definitionId": "77",
                                "value": "Warm",
                                "effectiveDate": "2026-01-01",
                            },
                        },
                        {
                            "type": "timeSeriesCustomFieldValues",
                            "id": "t2",
                            "attributes": {
                                "definitionId": "77",
                                "value": "Hot",
                                "effectiveDate": "2026-06-01",
                            },
                        },
                    ],
                    "links": {"next": None},
                },
            )
        )

        async with create_backstop_client(BASE_URL, _CRED) as client:
            value = await read_custom_field_value(
                client,
                entity_type="organizations",
                entity_id="o1",
                definition=definition,
            )

        assert value == "Hot"
        sent_url = str(route.calls.last.request.url)
        assert "timeSeriesCustomFieldValues" in sent_url
        assert (
            "filter%5BdefinitionId%5D%5Beq%5D=77" in sent_url
            or "filter[definitionId][eq]=77" in sent_url
        )
