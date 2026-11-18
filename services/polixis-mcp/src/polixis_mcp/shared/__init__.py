# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

"""What more than one layer uses, below every layer but `telemetry`.

- `contracts/`: the types two layers agree on without importing each other, as `upstream` and
  `persistence` cannot. Interfaces and value models only, such as a store's protocol or the
  credentials a signed-in user's calls carry; what implements them lives in the layer above.
  import-linter keeps storage, HTTP and crypto libraries out of it.
- `utils/`: helpers, such as a formatter or a date rule.

Each is empty until two layers need it: what one layer uses stays in that layer. Nothing here
imports fastmcp, MCP or a layer above. Expose each name here, never the module it lives in.
"""

from polixis_mcp.shared.contracts import CachedAnswer
from polixis_mcp.shared.contracts import ResponseCache

__all__ = ["CachedAnswer", "ResponseCache"]
