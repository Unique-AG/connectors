"""Build JSON:API request bodies for activity writes.

`resourceType` is the plural name, not Bean casing. Identity pointers are
relationships; parent pointers are attributes.
"""

from datetime import date, datetime
from urllib.parse import quote

from backstop_mcp.features.entity_types import SearchType


def omit_none_values(values: dict[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}


def isoformat(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def party_resource_link(*, party_id: str, search_type: SearchType) -> dict[str, object]:
    """A parent pointer for `attachedTo` / `regarding` / `resources` / `linkedResources`.

    `resourceType` is the plural resource name, not Bean casing. Backstop normalizes
    aliasing collections itself — an `employees` link comes back as `people`.
    """
    return {
        "resourceId": party_id,
        "resourceType": search_type,
        "resourceLink": f"/{search_type}/{quote(party_id, safe='')}",
    }


def secondary_resource_link(
    *,
    party_id: str,
    secondary_party_id: str | None,
    secondary_search_type: SearchType | None,
) -> dict[str, object] | None:
    """The second party's link, or `None` when there is none or it repeats the parent.

    Backstop silently drops a `linkedResources` entry that is already the parent, so the
    record would come back with `linkedResources: []` and no error. Filtering here keeps
    the request honest about what it asked for.
    """
    if secondary_party_id is None or secondary_search_type is None:
        return None
    if secondary_party_id == party_id:
        return None
    return party_resource_link(party_id=secondary_party_id, search_type=secondary_search_type)


def relationship_data(resource_type: str, ids: tuple[str, ...]) -> dict[str, object] | None:
    if not ids:
        return None
    return {"data": [{"type": resource_type, "id": item_id} for item_id in ids]}


def relationship_replace(
    resource_type: str, ids: tuple[str, ...] | None
) -> dict[str, object] | None:
    """JSON:API relationship replace. `None` omits the key; `()` clears it."""
    if ids is None:
        return None
    return {"data": [{"type": resource_type, "id": item_id} for item_id in ids]}


def json_api_update(
    *,
    resource_type: str,
    resource_id: str,
    attributes: dict[str, object],
    relationships: dict[str, object] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "type": resource_type,
        "id": resource_id,
        "attributes": attributes,
    }
    if relationships:
        data["relationships"] = relationships
    return {"data": data}


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
