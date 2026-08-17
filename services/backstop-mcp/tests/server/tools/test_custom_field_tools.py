from collections.abc import Callable

import httpx
import pytest
import respx

from backstop_mcp.features.custom_fields import FieldOverride
from backstop_mcp.features.entity_types import EntityType
from backstop_mcp.server.tools.list_custom_fields import (
    ListCustomFieldsResponse,
    list_custom_fields,
)
from tests.features.party_resolver.helpers import BASE_URL, resource
from tests.server.tools.helpers import tool_model

type ConnectUser = Callable[..., object]

_OVERRIDES: dict[str, FieldOverride] = {
    "organizations:is1": FieldOverride(
        display_name="Investor Status",
        aliases=("investor status",),
    )
}


def tenant(name: str) -> str:
    """A distinct Backstop base URL per test.

    Schema snapshots are keyed by base URL and the test Postgres persists for the whole
    session, so sharing one URL would let an earlier test's snapshot satisfy a later test's
    `ensure_fresh` and skip the fetch under test.
    """
    return f"{BASE_URL}/{name}"


def _lov_entries_route(base_url: str) -> respx.Route:
    return respx.get(f"{base_url}/lov-entries").mock(
        return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
    )


def _definitions_route(base_url: str, *definitions: dict[str, object]) -> respx.Route:
    _lov_entries_route(base_url)
    return respx.get(f"{base_url}/custom-field-definitions").mock(
        return_value=httpx.Response(200, json={"data": list(definitions), "links": {"next": None}})
    )


def _investor_status(**extra: object) -> dict[str, object]:
    return resource(
        "99",
        "custom-field-definitions",
        name="is1",
        entityType="Organization",
        fieldType="picklist",
        isTimeSeries=False,
        **extra,
    )


class TestListCustomFieldsTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_lists_definitions_for_entity_type(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-list")
        await connect_user("user-cf-list-1", "cf-list-bob", base_url=base_url, overrides=_OVERRIDES)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status(selectOptions=[{"label": "Active"}]))

        result = tool_model(
            await list_custom_fields(entity_type=EntityType.ORGANIZATIONS, refresh=True),
            ListCustomFieldsResponse,
        )

        assert result.entity_type == EntityType.ORGANIZATIONS
        assert result.count == 1
        assert result.definitions[0].definition_id == "99"
        assert result.definitions[0].display_name == "Investor Status"
        assert result.definitions[0].allowed_values[0].label == "Active"

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_entity_type_returns_empty_catalog(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-list-empty")
        await connect_user("user-cf-list-2", "cf-list-carol", base_url=base_url)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status())

        result = tool_model(
            await list_custom_fields(entity_type=EntityType.PEOPLE, refresh=True),
            ListCustomFieldsResponse,
        )

        assert result.entity_type == EntityType.PEOPLE
        assert result.count == 0
        assert result.definitions == []
