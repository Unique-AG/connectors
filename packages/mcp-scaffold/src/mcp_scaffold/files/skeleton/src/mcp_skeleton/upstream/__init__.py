"""The system the MCP fronts: an API, a vendor SDK, another service. Empty until an MCP calls one.

Expose its client here as `Upstream`, `UpstreamError`, `UpstreamSettings` and `open_upstream`,
never the module it lives in: contexts import the layer, not its files.
"""

__all__: list[str] = []
