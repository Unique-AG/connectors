"""MCP server concerns: how the features are exposed, not what they do.

Tool declarations (`tools`), FastMCP/ASGI middleware (`middleware`), and the process-wide
service holder (`runtime`) that exists only because FastMCP calls tool functions with a plain
signature and so denies them constructor injection. `tools` and `middleware` are still empty in
this PR — they fill in once `features/custom_fields` and `features/party_resolver` land.

This side may import freely from `features/`. The reverse is a layering violation — see
`features/__init__.py`.
"""
