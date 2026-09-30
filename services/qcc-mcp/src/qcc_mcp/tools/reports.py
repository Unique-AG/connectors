"""Full-report tools — resolve a name and return a complete report in one call.
Each submits an async order and polls until the report is ready."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from qcc_mcp.client import QccClient


def register(mcp: FastMCP, client: QccClient) -> None:
    @mcp.tool(
        name="qcc_company_basic",
        title="QCC KYC Basic report",
        description="Full KYC Basic report for a CN company (name or BRN): company profile, share "
                    "capital, shareholders, officers, headquarters, branches. Resolves the name and "
                    "returns everything in one call.",
    )
    async def qcc_company_basic(company: str, region_code: str = "CN") -> dict[str, Any]:
        return await asyncio.to_thread(client.kyc_basic, company, region_code)

    @mcp.tool(
        name="qcc_ubo_report",
        title="QCC UBO report",
        description="Full UBO report for a CN company: everything in KYC Basic PLUS subsidiaries, "
                    "affiliates, and `UBOInfo` — the ultimate beneficial owner(s) with the ownership "
                    "chain and percentages. This is the beneficial-ownership evidence other CN "
                    "registries do not publish. Note: subsidiaries/affiliates are what the company "
                    "OWNS (outbound), not its owners.",
    )
    async def qcc_ubo_report(company: str, region_code: str = "CN") -> dict[str, Any]:
        return await asyncio.to_thread(client.kyc_ubo, company, region_code)

    @mcp.tool(
        name="qcc_executive_report",
        title="QCC Executive (person) report",
        description="Executive report for an individual, identified by their name plus an associated "
                    "company name. Returns the person's roles, shareholdings, and related officers.",
    )
    async def qcc_executive_report(name: str, corp_name: str) -> dict[str, Any]:
        return await asyncio.to_thread(client.kyc_executive, name, corp_name)
