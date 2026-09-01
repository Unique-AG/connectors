"""Bridging MCP OAuth to a With Intelligence credential: login, token lifetime, encryption.

The public surface: what `create_app` wires together and what other features need to resolve
the calling user. `credential_store`, the login form and the CSRF helpers are this package's own
business. Enforced by `tests/test_layering.py`.
"""

from with_intelligence_mcp.features.auth.cleanup import cleanup_lifespan, purge_expired_auth_rows
from with_intelligence_mcp.features.auth.context import (
    NotConnectedError,
    WithIntelligenceAuthContext,
)
from with_intelligence_mcp.features.auth.crypto import (
    InvalidCredentialEnvelopeError,
    load_key,
)
from with_intelligence_mcp.features.auth.provider import WithIntelligenceOAuthProvider
from with_intelligence_mcp.features.auth.throttle import ThrottleConfig

__all__ = [
    "InvalidCredentialEnvelopeError",
    "NotConnectedError",
    "ThrottleConfig",
    "WithIntelligenceAuthContext",
    "WithIntelligenceOAuthProvider",
    "cleanup_lifespan",
    "load_key",
    "purge_expired_auth_rows",
]
