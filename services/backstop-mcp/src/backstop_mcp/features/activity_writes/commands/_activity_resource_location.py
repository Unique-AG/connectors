"""Where an activity lives, resolved from a `kind` and a caller-supplied id.

Routing, not body building — nothing here appears in a request payload, which is why it is
separate from `_json_api_utils`. `update_activity` and `delete_activity` are the only
callers; a create already knows its own collection.

The id arrives in either of two spellings. `get_activity_history` hands out a composite
`{resourceType}_{resourceId}` handle (`notes_26018215`, `meeting-or-calls_76537547`), while
a create echo and a `search_activities` row are already bare. A composite whose type
contradicts `kind` is rejected rather than stripped and sent to the wrong collection.
`ResourceIdentifierDto.from_activity_id` in `features/activity_history` splits the same
handle for the read path; this is the write-side counterpart, and it also has to know the
collection because the target is `/{collection}/{id}` rather than one detail endpoint.
"""

from typing import ClassVar, Literal, Self
from urllib.parse import quote

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict

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


def _extract_resource_id_from_activity_id(*, kind: ActivityKind, activity_id: str) -> str:
    """The bare Backstop id, or a history composite's id when its type matches `kind`."""
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
                + f"/{_COLLECTIONS[kind]}."
            )
    return handle


class ActivityResourceLocation(BaseModel):
    """The collection an activity lives in, its bare id, and the path to PATCH or DELETE.

    All three travel together: a command needs `path` for the request, `resource_id` for
    the JSON:API `data.id`, and `collection` for both `data.type` and the response's
    `resource_type`. Returning them as one value keeps a caller from pairing the id of one
    record with the path of another.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    path: str
    resource_id: str
    collection: ActivityCollection

    @classmethod
    def from_activity_id(cls, *, kind: ActivityKind, activity_id: str) -> Self:
        """Resolve a create echo, a search row, or a history handle to one location."""
        resource_id = _extract_resource_id_from_activity_id(kind=kind, activity_id=activity_id)
        collection = _COLLECTIONS[kind]
        return cls(
            path=f"/{collection}/{quote(resource_id, safe='')}",
            resource_id=resource_id,
            collection=collection,
        )
