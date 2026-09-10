"""JSON:API create envelopes and Backstop resource-link objects for activity POSTs."""

from datetime import date, datetime
from urllib.parse import quote

from backstop_mcp.features.entity_types import SearchType, map_search_type_to_resource_type_bean

_SYSTEM_USER_BEAN = "SystemUserBean"


def compact_attributes(attributes: dict[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in attributes.items() if value is not None}


def isoformat(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def party_resource_link(*, party_id: str, search_type: SearchType) -> dict[str, object]:
    return {
        "resourceId": party_id,
        "resourceType": map_search_type_to_resource_type_bean(search_type),
        "resourceLink": f"/{search_type}/{quote(party_id, safe='')}",
    }


def system_user_resource_link(user_id: str) -> dict[str, object]:
    return {
        "resourceId": user_id,
        "resourceType": _SYSTEM_USER_BEAN,
        "resourceLink": f"/system-users/{quote(user_id, safe='')}",
    }


def secondary_resource_link(
    *,
    party_id: str,
    secondary_party_id: str | None,
    secondary_search_type: SearchType | None,
) -> dict[str, object] | None:
    if secondary_party_id is None or secondary_search_type is None:
        return None
    if secondary_party_id == party_id:
        return None
    return party_resource_link(party_id=secondary_party_id, search_type=secondary_search_type)


def relationship_data(resource_type: str, ids: tuple[str, ...]) -> dict[str, object] | None:
    if not ids:
        return None
    return {"data": [{"type": resource_type, "id": item_id} for item_id in ids]}


def json_api_create(
    *,
    resource_type: str,
    attributes: dict[str, object],
    relationships: dict[str, object] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {"type": resource_type, "attributes": attributes}
    if relationships:
        data["relationships"] = relationships
    return {"data": data}
