from functools import partial

from mcp_configs import LoggingSettings
from mcp_configs import ServerSettings

from architecture_demo_mcp.mcp import create_server
from architecture_demo_mcp.mcp import run_server
from architecture_demo_mcp.persistence import open_persistence
from architecture_demo_mcp.persistence import PersistenceSettings
from architecture_demo_mcp.telemetry import init_telemetry
from architecture_demo_mcp.upstream import UpstreamSettings


def main() -> None:
    init_telemetry(LoggingSettings())
    persistence = partial(open_persistence, PersistenceSettings())
    server = create_server(UpstreamSettings(), persistence)  # pyright: ignore[reportCallIssue]
    run_server(server, ServerSettings())


if __name__ == "__main__":
    main()
