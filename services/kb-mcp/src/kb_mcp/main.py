from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from kb_mcp.auth import build_auth
from kb_mcp.references import SERVER_CITATION_INSTRUCTIONS
from kb_mcp.settings import get_settings


def main() -> None:
    # First statement: config errors fail fast at boot, before any other setup.
    settings = get_settings()
    # Opt-in via OTEL_* (e.g. OTEL_TRACES_EXPORTER=console locally).
    configure_tracing(service_name="kb-mcp")
    configure_logging()

    oidc_proxy = build_auth(settings)

    mcp = FastMCP(
        "Knowledge Base Search",
        instructions=SERVER_CITATION_INSTRUCTIONS,
        auth=oidc_proxy,
        providers=[FileSystemProvider(Path(__file__).parent / "tools")],
    )

    # Bearer auth (Authorization header) — no cookies, so no allow_credentials.
    # Wildcard + credentials would reflect any Origin (credentialed CORS hole).
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
        # HTTP Prometheus metrics; MCP tool spans come from FastMCP + configure_tracing.
        setup_ops(mcp),
    ]

    # Host/Origin DNS-rebinding guard is opt-in in FastMCP 3.4.x
    # (host_origin_protection defaults to False). Passing allowed_hosts alone
    # is a no-op. Enabling protection in-cluster also needs probe Host headers
    # (kubelet Host is the pod IP, not PUBLIC), e.g.
    # FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=auto + chart probe httpHeaders.
    # OAuth redirect / token-swap base still comes from UNIQUE_MCP_PUBLIC_BASE_URL
    # via Settings — not from this Host allowlist.
    mcp.run(
        transport=settings.transport_scheme,
        host=settings.local_base_url.host,
        port=settings.local_base_url.port,
        log_level="info",
        middleware=middleware,
    )


if __name__ == "__main__":
    main()
