"""Map our `kind` to the Backstop collection, and check the handle belongs there."""

from typing import Literal

from fastmcp.exceptions import ToolError

from backstop_mcp.utils import ParsedActivityHandle

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


def extract_collection(
    handle: ParsedActivityHandle, *, kind: ActivityKind
) -> tuple[ActivityCollection, str]:
    """The API collection for `kind`, and the bare id to PATCH or DELETE.

    Rejects a `/` in the handle and a history prefix that does not match `kind`. Collection
    comes from `kind`, not the handle — a bare create-echo id has no resource type.
    """
    if "/" in handle.handle:
        raise ToolError(
            f"activity_id {handle.handle!r} is not a Backstop activity id. Echo an id from a "
            + "create, a search_activities row, or a get_activity_history handle."
        )
    if handle.resource_type is None or handle.resource_type in _COMPOSITE_TYPES[kind]:
        resource_id = handle.resource_id
    elif handle.resource_type in _ALL_COMPOSITE_PREFIXES:
        raise ToolError(
            f"{handle.handle!r} is a {handle.resource_type} handle; kind={kind} targets "
            + f"/{_COLLECTIONS[kind]}."
        )
    else:
        resource_id = handle.handle
    return _COLLECTIONS[kind], resource_id
