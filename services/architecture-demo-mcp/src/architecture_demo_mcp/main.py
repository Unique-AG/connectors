# mcp-scaffold-commit: 9a91a8864afe, timestamp: 2026-10-21T12:09:32+00:00

from functools import partial

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import RateLimitSettings
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings

from architecture_demo_mcp.mcp import AuthMode
from architecture_demo_mcp.mcp import AuthSettings
from architecture_demo_mcp.mcp import create_auth
from architecture_demo_mcp.mcp import create_server
from architecture_demo_mcp.mcp import run_server
from architecture_demo_mcp.persistence import open_persistence
from architecture_demo_mcp.persistence import PersistenceSettings
from architecture_demo_mcp.telemetry import init_telemetry
from architecture_demo_mcp.upstream import UpstreamSettings


def main() -> None:
    server_settings = ServerSettings()
    persistence_settings = PersistenceSettings()
    upstream_settings = from_environment(UpstreamSettings)
    # Read only in zitadel mode, so a server without sign-in starts without its variables.
    zitadel = from_environment(ZitadelSettings) if AuthSettings().mode is AuthMode.ZITADEL else None
    init_telemetry(
        LoggingSettings(), secrets=_secrets(persistence_settings, upstream_settings, zitadel)
    )
    auth = create_auth(zitadel=zitadel, server=server_settings, store=persistence_settings.store)
    persistence = partial(open_persistence, persistence_settings)
    # Without sign-in there is no user to count tool calls under.
    rate_limit = RateLimitSettings() if auth is not None else None
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
