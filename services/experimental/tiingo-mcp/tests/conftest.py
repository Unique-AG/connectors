import pytest
from pydantic import SecretStr

from tiingo_mcp.settings import Settings


@pytest.fixture
def local_settings() -> Settings:
    return Settings(tiingo_api_key=SecretStr("test"), mcp_auth_mode="none", _env_file=None)
