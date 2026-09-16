"""WI authentication public API."""

from mcp_credential_auth import LoginThrottleConfig

from with_intelligence_mcp.features.auth.cleanup import cleanup_lifespan
from with_intelligence_mcp.features.auth.context import (
    NotConnectedError,
    WithIntelligenceAuthContext,
)
from with_intelligence_mcp.features.auth.crypto import load_key
from with_intelligence_mcp.features.auth.provider import WithIntelligenceOAuthProvider

__all__ = [
    "NotConnectedError",
    "LoginThrottleConfig",
    "WithIntelligenceAuthContext",
    "WithIntelligenceOAuthProvider",
    "cleanup_lifespan",
    "load_key",
]
