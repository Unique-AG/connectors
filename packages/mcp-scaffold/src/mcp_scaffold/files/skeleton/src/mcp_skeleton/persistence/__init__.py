"""Storage the MCP owns: a database, Redis, a key-value store. Empty until an MCP needs one.

Expose a store's interface here, never its driver: contexts depend on what is stored, not where.
"""

__all__: list[str] = []
