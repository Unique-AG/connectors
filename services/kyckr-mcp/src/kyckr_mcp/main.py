# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from functools import partial

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import RateLimitSettings
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings

from kyckr_mcp.mcp import AuthMode
from kyckr_mcp.mcp import AuthSettings
from kyckr_mcp.mcp import create_auth
from kyckr_mcp.mcp import create_server
from kyckr_mcp.mcp import run_server
from kyckr_mcp.persistence import open_persistence
from kyckr_mcp.persistence import PersistenceSettings
from kyckr_mcp.persistence import sign_in_store
from kyckr_mcp.telemetry import init_telemetry
from kyckr_mcp.upstream import UpstreamSettings


def main() -> None:
    server_settings = ServerSettings()
    upstream_settings = from_environment(UpstreamSettings)
    persistence_settings = PersistenceSettings()
    # Read only in zitadel mode, so a server without sign-in starts without its variables.
    zitadel = from_environment(ZitadelSettings) if AuthSettings().mode is AuthMode.ZITADEL else None
    init_telemetry(
        LoggingSettings(), secrets=_secrets(persistence_settings, upstream_settings, zitadel)
    )
    auth = sign_in = rate_limit = None
    if zitadel is not None:
        sign_in = sign_in_store(persistence_settings.store)
        auth = create_auth(zitadel=zitadel, server=server_settings, store=sign_in)
        # Without sign-in there is no user to count tool calls under.
        rate_limit = RateLimitSettings()
    persistence = partial(open_persistence, sign_in)
    server = create_server(upstream_settings, persistence, auth=auth, rate_limit=rate_limit)
    run_server(server, server_settings)


def _secrets(
    persistence: PersistenceSettings, upstream: UpstreamSettings, zitadel: ZitadelSettings | None
) -> tuple[str, ...]:
    """Every secret the deployment configures. Add each new one here."""
    keys = (
        upstream.api_key,
        *((zitadel.jwt_signing_key, zitadel.client_secret) if zitadel else ()),
    )
    return (*(key.get_secret_value() for key in keys if key is not None), *persistence.passwords())


if __name__ == "__main__":
    main()
