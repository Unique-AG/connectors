"""MCP server concerns: how the features are exposed, not what they do.

Server instructions and the hand-written `TOOLS` list in `tools/registry.py`. `create_app`
registers from that list. Adding a tool is two edits; rule 7 in `tests/test_layering.py`
fails the suite if the second is forgotten. The tools themselves live under
`features/<f>/tools/`.

This side may import freely from `features/`. The reverse is a layering violation — see
`features/__init__.py`.
"""
