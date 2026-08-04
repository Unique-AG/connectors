import asyncio
from unittest.mock import MagicMock, patch

from q_bridge_mcp.auth.setup import REQUIRED_SCOPES, setup_auth
from q_bridge_mcp.config.settings import settings
from q_bridge_mcp.main import main
from q_bridge_mcp.server import create_server
from q_bridge_mcp.tools.hello import hello_world


def test_hello_world_greets_authenticated_user() -> None:
    assert hello_world("Ada Lovelace") == "Hello, Ada Lovelace!"


@patch("q_bridge_mcp.server.setup_auth", return_value=None)
def test_registers_only_hello_world_tool(setup_auth: MagicMock) -> None:
    server = create_server()
    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == ["hello_world"]
    setup_auth.assert_called_once_with()


@patch("q_bridge_mcp.main.create_server")
def test_main_uses_streamable_http(create_server: MagicMock) -> None:
    main()

    create_server.assert_called_once_with()
    create_server.return_value.run.assert_called_once_with(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
    )


@patch("q_bridge_mcp.auth.setup.create_storage")
@patch("q_bridge_mcp.auth.setup.OIDCProxy")
def test_setup_auth_uses_zitadel_settings(
    oidc_proxy: MagicMock,
    create_storage: MagicMock,
) -> None:
    _ = setup_auth()

    create_storage.assert_called_once_with()
    oidc_proxy.assert_called_once_with(
        config_url=settings.zitadel_openid_configuration,
        client_id=settings.zitadel_client_id,
        client_secret=settings.zitadel_client_secret.get_secret_value(),
        base_url=str(settings.mcp_base_url),
        jwt_signing_key=settings.mcp_jwt_signing_key.get_secret_value(),
        client_storage=create_storage.return_value,
        required_scopes=REQUIRED_SCOPES,
        verify_id_token=True,
        strict=True,
    )
