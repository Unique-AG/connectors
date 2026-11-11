"""`qcc_search` — resolve a fuzzy company name / registration number to QCC
identifiers. The first step of every report: the returned `qccCode` is the id
the report tools take."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from qcc_mcp.client import QccClient

_DESCRIPTION = """\
Search CN company registries by name or Business Registration Number (BRN) and \
return matching entities, each with its `qccCode` (the identifier the report \
tools require), `regNo`, and English/Chinese names. Call this first to resolve \
which exact legal entity is meant, then pass the chosen `qccCode` onward. \
CN mainland only; a Cayman/HK parent is a different jurisdiction. Max 20 results.\
"""


def register(mcp: FastMCP, client: QccClient) -> None:
    @mcp.tool(name="qcc_search", title="QCC entity search", description=_DESCRIPTION)
    async def qcc_search(search_term: str, region_code: str = "CN") -> list[dict[str, Any]]:
        return await asyncio.to_thread(client.search, search_term, region_code)

    @mcp.tool(name="qcc_search_person", title="QCC person search",
              description="Resolve a person by name plus their associated company name to a "
                          "`personKeyNo`, used by the executive report.")
    async def qcc_search_person(name: str, corp_name: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(client.search_person, name, corp_name)
