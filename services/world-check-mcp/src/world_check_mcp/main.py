# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from functools import partial

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings

from world_check_mcp.mcp import AuthMode
from world_check_mcp.mcp import AuthSettings
from world_check_mcp.mcp import create_auth
from world_check_mcp.mcp import create_server
from world_check_mcp.mcp import run_server
from world_check_mcp.persistence import open_persistence
from world_check_mcp.persistence import PersistenceSettings
from world_check_mcp.telemetry import init_telemetry
from world_check_mcp.upstream import UpstreamSettings


def main() -> None:
    init_telemetry(LoggingSettings())
    server_settings = ServerSettings()
    persistence_settings = PersistenceSettings()
    # Read only in zitadel mode, so a server without sign-in starts without its variables.
    zitadel = from_environment(ZitadelSettings) if AuthSettings().mode is AuthMode.ZITADEL else None
    auth = create_auth(zitadel=zitadel, server=server_settings, store=persistence_settings.store)
    persistence = partial(open_persistence, persistence_settings)
    server = create_server(from_environment(UpstreamSettings), persistence, auth=auth)
    run_server(server, server_settings)


if __name__ == "__main__":
    main()
