# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from functools import partial

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import RateLimitSettings
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings

from polixis_mcp.mcp import AuthMode
from polixis_mcp.mcp import AuthSettings
from polixis_mcp.mcp import create_auth
from polixis_mcp.mcp import create_server
from polixis_mcp.mcp import run_server
from polixis_mcp.persistence import open_persistence
from polixis_mcp.persistence import PersistenceSettings
from polixis_mcp.telemetry import init_telemetry
from polixis_mcp.upstream import UpstreamSettings


def main() -> None:
    init_telemetry(LoggingSettings())
    server_settings = ServerSettings()
    persistence_settings = PersistenceSettings()
    # Read only in zitadel mode, so a server without sign-in starts without its variables.
    zitadel = from_environment(ZitadelSettings) if AuthSettings().mode is AuthMode.ZITADEL else None
    auth = create_auth(zitadel=zitadel, server=server_settings, store=persistence_settings.store)
    persistence = partial(open_persistence, persistence_settings)
    # Without sign-in there is no user to count tool calls under.
    rate_limit = RateLimitSettings() if auth is not None else None
    server = create_server(
        from_environment(UpstreamSettings), persistence, auth=auth, rate_limit=rate_limit
    )
    run_server(server, server_settings)


if __name__ == "__main__":
    main()
