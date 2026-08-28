"""The Backstop REST transport: one shared pool, per-caller authenticated clients.

Infrastructure, so nothing here imports from `features/` — see `features/__init__.py` for the
rule and `credential.py` for how the types both layers need are shared without a cycle.

Nothing here imports `config` either: the tuning knobs arrive as the frozen types in
`settings.py`, which `dependencies.transport_settings` / `retry_settings` translate
`BackstopConfig` into. Both rules are enforced by `tests/test_layering.py`.
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
    IncludedIndex,
    IncludedResource,
    ResourceRef,
    follow_included,
    follow_indexed,
    included_by_type,
    included_resource,
    index_included,
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
    "IncludedIndex",
    "IncludedResource",
    "PageResult",
    "ResourceRef",
    "RetryPolicy",
    "RetrySettings",
    "SinglePage",
    "follow_included",
    "follow_indexed",
    "included_by_type",
    "included_resource",
    "index_included",
    "mcp_session_was_revoked",
    "paginate_all",
    "parse_page",
    "reset_mcp_session_revoked",
    "restore_mcp_session_revoked",
]
