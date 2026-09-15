from functools import lru_cache

from fastmcp.dependencies import Depends

from with_intelligence_mcp.dependencies import (
    get_auth_context,
    get_with_intelligence_client_factory,
)
from with_intelligence_mcp.features.wi_session.caller_wi_session import CallerWiSession
from with_intelligence_mcp.features.wi_session.wi_session_cache import WiSessionCache
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


@lru_cache(maxsize=1)
def get_wi_session_cache() -> WiSessionCache:
    return WiSessionCache(get_with_intelligence_client_factory())


def get_with_intelligence_client(
    cache: WiSessionCache = Depends(get_wi_session_cache),
) -> WithIntelligenceClient:
    """A client authenticated as the in-flight MCP caller."""
    session = CallerWiSession(cache, get_auth_context())
    return get_with_intelligence_client_factory().for_session(session)
