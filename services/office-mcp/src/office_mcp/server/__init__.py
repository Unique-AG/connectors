"""Expose features over MCP. Imports freely from features/; the reverse is a layering violation."""

from office_mcp.server.readiness import ready_response

__all__ = ["ready_response"]
