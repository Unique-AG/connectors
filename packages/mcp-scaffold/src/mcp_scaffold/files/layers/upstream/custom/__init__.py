"""The upstream this MCP calls, through a client written by hand.

Its protocol (SOAP, gRPC, a vendor SDK...) is not OpenAPI or plain HTTP. Expose the same
interface the other upstream kinds do, so the server and the contexts read the same way in
every MCP: `Upstream` (the client the contexts receive), `UpstreamError` (a ToolError),
`UpstreamSettings`, and `open_upstream(settings)`, an async context manager the server lifespan
opens. Then register it in `mcp/server.py` and `mcp/dependencies.py`.
"""

__all__: list[str] = []
