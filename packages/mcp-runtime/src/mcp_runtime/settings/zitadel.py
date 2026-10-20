from typing import ClassVar, Self

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_runtime.settings.config import shared_config

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
# What every MCP needs from the token: who the user is and which organisation they belong to.
_REQUIRED_SCOPES = ("openid", "profile", "urn:zitadel:iam:user:resourceowner")


class ZitadelSettings(BaseSettings):
    """The Zitadel instance an MCP signs its users in with, as an OIDC proxy.

    The names match `unique_mcp.auth.zitadel.ZitadelOIDCProxySettings`, so the same environment
    configures both.
    """

    model_config: ClassVar[SettingsConfigDict] = shared_config("ZITADEL_")

    base_url: AnyHttpUrl
    client_id: str = Field(min_length=1)
    # None makes the MCP a public client with PKCE.
    client_secret: SecretStr | None = None
    # Signs the tokens the proxy issues to MCP clients.
    jwt_signing_key: SecretStr = Field(min_length=32)
    # Restricts sign-in to one organisation when set.
    org_id: str | None = None

    @model_validator(mode="after")
    def _https_unless_local(self) -> Self:
        if self.base_url.host not in _LOCAL_HOSTS and self.base_url.scheme != "https":
            raise ValueError("ZITADEL_BASE_URL must use https outside localhost")
        return self

    @property
    def issuer(self) -> str:
        return str(self.base_url).rstrip("/")

    @property
    def config_url(self) -> str:
        return f"{self.issuer}/.well-known/openid-configuration"

    @property
    def required_scopes(self) -> list[str]:
        organisation = [f"urn:zitadel:iam:org:id:{self.org_id}"] if self.org_id else []
        return [*_REQUIRED_SCOPES, *organisation]
