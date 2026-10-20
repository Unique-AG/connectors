from fastmcp import FastMCP
import mcp_runtime
from mcp_runtime import LoggingSettings
from starlette.middleware import Middleware

SERVICE_NAME = "architecture-demo-mcp"


def init_telemetry(settings: LoggingSettings) -> None:
    mcp_runtime.init_telemetry(SERVICE_NAME, settings)


def instrument(mcp: FastMCP) -> Middleware:
    return mcp_runtime.instrument(mcp)
