from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from unique_mcp.auth.zitadel.oidc_proxy import (
    ZitadelOIDCProxySettings,
    create_zitadel_oidc_proxy,
)
from unique_mcp.auth.zitadel.scopes import ZITADEL_DEFAULT_MCP_SCOPES
from unique_mcp.settings import ServerSettings

from kb_search.references import SERVER_CITATION_INSTRUCTIONS


def main() -> None:
    # Single .env for local (toolkit prefers unique.env; mcp/zitadel prefer their
    # own names — loading into the process env covers all of them).
    # override=True so service .env wins over stale shell UNIQUE_MCP_* exports.
    load_dotenv(Path.cwd() / ".env", override=True)

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

    @mcp.custom_route("/probe", methods=["GET"])
    async def probe(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_credentials=True,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    # FastMCP Host allowlist (DNS-rebinding guard). Use PUBLIC host when set
    # (ingress / ngrok / localhost). That is the Host clients hit — not the
    # Unique frontend Origin. Without PUBLIC matching the client URL, OAuth
    # and Host checks use the wrong base (421/403 / broken token swap).
    public = server_settings.public_base_url
    public_host = public.host if public else None
    mcp.run(
        transport=server_settings.transport_scheme,
        host=server_settings.local_base_url.host,
        port=server_settings.local_base_url.port,
        log_level="info",
        middleware=middleware,
        allowed_hosts=[public_host] if public_host else None,
    )


if __name__ == "__main__":
    main()
