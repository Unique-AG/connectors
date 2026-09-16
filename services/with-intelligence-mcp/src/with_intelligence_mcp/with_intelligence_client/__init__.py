"""With Intelligence v3 HTTP client."""

from with_intelligence_mcp.with_intelligence_client.as_sequence import (
    SEQUENCE,
    SINGLE,
    as_sequence,
    as_single,
)
from with_intelligence_mcp.with_intelligence_client.client import (
    QueryValue,
    WithIntelligenceClient,
    as_query,
)
from with_intelligence_mcp.with_intelligence_client.credential import (
    CallerSessionProvider,
    WiCredential,
)
from with_intelligence_mcp.with_intelligence_client.errors import (
    ApiError,
    AuthenticationRejected,
    AuthError,
    NotEntitled,
    NotFound,
    RateLimited,
    Unreachable,
    WithIntelligenceError,
)
from with_intelligence_mcp.with_intelligence_client.factory import (
    REFRESH_PATH,
    SIGN_IN_PATH,
    WithIntelligenceClientFactory,
)
from with_intelligence_mcp.with_intelligence_client.pagination import Page, PageInfo
from with_intelligence_mcp.with_intelligence_client.retry import RetryPolicy
from with_intelligence_mcp.with_intelligence_client.session import WiSession
from with_intelligence_mcp.with_intelligence_client.settings import RetrySettings, TransportSettings

__all__ = [
    "REFRESH_PATH",
    "SIGN_IN_PATH",
    "ApiError",
    "AuthError",
    "CallerSessionProvider",
    "NotEntitled",
    "NotFound",
    "SEQUENCE",
    "SINGLE",
    "Page",
    "PageInfo",
    "QueryValue",
    "RateLimited",
    "RetryPolicy",
    "RetrySettings",
    "AuthenticationRejected",
    "TransportSettings",
    "Unreachable",
    "WiCredential",
    "WiSession",
    "WithIntelligenceClient",
    "WithIntelligenceClientFactory",
    "WithIntelligenceError",
    "as_query",
    "as_sequence",
    "as_single",
]
