"""Remap Backstop write errors the raw `ToolError` does not make actionable.

Unknown-tag `404`s keep Backstop's `title` and gain a `list_activity_tags` pointer.
Validation titles pass through on the original `BackstopApiError`. `413` remapping stays
on `attach_file` so it is not the same message as the local size cap.
"""

from typing import Never

from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopApiError

_TAG_POINTER = "Look up valid ids with list_activity_tags. Tags are never created automatically."


def reraise_activity_write_error(exc: BackstopApiError) -> Never:
    if _is_unknown_activity_tag(exc):
        raise ToolError(f"{exc.detail} {_TAG_POINTER}") from exc
    raise exc


def _is_unknown_activity_tag(exc: BackstopApiError) -> bool:
    if exc.status_code != 404:
        return False
    texts = [exc.detail, exc.code or ""]
    texts.extend(error.title or "" for error in exc.errors)
    texts.extend(error.detail or "" for error in exc.errors)
    haystack = " ".join(texts).casefold()
    return "activity-tags" in haystack or "activity-tag" in haystack
