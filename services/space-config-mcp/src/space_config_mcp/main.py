from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import ServerSettings

from space_config_mcp.mcp import create_server
from space_config_mcp.mcp import run_server
from space_config_mcp.persistence import PersistenceSettings
from space_config_mcp.telemetry import init_telemetry
from space_config_mcp.upstream import UpstreamSettings


def main() -> None:
    init_telemetry(LoggingSettings())
    server = create_server(
        from_environment(UpstreamSettings),
        from_environment(PersistenceSettings),
    )
    run_server(server, ServerSettings())


if __name__ == "__main__":
    main()
