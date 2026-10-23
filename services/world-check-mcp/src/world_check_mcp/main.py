# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import RedisSettings
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings

from world_check_mcp.mcp import AuthMode
from world_check_mcp.mcp import AuthSettings
from world_check_mcp.mcp import create_auth
from world_check_mcp.mcp import create_server
from world_check_mcp.mcp import run_server
from world_check_mcp.telemetry import init_telemetry
from world_check_mcp.upstream import UpstreamSettings


def main() -> None:
    init_telemetry(LoggingSettings())
    server_settings = ServerSettings()
    # Read only in zitadel mode, so a server without sign-in starts without its variables.
    zitadel = from_environment(ZitadelSettings) if AuthSettings().mode is AuthMode.ZITADEL else None
    store = from_environment(RedisSettings) if zitadel is not None else None
    auth = create_auth(zitadel=zitadel, server=server_settings, store=store)
    server = create_server(from_environment(UpstreamSettings), auth=auth)
    run_server(server, server_settings)


if __name__ == "__main__":
    main()
