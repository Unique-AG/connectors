"""Expose features over MCP. Imports freely from features/; the reverse is a layering violation.

A future `runtime` module holds process-wide services. FastMCP calls tool functions with a
plain signature, so it denies them constructor injection.
"""
