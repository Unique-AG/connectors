from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from backstop_mcp.features.custom_fields.tools.list_custom_field_groups import (
    ListCustomFieldGroupsResponse,
    list_custom_field_groups,
)
from tests.helpers import (
    BASE_URL,
    custom_field_groups_service,
    custom_fields_service,
    recorded_requests,
    resource,
    tool_client,
)
from tests.server.tools.helpers import tool_model, tool_payload

_INPUT: TypeAdapter[object] = TypeAdapter(without_injected_parameters(list_custom_field_groups))


def tenant(name: str) -> str:
    """A distinct Backstop base URL per test so mocked routes cannot leak across cases."""
    return f"{BASE_URL}/{name}"


def _collection_page(*items: dict[str, object], next_url: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(items), "links": {"next": next_url}},
    )


def _group(
    group_id: str,
    *,
    name: str | None = None,
    relationships: dict[str, object] | None = None,
    **attrs: object,
) -> dict[str, object]:
    row = resource(group_id, "custom-field-groups", name=name, **attrs)
    if relationships is not None:
        row["relationships"] = relationships
    return row


def _definition(
    definition_id: str, *, name: str, entity_type: str, **attrs: object
) -> dict[str, object]:
    return resource(
        definition_id,
        "custom-field-definitions",
        name=name,
        entityType=entity_type,
        **attrs,
    )


def _overview_tab() -> dict[str, object]:
    return _group("10", name="Overview", fullPathName=["Overview"])


def _details_section(*, base_url: str) -> dict[str, object]:
    return _group(
        "20",
        name="Details",
        fullPathName=["Overview", "Details"],
        parent={"id": 10, "name": "Overview", "parentId": None},
        relationships={
            "parent": {
                "links": {
                    "self": f"{base_url}/custom-field-groups/20/relationships/parent",
                    "related": f"{base_url}/custom-field-groups/10",
                }
            }
        },
    )


def _unnamed_group() -> dict[str, object]:
    return _group("30", fullPathName=["Dropped"])


def _status_flag() -> dict[str, object]:
    return _definition(
        "99",
        name="statusFlag",
        entity_type="OrganizationBean",
        fieldType="boolean",
        groupId="10",
        selectOptions=[{"label": "Yes"}],
    )


def _unplaced_field() -> dict[str, object]:
    return _definition(
        "100",
        name="unplaced",
        entity_type="OrganizationBean",
        fieldType="text",
    )


def _unknown_group_field() -> dict[str, object]:
    return _definition(
        "101",
        name="orphan",
        entity_type="PersonBean",
        fieldType="text",
        groupId=999,
    )


class TestListCustomFieldGroupsTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_path_parent_and_membership_from_one_collection_walk(self) -> None:
        base_url = tenant("cfg-project")
        next_url = (
            f"{base_url}/custom-field-groups?"
            "page[offset]=1000&page[limit]=1000&sentinel=literal-next"
        )
        groups_route = respx.get(f"{base_url}/custom-field-groups").mock(
            side_effect=[
                _collection_page(_overview_tab(), _unnamed_group(), next_url=next_url),
                _collection_page(_details_section(base_url=base_url)),
            ]
        )
        definitions_route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=_collection_page(_status_flag(), _unplaced_field(), _unknown_group_field())
        )
        parent_by_id = respx.get(f"{base_url}/custom-field-groups/10").mock(
            return_value=httpx.Response(500)
        )
        parent_related = respx.get(f"{base_url}/custom-field-groups/20/parent").mock(
            return_value=httpx.Response(500)
        )
        parent_rel = respx.get(f"{base_url}/custom-field-groups/20/relationships/parent").mock(
            return_value=httpx.Response(500)
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await list_custom_field_groups(
                    refresh=True,
                    client=client,
                    custom_fields=custom_fields_service(),
                    custom_field_groups=custom_field_groups_service(),
                ),
                ListCustomFieldGroupsResponse,
            )

        assert groups_route.call_count == 2
        assert definitions_route.call_count == 1
        group_requests = recorded_requests(groups_route.calls)
        assert group_requests[0].url.params["page[offset]"] == "0"
        assert group_requests[0].url.params["page[limit]"] == "1000"
        assert "filter[name][like]" not in group_requests[0].url.params
        assert "include" not in group_requests[0].url.params
        assert str(group_requests[1].url) == next_url
        assert parent_by_id.call_count == 0
        assert parent_related.call_count == 0
        assert parent_rel.call_count == 0
        assert not any(
            "/relationships/parent" in str(request.url) or str(request.url.path).endswith("/parent")
            for request in recorded_requests(respx.calls)
        )
        assert [group.id for group in result.groups] == ["10", "20"]
        overview, details = result.groups
        assert details.parent is not None
        assert overview.id == details.parent.id
        assert tool_payload(result) == {
            "status": "ok",
            "cache": "ok",
            "groups": [
                {
                    "id": "10",
                    "name": "Overview",
                    "full_path_name": ["Overview"],
                    "parent": None,
                    "membership": [
                        {
                            "id": "99",
                            "name": "statusFlag",
                            "entity_type": "OrganizationBean",
                            "field_type": "boolean",
                        }
                    ],
                },
                {
                    "id": "20",
                    "name": "Details",
                    "full_path_name": ["Overview", "Details"],
                    "parent": {"id": "10", "name": "Overview", "parent_id": None},
                    "membership": [],
                },
            ],
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_call_uses_cache_and_refresh_refetches(self) -> None:
        base_url = tenant("cfg-cache")
        groups_route = respx.get(f"{base_url}/custom-field-groups").mock(
            return_value=_collection_page(_overview_tab())
        )
        definitions_route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=_collection_page(_status_flag())
        )
        fields = custom_fields_service()
        groups = custom_field_groups_service()

        async with tool_client(base_url) as client:
            first = tool_model(
                await list_custom_field_groups(
                    client=client,
                    custom_fields=fields,
                    custom_field_groups=groups,
                ),
                ListCustomFieldGroupsResponse,
            )
            second = tool_model(
                await list_custom_field_groups(
                    client=client,
                    custom_fields=fields,
                    custom_field_groups=groups,
                ),
                ListCustomFieldGroupsResponse,
            )
            refreshed = tool_model(
                await list_custom_field_groups(
                    refresh=True,
                    client=client,
                    custom_fields=fields,
                    custom_field_groups=groups,
                ),
                ListCustomFieldGroupsResponse,
            )

        assert first.cache == "ok"
        assert second.cache == "ok"
        assert refreshed.cache == "ok"
        assert groups_route.call_count == 2
        assert definitions_route.call_count == 2
        assert [group.id for group in first.groups] == ["10"]
        assert [group.id for group in second.groups] == ["10"]
        assert [group.id for group in refreshed.groups] == ["10"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_failure_serves_stale(self) -> None:
        base_url = tenant("cfg-stale")
        groups_route = respx.get(f"{base_url}/custom-field-groups").mock(
            return_value=_collection_page(_overview_tab())
        )
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=_collection_page(_status_flag())
        )
        fields = custom_fields_service()
        groups = custom_field_groups_service()

        async with tool_client(base_url) as client:
            first = tool_model(
                await list_custom_field_groups(
                    refresh=True,
                    client=client,
                    custom_fields=fields,
                    custom_field_groups=groups,
                ),
                ListCustomFieldGroupsResponse,
            )
            groups_route.mock(side_effect=httpx.ConnectError("backstop down"))
            result = tool_model(
                await list_custom_field_groups(
                    refresh=True,
                    client=client,
                    custom_fields=fields,
                    custom_field_groups=groups,
                ),
                ListCustomFieldGroupsResponse,
            )

        assert first.cache == "ok"
        assert result.cache == "stale"
        assert result.groups[0].id == "10"


class TestListCustomFieldGroupsInput:
    def test_rejects_search(self) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"search": "Overview"})

    def test_refresh_is_only_for_a_user_reported_missing_field(self) -> None:
        doc = list_custom_field_groups.__doc__ or ""
        assert "refresh=true" in doc
        assert "missing field" in doc
        assert "layout groups" in doc.casefold() or "custom-field group" in doc
        assert "tenant" not in doc.casefold()
        for banned in (
            "capstone",
            "events",
            "readers",
            "trip outreach",
            "new product targeting",
            "1,458",
            "1458",
        ):
            assert banned not in doc.casefold()

        annotations = cast("dict[str, object]", list_custom_field_groups.__annotations__)
        field_info = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["refresh"]))
            if isinstance(item, FieldInfo)
        )
        assert field_info.description is not None
        assert "missing field" in field_info.description
        assert "search" not in without_injected_parameters(list_custom_field_groups).__annotations__
