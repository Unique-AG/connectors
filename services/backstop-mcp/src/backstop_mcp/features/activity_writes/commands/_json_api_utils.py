"""Activity-specific write payload helpers.

JSON:API envelopes (`json_api_create`, `relationship_data`, …) live on `backstop_client`.
"""

from datetime import date, datetime
from typing import Literal, cast
from urllib.parse import quote

from pydantic import BaseModel

from backstop_mcp.backstop_client import isoformat, relationship_data
from backstop_mcp.features.entity_types import SearchType

_TitleKey = Literal["title", "name"]
_DescriptionKey = Literal["description", "details"]


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
