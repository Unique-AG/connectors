"""Bridging MCP OAuth to a Backstop credential: login, token lifetime, encryption at rest.

The public surface of the package — what `create_app` wires together and what other features
need to resolve the calling user. The rest (`credential_store`, `pkce`, the login form) is this
package's own business. Enforced by `tests/test_layering.py`.

This file used to be empty, which was load-bearing by accident: `backstop_client` imported
`features.auth` for the credential type while `provider.py` imported `backstop_client`, and only
the absent re-export kept that from being a package cycle. Those types now live in
`backstop_client/credential.py`, so the direction is one-way and this file can do its job.
"""

from backstop_mcp.features.auth.cleanup import cleanup_lifespan
from backstop_mcp.features.auth.context import BackstopAuthContext
from backstop_mcp.features.auth.crypto import load_key
from backstop_mcp.features.auth.provider import BackstopOAuthProvider
from backstop_mcp.features.auth.throttle import ThrottleConfig

__all__ = [
    "BackstopAuthContext",
    "BackstopOAuthProvider",
    "ThrottleConfig",
    "cleanup_lifespan",
    "load_key",
]
