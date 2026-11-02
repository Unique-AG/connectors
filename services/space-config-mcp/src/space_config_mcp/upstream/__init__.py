"""The upstream this MCP calls: unique_sdk Space and Module resources.

Keep these four names whatever is behind them, so the server and the contexts read the same way
in every MCP.
"""

from space_config_mcp.upstream.client import open_upstream
from space_config_mcp.upstream.client import Upstream
from space_config_mcp.upstream.client import UpstreamError
from space_config_mcp.upstream.settings import UpstreamSettings

__all__ = ["Upstream", "UpstreamError", "UpstreamSettings", "open_upstream"]
