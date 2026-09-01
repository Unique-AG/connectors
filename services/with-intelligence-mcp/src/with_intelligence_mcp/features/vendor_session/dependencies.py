from functools import lru_cache

from fastmcp.dependencies import Depends

from with_intelligence_mcp.config import WithIntelligenceConfig
from with_intelligence_mcp.dependencies import (
    get_with_intelligence_client_factory,
    get_with_intelligence_config,
)
from with_intelligence_mcp.features.vendor_session.service_account_session import (
    ServiceAccountSession,
)
from with_intelligence_mcp.with_intelligence_client import (
    VendorCredential,
    WithIntelligenceClient,
)


@lru_cache(maxsize=1)
def get_service_account_session() -> ServiceAccountSession:
    config = get_with_intelligence_config()
    return ServiceAccountSession(
        get_with_intelligence_client_factory(), _credential_from_config(config)
    )


def _credential_from_config(config: WithIntelligenceConfig) -> VendorCredential | None:
    """`None` when unconfigured — the session reports that at call time, with a usable message."""
    username, password = config.username, config.password
    if username is None or password is None:
        return None
    return VendorCredential(username=username, password=password)


def get_with_intelligence_client(
    session: ServiceAccountSession = Depends(get_service_account_session),
) -> WithIntelligenceClient:
    return get_with_intelligence_client_factory().for_session(session)
