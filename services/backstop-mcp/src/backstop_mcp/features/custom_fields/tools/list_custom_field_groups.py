from collections.abc import Mapping
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.custom_fields import (
    CustomFieldDefinitionDto,
    CustomFieldGroupMemberResponse,
    CustomFieldGroupResponse,
    CustomFieldGroupsService,
    CustomFieldsService,
    ListCustomFieldGroupsResponse,
    get_custom_field_groups_service,
    get_custom_fields_service,
)


def _join_id(resource_id: str) -> int | None:
    try:
        return int(resource_id)
    except ValueError:
        return None


def _membership_by_group_id(
    catalog: Mapping[str, CustomFieldDefinitionDto],
) -> dict[int, list[CustomFieldGroupMemberResponse]]:
    by_group: dict[int, list[CustomFieldGroupMemberResponse]] = {}
    for definition in catalog.values():
        group_id = definition.group_id
        if group_id is None:
            continue
        member = CustomFieldGroupMemberResponse.from_definition(definition)
        members = by_group.get(group_id)
        if members is None:
            by_group[group_id] = [member]
        else:
            members.append(member)
    return by_group


def _cache_status(*statuses: Literal["ok", "stale"]) -> Literal["ok", "stale"]:
    return "stale" if "stale" in statuses else "ok"


def _members_for(
    group_id: str, membership: dict[int, list[CustomFieldGroupMemberResponse]]
) -> list[CustomFieldGroupMemberResponse]:
    join_id = _join_id(group_id)
    if join_id is None:
        return []
    return membership.get(join_id, [])


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_custom_field_groups(
    refresh: Annotated[
        bool,
        Field(description="Do not pass true unless the user reports a missing field."),
    ] = False,
    custom_fields: CustomFieldsService = Depends(get_custom_fields_service),
    custom_field_groups: CustomFieldGroupsService = Depends(get_custom_field_groups_service),
) -> ListCustomFieldGroupsResponse:
    """List Backstop layout groups (tabs and sections) with the fields that sit in each.

    Use when you need the standard Backstop custom-field group catalog: group ids, names,
    full_path_name tab-to-section segments, parent {id, name, parent_id}, and field membership
    joined by group_id from the definition catalog. Instance tab and section names come back as
    data. Pass refresh=true only when the user reports a missing field.
    """
    groups, groups_cache = await custom_field_groups.get(refresh=refresh)
    definitions, definitions_cache = await custom_fields.get(refresh=refresh)
    membership = _membership_by_group_id(definitions)
    return ListCustomFieldGroupsResponse(
        cache=_cache_status(groups_cache, definitions_cache),
        groups=[
            CustomFieldGroupResponse.from_group(group, _members_for(group.id, membership))
            for group in groups.values()
        ],
    )
