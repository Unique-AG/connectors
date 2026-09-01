"""Holding a With Intelligence session per authenticated user, and handing out its token."""

from with_intelligence_mcp.features.vendor_session.caller_vendor_session import (
    CallerVendorSession,
)
from with_intelligence_mcp.features.vendor_session.dependencies import (
    get_vendor_session_registry,
    get_with_intelligence_client,
)
from with_intelligence_mcp.features.vendor_session.vendor_session_registry import (
    MAX_TRACKED_SUBJECTS,
    VendorSessionRegistry,
)

__all__ = [
    "MAX_TRACKED_SUBJECTS",
    "CallerVendorSession",
    "VendorSessionRegistry",
    "get_vendor_session_registry",
    "get_with_intelligence_client",
]
