"""Small domain-free helpers, importable from anywhere in the package."""

from backstop_mcp.utils.array import first_item
from backstop_mcp.utils.date_window import date_window
from backstop_mcp.utils.parse_activity_handle import ParsedActivityHandle, parse_activity_handle
from backstop_mcp.utils.presence_flags import presence_flags
from backstop_mcp.utils.sample_ids import sample_ids

__all__ = [
    "ParsedActivityHandle",
    "date_window",
    "first_item",
    "parse_activity_handle",
    "presence_flags",
    "sample_ids",
]
