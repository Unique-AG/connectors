"""WI authentication public API."""

from with_intelligence_mcp.features.auth.cleanup import cleanup_lifespan, purge_expired_auth_rows
from with_intelligence_mcp.features.auth.context import (
    NotConnectedError,
    WithIntelligenceAuthContext,
)
from with_intelligence_mcp.features.auth.crypto import (
    InvalidSessionEnvelopeError,
    load_key,
)
from with_intelligence_mcp.features.auth.provider import WithIntelligenceOAuthProvider
from with_intelligence_mcp.features.auth.throttle import ThrottleConfig

__all__ = [
    "InvalidSessionEnvelopeError",
    "NotConnectedError",
    "ThrottleConfig",
    "WithIntelligenceAuthContext",
    "WithIntelligenceOAuthProvider",
    "cleanup_lifespan",
    "load_key",
    "purge_expired_auth_rows",
]
