"""The Backstop REST transport: one shared pool, per-caller authenticated clients.

Infrastructure, so nothing here imports from `features/` — see `features/__init__.py` for the
rule and `credential.py` for how the types both layers need are shared without a cycle.

Nothing here imports `config` either: the tuning knobs arrive as the frozen types in
`settings.py`, which `create_app` translates `BackstopConfig` into. Both rules are enforced by
`tests/test_layering.py`.
"""

from backstop_mcp.backstop_client.client import (
    BackstopClient,
)
from backstop_mcp.backstop_client.credential import (
    BackstopCredentialSecret,
    CallerAuthContext,
)
from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopAuthError,
    BackstopErrorDetail,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
    BackstopUnreachableError,
    BackstopUntrustedUrlError,
)
from backstop_mcp.backstop_client.factory import (
    BackstopClientFactory,
)
from backstop_mcp.backstop_client.json_api import (
    BackstopApiCollectionDocument,
    BackstopApiResource,
    BackstopApiResourceDocument,
    IncludedResource,
    ResourceRef,
    follow_included,
    included_by_type,
    included_resource,
)
from backstop_mcp.backstop_client.pagination import PageResult, SinglePage
from backstop_mcp.backstop_client.settings import BackstopTransportSettings, RetrySettings

__all__ = [
    "BackstopApiCollectionDocument",
    "BackstopApiError",
    "BackstopApiResource",
    "BackstopApiResourceDocument",
    "BackstopAuthError",
    "BackstopClient",
    "BackstopClientFactory",
    "BackstopCredentialSecret",
    "BackstopErrorDetail",
    "BackstopRateLimitError",
    "BackstopResponseSchemaError",
    "BackstopTransportSettings",
    "BackstopUnreachableError",
    "BackstopUntrustedUrlError",
    "CallerAuthContext",
    "IncludedResource",
    "PageResult",
    "ResourceRef",
    "RetrySettings",
    "SinglePage",
    "follow_included",
    "included_by_type",
    "included_resource",
]
