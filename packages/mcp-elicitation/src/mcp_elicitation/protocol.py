"""The two `_meta` keys Unique's MCP client and our servers agree on (UN-27224).

A tool that asks for confirmation itself says so in its definition, so MCP Hub drops its own
generic approval for it. MCP Hub then tells each call whether a person has to confirm.
"""

from collections.abc import Mapping
from typing import cast

from fastmcp import Context

ASKS_CONFIRMATION_KEY = "unique.app/mcp-server/asks-confirmation"
SKIP_CONFIRMATION_KEY = "unique.app/mcp-server/skip-confirmation"

ASKS_CONFIRMATION: dict[str, object] = {ASKS_CONFIRMATION_KEY: True}


def confirmation_skipped(ctx: Context) -> bool:
    """Whether this `tools/call` carries `skip-confirmation: true`.

    A missing key, `false`, or any other value means a person has to confirm.
    """
    request = ctx.request_context
    if request is None:
        return False
    meta = cast("Mapping[str, object] | None", request.meta)
    return meta is not None and meta.get(SKIP_CONFIRMATION_KEY) is True
