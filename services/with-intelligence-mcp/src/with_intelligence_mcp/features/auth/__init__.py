"""WI authentication public API."""

from mcp_credential_auth import ThrottleConfig

from with_intelligence_mcp.features.auth.cleanup import cleanup_lifespan
from with_intelligence_mcp.features.auth.context import (
    NotConnectedError,
    WithIntelligenceAuthContext,
)
from with_intelligence_mcp.features.auth.crypto import load_key
from with_intelligence_mcp.features.auth.provider import WithIntelligenceOAuthProvider

__all__ = [
    "NotConnectedError",
    "ThrottleConfig",
    "WithIntelligenceAuthContext",
    "WithIntelligenceOAuthProvider",
    "cleanup_lifespan",
    "load_key",
]
