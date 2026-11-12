# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from typing import Annotated, ClassVar

from mcp_configs import RetrySettings
from mcp_configs import shared_config
from pydantic import AnyHttpUrl
from pydantic import Field
from pydantic import SecretStr
from pydantic import UrlConstraints
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from polixis_mcp.upstream.recording import RecordingSettings

# The client credentials, the token and the API key travel to these, so plain http is refused.
type _HttpsUrl = Annotated[AnyHttpUrl, UrlConstraints(allowed_schemes=["https"])]


class UpstreamSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("UPSTREAM_")

    # Polixis wants both on every request: a client-credentials token from its Keycloak realm
    # and the API key in `x-api-key`.
    client_id: SecretStr = Field(min_length=1)
    client_secret: SecretStr = Field(min_length=1)
    api_key: SecretStr = Field(min_length=1)
    api_url: _HttpsUrl = AnyHttpUrl("https://api-polixis.polixis.com")
    token_url: _HttpsUrl = AnyHttpUrl(
        "https://auth.polixis.com/realms/plx-prod/protocol/openid-connect/token"
    )
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    # At most this many requests to Polixis at once from one process; the others wait for a free
    # connection, within `timeout_seconds`. Polixis throttles bursts and trips a circuit breaker
    # on many large graphs at once.
    max_concurrent_requests: int = Field(default=4, ge=1, le=20)
    # How long a process stops calling Polixis after it answers that the quota is spent.
    quota_cooldown_seconds: float = Field(default=15 * 60, ge=0)
    # Read from UPSTREAM_RETRY_*, with the defaults every MCP shares.
    retry: RetrySettings = Field(default_factory=RetrySettings)
    # Read from UPSTREAM_RECORDING_*: off unless a developer records or replays Polixis's answers.
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
