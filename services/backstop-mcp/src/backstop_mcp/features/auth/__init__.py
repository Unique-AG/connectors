"""Bridging MCP OAuth to a Backstop credential: login, token lifetime, encryption at rest.

The public surface of the package — what `create_app` wires together and what other features
need to resolve the calling user. Credential types live in `backstop_client/credential.py`.
Enforced by `tests/test_layering.py`.
"""

from mcp_credential_auth import LoginThrottleConfig

from backstop_mcp.features.auth.cleanup import cleanup_lifespan
from backstop_mcp.features.auth.context import (
    BackstopAuthContext,
    NotConnectedError,
)
from backstop_mcp.features.auth.credential_store import get_system_user_cache
from backstop_mcp.features.auth.crypto import load_key
from backstop_mcp.features.auth.provider import BackstopOAuthProvider

__all__ = [
    "BackstopAuthContext",
    "BackstopOAuthProvider",
    "NotConnectedError",
    "LoginThrottleConfig",
    "cleanup_lifespan",
    "get_system_user_cache",
    "load_key",
]
