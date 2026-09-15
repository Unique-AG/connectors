"""Drill-down tools — submit one order, then read individual sections on demand.
Use these instead of a full report when you want a targeted section, or the full
(paginated) shareholder/officer list that the bundled report caps at 200."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from qcc_mcp.client import SECTIONS, QccClient

_SECTION_NAMES = ", ".join(SECTIONS)


def register(mcp: FastMCP, client: QccClient) -> None:
    @mcp.tool(
        name="qcc_submit_ubo_order",
        title="QCC submit UBO order",
        description="Resolve a CN company and submit a UBO order, returning its `order_no`. "
                    "Pass that order_no to `qcc_get_section` to read individual sections on demand.",
    )
    async def qcc_submit_ubo_order(company: str, region_code: str = "CN") -> dict[str, str]:
        order_no = await asyncio.to_thread(client.submit_ubo, company, region_code)
        return {"order_no": order_no}

    @mcp.tool(
        name="qcc_get_section",
        title="QCC get report section",
        description=f"Read one section of a submitted order by `order_no`. Sections: {_SECTION_NAMES}. "
                    "`shareholders`/`officers` paginate via `page` (1-based). Object sections return "
                    "an object; list sections return an array.",
    )
    async def qcc_get_section(section: str, order_no: str, page: int | None = None) -> Any:
        return await asyncio.to_thread(client.get_section, section, order_no, page)
