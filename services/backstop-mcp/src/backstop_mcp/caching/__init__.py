"""Process-wide in-memory cache primitives.

`CachedValue` is one TTL'd, single-flight slot. Catalogs and opportunity stages compose it;
`backstop_client` is the HTTP transport and does not belong here.
"""

from backstop_mcp.caching.cached_value import CachedValue, CacheFreshness, CacheSource

__all__ = ["CacheFreshness", "CacheSource", "CachedValue"]
