# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import ServerSettings

from world_check_mcp.mcp import create_server
from world_check_mcp.mcp import run_server
from world_check_mcp.telemetry import init_telemetry
from world_check_mcp.upstream import UpstreamSettings


def main() -> None:
    init_telemetry(LoggingSettings())
    server = create_server(from_environment(UpstreamSettings))
    run_server(server, ServerSettings())


if __name__ == "__main__":
    main()
