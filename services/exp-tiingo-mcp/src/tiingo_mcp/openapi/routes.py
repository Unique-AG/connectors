from fastmcp.server.providers.openapi import MCPType

from tiingo_mcp.helpers.openapi import mcp_name, route_map

# operationIds from the spec and how they are exposed as-is. Everything else is hidden.
# Resources are for GETs without query params only.
EXPOSED: dict[str, MCPType] = {
    **dict.fromkeys(
        [
            "testConnection",
            "searchAssets",
            "getDailyMeta",
            "getFundamentalsMeta",
            "getIexTopOfBook",
            "getCryptoPrices",
            "getCryptoTopOfBook",
            "getForexPrices",
            "getForexTopOfBook",
        ],
        MCPType.TOOL,
    ),
    **dict.fromkeys(["getFundamentalsDefinitions"], MCPType.RESOURCE),
}

# Operations the tools call through `OperationClient`, so they are not served as generated tools.
CLIENT_BACKED = ["getDailyPrices", "getFundamentalsStatements", "getFundamentalsDaily"]

# Operations whose responses get a generated model.
RESPONSE_MODELS = [*EXPOSED, *CLIENT_BACKED]

MCP_NAMES: dict[str, str] = {operation_id: mcp_name(operation_id) for operation_id in EXPOSED}

route_map_fn = route_map(EXPOSED)
