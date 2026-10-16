import pytest
from pydantic import SecretStr

from kyckr_mcp.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        mcp_api_key=SecretStr("test-mcp-key"),
        kyckr_api_key=SecretStr("test-kyckr-key"),
        _env_file=None,
    )
