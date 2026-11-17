# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

# operationIds served as tools straight from the spec: the MCP's first version. Promote one
# to a tool of our own by removing it here, as mcp-architecture's ARCHITECTURE.md describes.
# Every other one is hidden.
EXPOSED: list[str] = ["resolvePermanentId"]
