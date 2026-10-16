import pytest
from pydantic import SecretStr, ValidationError

from kyckr_mcp.settings import Settings


def settings_with(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "mcp_api_key": SecretStr("mcp"),
        "kyckr_api_key": SecretStr("kyckr"),
        **overrides,
    }
    return Settings.model_validate(values | {"_env_file": None})


@pytest.mark.parametrize(
    "url",
    ["http://localhost:9542", "http://127.0.0.1:9542", "http://[::1]:9542", "https://mcp.example"],
)
def test_a_local_or_https_origin_is_accepted(url: str) -> None:
    assert settings_with(mcp_base_url=url).base_url == url


@pytest.mark.parametrize(
    "url", ["http://mcp.example", "https://mcp.example/mcp", "https://u@mcp.example"]
)
def test_a_remote_http_url_or_a_url_with_a_path_or_user_is_refused(url: str) -> None:
    with pytest.raises(ValidationError):
        settings_with(mcp_base_url=url)


def test_a_local_url_allows_the_local_hosts_and_a_remote_one_only_its_own() -> None:
    assert settings_with().allowed_hosts == ["localhost", "127.0.0.1"]
    assert settings_with(mcp_base_url="https://mcp.example").allowed_hosts == ["mcp.example"]


def test_the_mcp_path_is_made_from_the_api_key() -> None:
    assert settings_with().mcp_path == "/mcp/mcp"


def test_the_inspector_origin_is_allowed_on_a_local_bind_only() -> None:
    assert [str(url) for url in settings_with(host="::1").mcp_allowed_origins] == [
        "http://localhost:6274/"
    ]
    assert (
        settings_with(host="10.0.0.5", mcp_base_url="https://mcp.example").mcp_allowed_origins == []
    )
