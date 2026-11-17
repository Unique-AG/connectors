# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from functools import partial

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import RateLimitSettings
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from pydantic import Field

from polixis_mcp.mcp import AuthMode
from polixis_mcp.mcp import AuthSettings
from polixis_mcp.mcp import create_auth
from polixis_mcp.mcp import create_server
from polixis_mcp.mcp import run_server
from polixis_mcp.persistence import open_persistence
from polixis_mcp.persistence import PersistenceSettings
from polixis_mcp.telemetry import init_telemetry
from polixis_mcp.upstream import RecordingMode
from polixis_mcp.upstream import UpstreamSettings


class _RateLimitSettings(RateLimitSettings):
    """Below every MCP's default: the tool calls of every user spend one fixed quota of Polixis
    requests, which a user calling in a loop would use up for all of them.
    """

    tool_calls_per_window: int = Field(default=20, ge=1)


def main() -> None:
    init_telemetry(LoggingSettings())
    server_settings = ServerSettings()
    persistence_settings = PersistenceSettings()
    # Read only in zitadel mode, so a server without sign-in starts without its variables.
    zitadel = from_environment(ZitadelSettings) if AuthSettings().mode is AuthMode.ZITADEL else None
    auth = create_auth(zitadel=zitadel, server=server_settings, store=persistence_settings.store)
    persistence = partial(open_persistence, persistence_settings)
    # Without sign-in there is no user to count tool calls under.
    rate_limit = _RateLimitSettings() if auth is not None else None
    upstream = from_environment(UpstreamSettings)
    # Recordings are licensed data about real people: only a developer's own loopback server
    # may save or serve them.
    assert upstream.recording.mode is RecordingMode.OFF or auth is None, (
        "UPSTREAM_RECORDING_MODE needs MCP_AUTH_MODE=none"
    )
    server = create_server(upstream, persistence, auth=auth, rate_limit=rate_limit)
    run_server(server, server_settings)


if __name__ == "__main__":
    main()
