"""The Backstop REST transport: one shared pool, per-caller authenticated clients.

Infrastructure, so nothing here imports from `features/` — see `features/__init__.py` for the
rule and `credential.py` for how the types both layers need are shared without a cycle.

Nothing here imports `config` either: the tuning knobs arrive as the frozen types in
`settings.py`, which `dependencies.transport_settings` / `retry_settings` translate
`BackstopConfig` into. Both rules are enforced by `tests/test_layering.py`.
"""

from backstop_mcp.backstop_client.client import (
    SYSTEM_INFO_PATH,
    BackstopClient,
)
from backstop_mcp.backstop_client.credential import (
    AuthFailureHook,
    BackstopCredentialSecret,
    CallerAuthContext,
    CallerSession,
    CallerSessionProvider,
)
from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopAuthError,
    BackstopErrorDetail,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
    BackstopSessionRevokedError,
    BackstopTransientAuthError,
    BackstopUnreachableError,
    BackstopUntrustedUrlError,
    mcp_session_was_revoked,
    reset_mcp_session_revoked,
    restore_mcp_session_revoked,
)
from backstop_mcp.backstop_client.factory import (
    BackstopClientFactory,
)
from backstop_mcp.backstop_client.json_api import (
    BackstopApiCollectionDocument,
    BackstopApiResource,
    BackstopApiResourceDocument,
    Included,
    IncludedResource,
    ResourceRef,
    included_resource,
)
from backstop_mcp.backstop_client.pagination import (
    PageResult,
    SinglePage,
    paginate_all,
    parse_page,
)
from backstop_mcp.backstop_client.retry import RetryPolicy
from backstop_mcp.backstop_client.settings import BackstopTransportSettings, RetrySettings

__all__ = [
    "AuthFailureHook",
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
    "BackstopSessionRevokedError",
    "BackstopTransientAuthError",
    "BackstopTransportSettings",
    "BackstopUnreachableError",
    "BackstopUntrustedUrlError",
    "CallerAuthContext",
    "CallerSession",
    "CallerSessionProvider",
    "Included",
    "IncludedResource",
    "PageResult",
    "ResourceRef",
    "RetryPolicy",
    "RetrySettings",
    "SYSTEM_INFO_PATH",
    "SinglePage",
    "included_resource",
    "mcp_session_was_revoked",
    "paginate_all",
    "parse_page",
    "reset_mcp_session_revoked",
    "restore_mcp_session_revoked",
]
