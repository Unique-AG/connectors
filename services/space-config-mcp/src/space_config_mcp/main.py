import logging

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import ServerSettings
from pydantic import ValidationError

from space_config_mcp.mcp import AuthSettings
from space_config_mcp.mcp import create_server
from space_config_mcp.mcp import run_server
from space_config_mcp.persistence import PersistenceSettings
from space_config_mcp.telemetry import init_telemetry
from space_config_mcp.upstream import UpstreamSettings

_LOG = logging.getLogger(__name__)


def main() -> None:
    init_telemetry(LoggingSettings())
    try:
        auth_settings: AuthSettings | None = from_environment(AuthSettings)
    except ValidationError:
        auth_settings = None
        _LOG.warning(
            "ZITADEL_* / UNIQUE_MCP_PUBLIC_BASE_URL not set — "
            "starting without auth (local dev only, never use in production)"
        )
    server = create_server(
        from_environment(UpstreamSettings),
        from_environment(PersistenceSettings),
        auth_settings,
    )
    run_server(server, ServerSettings())


if __name__ == "__main__":
    main()
