import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from functools import cache
from pathlib import Path
from typing import override

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from mcp.types import Icon
from starlette.middleware import Middleware
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing
from unique_toolkit.monitoring.memory import start_memory_trimmer

from kb_mcp.auth import build_auth
from kb_mcp.common.references import SERVER_INSTRUCTIONS_CITATION_GUIDANCE
from kb_mcp.common.tree_cache import expire_idle_trees_loop
from kb_mcp.health import PoolHealthMiddleware
from kb_mcp.http_client import install_pooled_http_client
from kb_mcp.settings import ENV_FILE, Settings, get_settings

_LOGGER = logging.getLogger(__name__)

_LOGO_PATH = Path(__file__).parent / "assets" / "logo.webp"


@cache
def _server_icon() -> Icon:
    """The connect-time icon: the OAuth consent page and serverInfo.icons both
    read FastMCP's `icons=`, and fall back to FastMCP's own logo without it."""
    logo_b64 = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
    return Icon(src=f"data:image/webp;base64,{logo_b64}", mime_type="image/webp")


class _DowngradeMemoryTrimNoise(logging.Filter):
    """Relabel the per-cycle "[MEMORY-TRIM:...]" log as DEBUG; other records on
    this logger (warnings, exceptions, the SIGTERM notice) pass through."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and record.msg.startswith("[MEMORY-TRIM:%s]"):
            record.levelno = logging.DEBUG
            record.levelname = logging.getLevelName(logging.DEBUG)
        return True


def apply_enabled_tools(mcp: FastMCP, settings: Settings) -> None:
    hidden = settings.disabled_tool_names()
    if hidden:
        mcp.disable(names=set(hidden), components={"tool"})
    _LOGGER.info(
        "MCP tools enabled: %s",
        ",".join(sorted(settings.enabled_tools)),
    )


@asynccontextmanager
async def tree_cache_expire_lifespan(_mcp: FastMCP) -> AsyncIterator[None]:
    """TTLCache is lazy; this drops idle trees on the event loop, then trims."""
    task = asyncio.create_task(
        expire_idle_trees_loop(),
        name="tree-cache-expire",
    )
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def main() -> None:
    # unique_toolkit and the logging/tracing setup read os.environ directly.
    # None would make load_dotenv fall back to searching for any .env.
    if ENV_FILE is not None:
        load_dotenv(ENV_FILE, override=False)

    settings = get_settings()
    # Opt-in via OTEL_* (e.g. OTEL_TRACES_EXPORTER=console locally).
    configure_tracing(service_name="kb-mcp")
    configure_logging()
    logging.getLogger("unique_toolkit.monitoring.memory").addFilter(
        _DowngradeMemoryTrimNoise()
    )
    start_memory_trimmer()
    # Before FastMCP(...): that imports the tool modules, and unique_sdk pins
    # whichever client exists the first time anything issues a request.
    install_pooled_http_client(settings)

    oidc_proxy = build_auth(settings)

    mcp = FastMCP(
        "Unique Knowledge Base Search MCP",
        instructions=SERVER_INSTRUCTIONS_CITATION_GUIDANCE,
        icons=[_server_icon()],
        auth=oidc_proxy,
        providers=[FileSystemProvider(Path(__file__).parent / "tools")],
        lifespan=tree_cache_expire_lifespan,
    )
    apply_enabled_tools(mcp, settings)

    # No CORS: /mcp is server-side and OAuth redirects are top-level navigation.
    middleware = [
        # First: short-circuits /probe before anything else looks at it.
        Middleware(PoolHealthMiddleware),
        # HTTP Prometheus metrics; MCP tool spans come from FastMCP + configure_tracing.
        setup_ops(mcp),
    ]

    # No allowed_hosts: the DNS-rebinding guard is off by default in FastMCP
    # 3.4.x, so passing it alone does nothing.
    mcp.run(
        transport=settings.transport_scheme,
        host=settings.local_base_url.host,
        port=settings.local_base_url.port,
        middleware=middleware,
    )


if __name__ == "__main__":
    main()
