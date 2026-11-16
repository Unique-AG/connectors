# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from functools import partial

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import ServerSettings

from kyckr_mcp.mcp import create_server
from kyckr_mcp.mcp import run_server
from kyckr_mcp.persistence import open_persistence
from kyckr_mcp.persistence import PersistenceSettings
from kyckr_mcp.telemetry import init_telemetry
from kyckr_mcp.upstream import UpstreamSettings


def main() -> None:
    upstream_settings = from_environment(UpstreamSettings)
    persistence_settings = PersistenceSettings()
    init_telemetry(
        LoggingSettings(),
        secrets=(upstream_settings.api_key.get_secret_value(), *persistence_settings.passwords()),
    )
    persistence = partial(open_persistence, persistence_settings)
    server = create_server(upstream_settings, persistence)
    run_server(server, ServerSettings())


if __name__ == "__main__":
    main()
