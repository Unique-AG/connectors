"""Obtaining and holding a With Intelligence session, and handing its token to the transport."""

from with_intelligence_mcp.features.vendor_session.dependencies import (
    get_service_account_session,
    get_with_intelligence_client,
)
from with_intelligence_mcp.features.vendor_session.service_account_session import (
    SERVICE_ACCOUNT_SUBJECT,
    ServiceAccountSession,
)

__all__ = [
    "SERVICE_ACCOUNT_SUBJECT",
    "ServiceAccountSession",
    "get_service_account_session",
    "get_with_intelligence_client",
]
