"""Compose the FastMCP app: build the client from config, register the tools.

Deliberately lean — no OAuth, no database, no OpenTelemetry. QCC needs only a
signed API key, so the whole composition is: config -> client -> tools.
"""

from __future__ import annotations

from fastmcp import FastMCP

from qcc_mcp.client import QccClient
from qcc_mcp.config import QccConfig
from qcc_mcp.tools import register_tools

_INSTRUCTIONS = """\
QCC KYC/KYB connector — CN (mainland China) company registry and Ultimate \
Beneficial Owner data. Workflow: call `qcc_search` to resolve a name to a \
`qccCode`, then a report tool (`qcc_ubo_report` for beneficial ownership, \
`qcc_company_basic` for registry facts). For a targeted section or a full \
paginated shareholder/officer list, use `qcc_submit_ubo_order` then \
`qcc_get_section`. Reports are compiled asynchronously; the tools poll until \
ready. CN mainland only — a Cayman/HK parent is a different jurisdiction.\
"""


def create_app(config: QccConfig | None = None) -> FastMCP:
    config = config or QccConfig()  # pyright: ignore[reportCallIssue] — fields come from env
    client = QccClient(config)
    mcp = FastMCP(name="qcc-mcp", instructions=_INSTRUCTIONS)
    register_tools(mcp, client)
    return mcp
