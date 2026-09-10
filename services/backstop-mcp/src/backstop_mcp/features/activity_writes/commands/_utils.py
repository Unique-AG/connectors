"""JSON:API create/update envelopes and Backstop resource-link objects for activity writes."""

from datetime import date, datetime
from typing import Literal
from urllib.parse import quote

from fastmcp.exceptions import ToolError

from backstop_mcp.features.entity_types import SearchType, map_search_type_to_resource_type_bean

type ActivityKind = Literal["note", "meeting", "call", "task", "email", "document"]
type ActivityCollection = Literal["notes", "meeting-or-calls", "tasks", "emails", "documents"]

_COLLECTIONS: dict[ActivityKind, ActivityCollection] = {
    "note": "notes",
    "meeting": "meeting-or-calls",
    "call": "meeting-or-calls",
    "task": "tasks",
    "email": "emails",
    "document": "documents",
}
_COMPOSITE_TYPES: dict[ActivityKind, frozenset[str]] = {
    "note": frozenset({"notes"}),
    "meeting": frozenset({"meeting-or-calls"}),
    "call": frozenset({"meeting-or-calls"}),
    "task": frozenset({"tasks"}),
    "email": frozenset({"emails", "email"}),
    "document": frozenset({"documents"}),
}
_ALL_COMPOSITE_PREFIXES: frozenset[str] = frozenset(
    prefix for prefixes in _COMPOSITE_TYPES.values() for prefix in prefixes
)


def omit_none_values(values: dict[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}


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


def relationship_replace(
    resource_type: str, ids: tuple[str, ...] | None
) -> dict[str, object] | None:
    """JSON:API relationship replace. `None` omits the key; `()` clears it."""
    if ids is None:
        return None
    return {"data": [{"type": resource_type, "id": item_id} for item_id in ids]}


def activity_collection(kind: ActivityKind) -> ActivityCollection:
    return _COLLECTIONS[kind]


def activity_resource_id(*, kind: ActivityKind, activity_id: str) -> str:
    """Bare Backstop id, or a history composite whose type matches `kind`."""
    handle = activity_id.strip()
    if not handle or "/" in handle:
        raise ToolError(
            f"activity_id {activity_id!r} is not a Backstop activity id. Echo an id from a "
            + "create, a search_activities row, or a get_activity_history handle."
        )
    resource_type, separator, resource_id = handle.rpartition("_")
    if separator and resource_type and resource_id:
        if resource_type in _COMPOSITE_TYPES[kind]:
            return resource_id
        if resource_type in _ALL_COMPOSITE_PREFIXES:
            raise ToolError(
                f"{activity_id!r} is a {resource_type} handle; kind={kind} targets "
                + f"/{activity_collection(kind)}."
            )
    return handle


def activity_target(*, kind: ActivityKind, activity_id: str) -> tuple[str, str, ActivityCollection]:
    """`(/{collection}/{id}, id, collection)` for a PATCH or DELETE."""
    resource_id = activity_resource_id(kind=kind, activity_id=activity_id)
    collection = activity_collection(kind)
    return f"/{collection}/{quote(resource_id, safe='')}", resource_id, collection


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
