import asyncio
from unittest.mock import MagicMock, patch

from fastmcp.server.auth import AccessToken

from q_bridge_mcp.auth.setup import REQUIRED_SCOPES, setup_auth
from q_bridge_mcp.config.settings import settings
from q_bridge_mcp.dependencies import get_company_id, get_user_id
from q_bridge_mcp.main import main
from q_bridge_mcp.server import create_server


def test_dependencies_extract_zitadel_claims() -> None:
    token = AccessToken(
        token="test-token",
        client_id="test-client",
        scopes=["openid", "profile"],
        claims={
            "sub": "user-123",
            "urn:zitadel:iam:user:resourceowner:id": "company-456",
        },
    )

    assert get_user_id(token) == "user-123"
    assert get_company_id(token) == "company-456"


@patch("q_bridge_mcp.server.setup_auth", return_value=None)
def test_registers_skill_and_profile_settings_tools(
    setup_auth: MagicMock,
) -> None:
    server = create_server()
    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "get_skill_guide",
        "save_profile",
        "save_organization_credentials",
        "profile_settings",
    ]
    assert tools[0].parameters == {
        "additionalProperties": False,
        "properties": {
            "file": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
            "force_refresh": {"default": False, "type": "boolean"},
            "skill": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
        },
        "type": "object",
    }
    assert tools[0].annotations is not None
    assert tools[0].annotations.read_only_hint is True
    assert tools[1].parameters == {
        "additionalProperties": False,
        "properties": {"skills_root_folder": {"type": "string"}},
        "required": ["skills_root_folder"],
        "type": "object",
    }
    assert tools[1].meta is not None
    assert tools[1].meta["ui"]["visibility"] == ["app"]
    assert tools[2].parameters == {
        "additionalProperties": False,
        "properties": {
            "api_key": {"type": "string"},
            "app_id": {"type": "string"},
        },
        "required": ["app_id", "api_key"],
        "type": "object",
    }
    assert tools[2].meta is not None
    assert tools[2].meta["ui"]["visibility"] == ["app"]
    assert tools[3].parameters == {
        "additionalProperties": False,
        "properties": {},
        "type": "object",
    }
    assert tools[3].meta is not None
    assert tools[3].meta["ui"]["visibility"] == ["model"]
    assert server.instructions is not None
    assert "profile_settings" in server.instructions
    assert "skill://" in server.instructions
    assert "get_skill_guide" in server.instructions
    assert "MANDATORY skill preflight" in server.instructions
    assert "Do not answer before completing this preflight" in server.instructions
    assert "the user does not need to name a skill" in server.instructions
    assert "supporting resources" in server.instructions
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
