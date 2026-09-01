from functools import lru_cache

from fastmcp.dependencies import Depends

from with_intelligence_mcp.dependencies import (
    get_auth_context,
    get_with_intelligence_client_factory,
)
from with_intelligence_mcp.features.vendor_session.caller_vendor_session import (
    CallerVendorSession,
)
from with_intelligence_mcp.features.vendor_session.vendor_session_registry import (
    VendorSessionRegistry,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


@lru_cache(maxsize=1)
def get_vendor_session_registry() -> VendorSessionRegistry:
    return VendorSessionRegistry(get_with_intelligence_client_factory())


def get_with_intelligence_client(
    registry: VendorSessionRegistry = Depends(get_vendor_session_registry),
) -> WithIntelligenceClient:
    """A client authenticated as the in-flight MCP caller."""
    session = CallerVendorSession(registry, get_auth_context())
    return get_with_intelligence_client_factory().for_session(session)
