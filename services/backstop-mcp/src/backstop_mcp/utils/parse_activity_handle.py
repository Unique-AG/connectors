from typing import NamedTuple

from fastmcp.exceptions import ToolError

__all__ = ["ParsedActivityHandle", "parse_activity_handle"]


class ParsedActivityHandle(NamedTuple):
    """A `{resourceType}_{resourceId}` split, or a bare id (`resource_type` is then None)."""

    resource_type: str | None
    resource_id: str

    @property
    def handle(self) -> str:
        if self.resource_type is None:
            return self.resource_id
        return f"{self.resource_type}_{self.resource_id}"


def parse_activity_handle(activity_id: str) -> ParsedActivityHandle:
    """Split on the last underscore. Raises when the value is empty after strip.

    Resource types can carry hyphens (`meeting-or-calls`); ids are the tail. A value with
    no underscore is a bare search-row / create-echo id. Callers apply their own rules
    (reject `email_*`, require `kind` to match, forbid `/`).
    """
    handle = activity_id.strip()
    if not handle:
        raise ToolError(
            f"{activity_id!r} is not a valid activity_id. Echo an id from a create, a "
            + "search_activities row, or a get_activity_history handle."
        )
    resource_type, separator, resource_id = handle.rpartition("_")
    if separator and resource_type and resource_id:
        return ParsedActivityHandle(resource_type, resource_id)
    return ParsedActivityHandle(None, handle)
