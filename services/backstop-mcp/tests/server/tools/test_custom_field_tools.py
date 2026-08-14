import inspect
from collections.abc import Callable
from typing import get_args

import httpx
import pytest
import respx
from pydantic import TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from backstop_mcp.features.custom_fields import CustomFieldEntityType
from backstop_mcp.server.tools.list_custom_fields import (
    ListCustomFieldsResponse,
    list_custom_fields,
)
from tests.features.party_resolver.helpers import BASE_URL, resource
from tests.server.tools.helpers import tool_model

type ConnectUser = Callable[..., object]


def tenant(name: str) -> str:
    """A distinct Backstop base URL per test so mocked routes cannot leak across cases."""
    return f"{BASE_URL}/{name}"


def _definitions_route(base_url: str, *definitions: dict[str, object]) -> respx.Route:
    return respx.get(f"{base_url}/custom-field-definitions").mock(
        return_value=httpx.Response(200, json={"data": list(definitions), "links": {"next": None}})
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
    async def test_lists_definitions_for_requested_types(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-list")
        await connect_user("user-cf-list-1", "cf-list-bob", base_url=base_url)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status(), _person_grade(), _account_name())

        result = tool_model(
            await list_custom_fields(
                entity_types=[CustomFieldEntityType.ORGANIZATIONS, CustomFieldEntityType.PEOPLE],
                refresh=True,
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
    async def test_preserves_request_order(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-list-order")
        await connect_user("user-cf-list-order", "cf-list-order", base_url=base_url)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status(), _person_grade())

        result = tool_model(
            await list_custom_fields(
                entity_types=[CustomFieldEntityType.PEOPLE, CustomFieldEntityType.ORGANIZATIONS],
                refresh=True,
            ),
            ListCustomFieldsResponse,
        )
        assert list(result.definitions_by_entity) == [
            CustomFieldEntityType.PEOPLE,
            CustomFieldEntityType.ORGANIZATIONS,
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_requested_type_is_present(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-list-empty")
        await connect_user("user-cf-list-2", "cf-list-carol", base_url=base_url)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status())

        result = tool_model(
            await list_custom_fields(
                entity_types=[CustomFieldEntityType.PEOPLE],
                refresh=True,
            ),
            ListCustomFieldsResponse,
        )

        assert list(result.definitions_by_entity) == [CustomFieldEntityType.PEOPLE]
        assert result.definitions_by_entity[CustomFieldEntityType.PEOPLE] == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_surfaces_stale_cache(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-list-stale")
        await connect_user("user-cf-list-stale", "cf-list-stale", base_url=base_url)  # pyright: ignore[reportGeneralTypeIssues]
        route = _definitions_route(base_url, _investor_status())

        first = tool_model(
            await list_custom_fields(
                entity_types=[CustomFieldEntityType.ORGANIZATIONS],
                refresh=True,
            ),
            ListCustomFieldsResponse,
        )
        assert first.cache == "ok"

        route.mock(side_effect=httpx.ConnectError("backstop down"))

        result = tool_model(
            await list_custom_fields(
                entity_types=[CustomFieldEntityType.ORGANIZATIONS],
                refresh=True,
            ),
            ListCustomFieldsResponse,
        )
        assert result.cache == "stale"
        assert result.definitions_by_entity[CustomFieldEntityType.ORGANIZATIONS][0].id == "99"


class TestListCustomFieldsInput:
    def test_rejects_contacts_and_employees(self) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(list_custom_fields).validate_python({"entity_types": ["contacts"]})
        with pytest.raises(ValidationError):
            TypeAdapter(list_custom_fields).validate_python({"entity_types": ["employees"]})

    def test_rejects_empty_entity_types(self) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(list_custom_fields).validate_python({"entity_types": []})

    def test_refresh_is_only_for_a_user_reported_missing_field(self) -> None:
        doc = list_custom_fields.__doc__ or ""
        assert "refresh=true" in doc
        assert "missing field" in doc

        refresh = inspect.signature(list_custom_fields).parameters["refresh"]
        field_info = next(arg for arg in get_args(refresh.annotation) if isinstance(arg, FieldInfo))
        assert field_info.description is not None
        assert "missing field" in field_info.description
