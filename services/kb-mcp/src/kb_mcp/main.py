from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from kb_mcp.auth import build_auth
from kb_mcp.references import SERVER_INSTRUCTIONS_CITATION_GUIDANCE
from kb_mcp.settings import ENV_FILE, get_settings


def main() -> None:
    # unique_toolkit and the logging/tracing setup read os.environ directly.
    # None would make load_dotenv fall back to searching for any .env.
    if ENV_FILE is not None:
        load_dotenv(ENV_FILE, override=False)

    settings = get_settings()
    # Opt-in via OTEL_* (e.g. OTEL_TRACES_EXPORTER=console locally).
    configure_tracing(service_name="kb-mcp")
    configure_logging()

    oidc_proxy = build_auth(settings)

    mcp = FastMCP(
        "Knowledge Base Search",
        instructions=SERVER_INSTRUCTIONS_CITATION_GUIDANCE,
        auth=oidc_proxy,
        providers=[FileSystemProvider(Path(__file__).parent / "tools")],
    )

    # No CORS: /mcp is server-side and OAuth redirects are top-level navigation.
    middleware = [
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
