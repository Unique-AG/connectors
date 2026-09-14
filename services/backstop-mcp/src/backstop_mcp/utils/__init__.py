"""Small domain-free helpers, importable from anywhere in the package."""

from backstop_mcp.utils.array import first_item
from backstop_mcp.utils.parse_activity_handle import ParsedActivityHandle, parse_activity_handle

__all__ = ["ParsedActivityHandle", "first_item", "parse_activity_handle"]
