# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

# operationIds served as tools straight from the spec: the MCP's first version. Promote one
# to a tool of our own by removing it here, as mcp-architecture's ARCHITECTURE.md describes.
# Every other one is hidden.
EXPOSED: list[str] = [
    "searchAssets",
    "getDailyMeta",
    "getDailyPrices",
    "getIexTopOfBook",
    "listNews",
    "getForexTopOfBook",
    "getCryptoTopOfBook",
    "getCryptoPrices",
    "getFundamentalsMeta",
    "getFundamentalsDaily",
    "getFundamentalsStatements",
    "getTickerDistributions",
    "getTickerSplits",
]
