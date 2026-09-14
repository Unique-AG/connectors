"""Build JSON:API request bodies for activity writes.

`resourceType` is the plural name, not Bean casing. Identity pointers are
relationships; parent pointers are attributes.
"""

from datetime import date, datetime
from typing import Literal, cast
from urllib.parse import quote

from pydantic import BaseModel

from backstop_mcp.features.entity_types import SearchType

_TitleKey = Literal["title", "name"]
_DescriptionKey = Literal["description", "details"]


def omit_none_values(values: dict[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}


def isoformat(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def activity_base_attributes(
    activity: BaseModel,
    *,
    title_key: _TitleKey = "title",
    description_key: _DescriptionKey = "description",
    default_effective_today: bool = False,
) -> dict[str, object | None]:
    """Wire attributes every activity kind shares: title, description, effectiveDate.

    Callers spread this and add kind-specific keys. Tasks pass `title_key="name"` and
    `description_key="details"`. Notes and documents that require a date pass
    `default_effective_today=True`.
    """
    dumped = activity.model_dump()
    fields = type(activity).model_fields
    attributes: dict[str, object | None] = {}
    if "title" in fields:
        attributes[title_key] = cast("str | None", dumped["title"])
    if "description" in fields:
        attributes[description_key] = cast("str | None", dumped["description"])
    if "effective_date" in fields:
        effective_date = cast("date | datetime | None", dumped["effective_date"])
        if effective_date is None and default_effective_today:
            effective_date = date.today()
        attributes["effectiveDate"] = isoformat(effective_date)
    return attributes


def activity_tag_relationship(
    activity: BaseModel, *, omit_empty: bool = False
) -> dict[str, object] | None:
    """`activityTags` payload, or `None` to omit the relationship key.

    Creates pass `omit_empty=True` so `()` is not sent. Updates leave `()` as a clear.
    """
    if "activity_tag_ids" not in type(activity).model_fields:
        return None
    ids = cast("tuple[str, ...] | None", activity.model_dump()["activity_tag_ids"])
    if omit_empty:
        ids = ids or None
    return relationship_data("activity-tags", ids)


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


def relationship_data(resource_type: str, ids: tuple[str, ...] | None) -> dict[str, object] | None:
    """JSON:API relationship payload. `None` omits the key; `()` is an empty replace."""
    if ids is None:
        return None
    return {"data": [{"type": resource_type, "id": item_id} for item_id in ids]}


def json_api_create(
    *,
    resource_type: str,
    attributes: dict[str, object],
    relationships: dict[str, object] | None = None,
    resource_id: str | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {"type": resource_type}
    if resource_id is not None:
        data["id"] = resource_id
    data["attributes"] = attributes
    if relationships:
        data["relationships"] = relationships
    return {"data": data}


def json_api_update(
    *,
    resource_type: str,
    resource_id: str,
    attributes: dict[str, object],
    relationships: dict[str, object] | None = None,
) -> dict[str, object]:
    return json_api_create(
        resource_type=resource_type,
        resource_id=resource_id,
        attributes=attributes,
        relationships=relationships,
    )
