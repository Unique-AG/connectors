"""The upstream this MCP calls, through a client of its own.

`client.py` is where it starts: an HTTP client with one `request` for any method and path. Shape
it to the upstream with the user, following the new-mcp skill's rules for coding a client, or
replace it for another protocol (SOAP, gRPC, a vendor SDK). Keep these four names whatever is
behind them, so the server and the contexts read the same way in every MCP.
"""

from mcp_skeleton.upstream.client import open_upstream
from mcp_skeleton.upstream.client import Upstream
from mcp_skeleton.upstream.client import UpstreamError
from mcp_skeleton.upstream.settings import UpstreamSettings

__all__ = ["Upstream", "UpstreamError", "UpstreamSettings", "open_upstream"]
