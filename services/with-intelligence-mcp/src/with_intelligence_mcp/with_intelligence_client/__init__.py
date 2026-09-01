"""HTTP transport for the With Intelligence v3 REST API.

Infrastructure the features consume: it must not import `features/` or `config`
(`tests/test_layering.py`). A type both sides need lives here, with `features/` supplying the
implementation — see `CallerSession`.
"""

from with_intelligence_mcp.with_intelligence_client.as_sequence import SEQUENCE, as_sequence
from with_intelligence_mcp.with_intelligence_client.client import (
    QueryValue,
    WithIntelligenceClient,
    as_query,
    narrow_dict,
)
from with_intelligence_mcp.with_intelligence_client.credential import (
    CallerSession,
    VendorCredential,
)
from with_intelligence_mcp.with_intelligence_client.errors import (
    ApiError,
    AuthError,
    NotEntitled,
    NotFound,
    RateLimited,
    SignInFailed,
    Unreachable,
    WithIntelligenceError,
)
from with_intelligence_mcp.with_intelligence_client.factory import (
    REFRESH_PATH,
    SIGN_IN_PATH,
    WithIntelligenceClientFactory,
)
from with_intelligence_mcp.with_intelligence_client.pagination import Page, PageInfo, parse_page
from with_intelligence_mcp.with_intelligence_client.retry import RetryPolicy
from with_intelligence_mcp.with_intelligence_client.session import VendorSession
from with_intelligence_mcp.with_intelligence_client.settings import RetrySettings, TransportSettings

__all__ = [
    "REFRESH_PATH",
    "SIGN_IN_PATH",
    "ApiError",
    "AuthError",
    "CallerSession",
    "NotEntitled",
    "NotFound",
    "SEQUENCE",
    "Page",
    "PageInfo",
    "QueryValue",
    "RateLimited",
    "RetryPolicy",
    "RetrySettings",
    "SignInFailed",
    "TransportSettings",
    "Unreachable",
    "VendorCredential",
    "VendorSession",
    "WithIntelligenceClient",
    "WithIntelligenceClientFactory",
    "WithIntelligenceError",
    "as_query",
    "as_sequence",
    "narrow_dict",
    "parse_page",
]
