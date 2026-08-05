"""The Backstop REST transport: one shared pool, per-caller authenticated clients.

Infrastructure, so nothing here imports from `features/` — see `features/__init__.py` for the
rule and `credential.py` for how the types both layers need are shared without a cycle.

Nothing here imports `config` either: the tuning knobs arrive as the frozen types in
`settings.py`, which `create_app` translates `BackstopConfig` into. Both rules are enforced by
`tests/test_layering.py`.
"""

from backstop_mcp.backstop_client.client import (
    BackstopAuthError,
    BackstopClient,
    BackstopUnreachableError,
    CallerClientProvider,
    build_auth_headers,
)
from backstop_mcp.backstop_client.credential import (
    BackstopCredentialSecret,
    CallerAuthContext,
)
from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopErrorDetail,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
    BackstopUnexpectedCollectionError,
    BackstopUntrustedUrlError,
)
from backstop_mcp.backstop_client.factory import (
    BackstopClientFactory,
    create_backstop_client_factory,
)
from backstop_mcp.backstop_client.json_api import (
    BackstopApiDocument,
    BackstopApiResource,
    included_for_relationship,
    included_of_type,
    single_resource,
)
from backstop_mcp.backstop_client.pagination import PageResult
from backstop_mcp.backstop_client.settings import BackstopTransportSettings, RetrySettings

__all__ = [
    "BackstopApiDocument",
    "BackstopApiError",
    "BackstopApiResource",
    "BackstopAuthError",
    "BackstopClient",
    "BackstopClientFactory",
    "BackstopCredentialSecret",
    "BackstopErrorDetail",
    "BackstopRateLimitError",
    "BackstopResponseSchemaError",
    "BackstopTransportSettings",
    "BackstopUnexpectedCollectionError",
    "BackstopUnreachableError",
    "BackstopUntrustedUrlError",
    "CallerAuthContext",
    "CallerClientProvider",
    "PageResult",
    "RetrySettings",
    "build_auth_headers",
    "create_backstop_client_factory",
    "included_for_relationship",
    "included_of_type",
    "single_resource",
]
