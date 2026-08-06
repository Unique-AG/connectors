"""All configuration for kb-mcp.

If it reads the environment, it is declared in this file. No exceptions.
"""

from functools import lru_cache

from fastmcp.server.server import Transport
from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from unique_mcp.util.find_env_file import find_env_file


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Env vars WIN over the file here. The old main.py's
        # load_dotenv(cwd/'.env', override=True) had it backwards, letting a
        # stray .env silently beat K8s secrets.
        env_file=find_env_file(filenames=["kb_mcp.env", ".env"], required=False),
        env_file_encoding="utf-8",
        frozen=True,
        extra="ignore",
    )

    # ── Server ──
    public_base_url: HttpUrl | None = Field(
        default=None, validation_alias="UNIQUE_MCP_PUBLIC_BASE_URL"
    )
    local_base_url: HttpUrl = Field(
        default=HttpUrl("http://localhost:8003"),
        validation_alias="UNIQUE_MCP_LOCAL_BASE_URL",
    )
    frontend_base_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Unique web app origin used to build clickable knowledge-upload "
            "deep links, e.g. https://<tenant>.unique.app. When unset, "
            "references fall back to unique://content/{id}."
        ),
        validation_alias="UNIQUE_MCP_FRONTEND_BASE_URL",
    )

    # ── Zitadel ──
    zitadel_base_url: str = Field(validation_alias="ZITADEL_BASE_URL")
    zitadel_client_id: str = Field(validation_alias="ZITADEL_CLIENT_ID")
    zitadel_client_secret: SecretStr = Field(validation_alias="ZITADEL_CLIENT_SECRET")

    # ── OAuth storage (see auth/storage.py) ──
    database_url: PostgresDsn | None = Field(
        default=None, validation_alias="DATABASE_URL"
    )
    storage_encryption_key: SecretStr | None = Field(default=None, min_length=44)
    allow_ephemeral_oauth_storage: bool = Field(
        default=False,
        description=("DEV ONLY. Per-pod storage that loses all sessions on restart."),
    )

    # ── Content-tree cache (was _ContentTreeCacheSettings) ──
    content_tree_cache_ttl_seconds: int = Field(
        default=1800, validation_alias="KB_SEARCH_CONTENT_TREE_CACHE_TTL_SECONDS"
    )
    content_tree_cache_max_entries: int = Field(
        default=128, validation_alias="KB_SEARCH_CONTENT_TREE_CACHE_MAX_ENTRIES"
    )

    # ── Search scope lookups (was the _LOOKUP_CONCURRENCY constant) ──
    scope_lookup_concurrency: int = 8

    @property
    def base_url(self) -> HttpUrl:
        return self.public_base_url or self.local_base_url

    @property
    def transport_scheme(self) -> Transport:
        url = self.base_url
        match url.scheme:
            case "http":
                return "http"
            case "https":
                return "http"
            case "sse":
                return "sse"
            case "streamable-http":
                return "streamable-http"
            case _:
                raise ValueError(f"Invalid scheme: {url.scheme}")

    def frontend_base_url_str(self) -> str | None:
        if self.frontend_base_url is None:
            return None
        return str(self.frontend_base_url).rstrip("/")

    @model_validator(mode="after")
    def _storage_must_be_durable(self) -> "Settings":
        if self.database_url and self.storage_encryption_key:
            return self
        if self.allow_ephemeral_oauth_storage:
            return self
        raise ValueError(
            "OAuth storage is not durable: set DATABASE_URL + STORAGE_ENCRYPTION_KEY, "
            "or set ALLOW_EPHEMERAL_OAUTH_STORAGE=true for local dev. "
            "Ephemeral storage logs out every user on pod restart."
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
