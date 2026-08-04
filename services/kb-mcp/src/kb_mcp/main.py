from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from unique_mcp.auth.zitadel.oidc_proxy import (
    ZitadelOIDCProxySettings,
    create_zitadel_oidc_proxy,
)
from unique_mcp.auth.zitadel.scopes import ZITADEL_DEFAULT_MCP_SCOPES
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops
from unique_mcp.settings import ServerSettings
from unique_toolkit.monitoring import configure_tracing

from kb_mcp.references import SERVER_CITATION_INSTRUCTIONS


def main() -> None:
    # Single .env for local (toolkit prefers unique.env; mcp/zitadel prefer their
    # own names — loading into the process env covers all of them).
    # override=True so service .env wins over stale shell UNIQUE_MCP_* exports.
    load_dotenv(Path.cwd() / ".env", override=True)
    # Opt-in via OTEL_* (e.g. OTEL_TRACES_EXPORTER=console locally).
    configure_tracing(service_name="kb-mcp")
    configure_logging()

    server_settings = ServerSettings()

    oidc_proxy = create_zitadel_oidc_proxy(
        mcp_server_base_url=server_settings.base_url.encoded_string(),
        zitadel_oidc_proxy_settings=ZitadelOIDCProxySettings(),  # pyright: ignore[reportCallIssue]
        # Zitadel often issues opaque (non-JWT) access tokens even when the app
        # is configured for JWT. Verify the OIDC id_token instead so the
        # token-swap after /token succeeds; otherwise every /mcp call returns
        # invalid_token despite a successful login.
        verify_id_token=True,
    )
    # OIDCProxy does not advertise scopes by default; without this, DCR rejects
    # openid/profile and clients fail authorize (invalid_scope → invalid_token).
    oidc_proxy.update_default_scopes(list(ZITADEL_DEFAULT_MCP_SCOPES))

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
    # via ServerSettings — not from this Host allowlist.
    mcp.run(
        transport=server_settings.transport_scheme,
        host=server_settings.local_base_url.host,
        port=server_settings.local_base_url.port,
        log_level="info",
        middleware=middleware,
    )


if __name__ == "__main__":
    main()
