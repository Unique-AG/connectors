"""The Backstop REST transport: one shared pool, per-caller authenticated clients.

Infrastructure, so nothing here imports from `features/` — see `features/__init__.py` for the
rule and `credential.py` for how the types both layers need are shared without a cycle.
"""

from backstop_mcp.backstop_client.client import (
    BackstopAuthError,
    BackstopClient,
    BackstopUnreachableError,
    build_auth_headers,
)
from backstop_mcp.backstop_client.credential import (
    BackstopCredentialSecret,
    CallerAuthContext,
)
from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
    BackstopUntrustedUrlError,
)
from backstop_mcp.backstop_client.factory import (
    BackstopClientFactory,
    create_backstop_client_factory,
)
from backstop_mcp.backstop_client.pagination import PageResult

__all__ = [
    "BackstopApiError",
    "BackstopAuthError",
    "BackstopClient",
    "BackstopClientFactory",
    "BackstopCredentialSecret",
    "BackstopRateLimitError",
    "BackstopResponseSchemaError",
    "BackstopUnreachableError",
    "BackstopUntrustedUrlError",
    "CallerAuthContext",
    "PageResult",
    "build_auth_headers",
    "create_backstop_client_factory",
]
