"""All configuration for kb-mcp.

If it reads the environment, it is declared in this file. No exceptions.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastmcp.server.server import Transport
from pydantic import (
    Field,
    HttpUrl,
    PostgresDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from unique_mcp.util.find_env_file import find_env_file

# main.py also loads this into the process env for libraries that bypass Settings.
ENV_FILE: Path | None = find_env_file(filenames=["kb_mcp.env", ".env"], required=False)

KNOWN_MCP_TOOLS = frozenset({"search", "content_tree", "read_file"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Env vars win over the file, unlike load_dotenv(override=True).
        env_file=ENV_FILE,
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
    zitadel_base_url: str
    zitadel_client_id: str
    zitadel_client_secret: SecretStr

    # ── OAuth storage (see auth/storage.py) ──
    database_url: PostgresDsn | None = Field(default=None)
    # Raw hex (openssl rand -hex 32) — auth/storage.py derives the Fernet
    # key kb-mcp actually needs from these bytes.
    encryption_key: SecretStr | None = Field(default=None, min_length=64, max_length=64)
    allow_ephemeral_oauth_storage: bool = Field(
        default=False,
        description=("DEV ONLY. Per-pod storage that loses all sessions on restart."),
    )

    # ── Content-tree cache ──
    content_tree_cache_ttl_seconds: int = Field(
        default=1800, validation_alias="KB_SEARCH_CONTENT_TREE_CACHE_TTL_SECONDS"
    )
    content_tree_cache_max_entries: int = Field(
        default=128, validation_alias="KB_SEARCH_CONTENT_TREE_CACHE_MAX_ENTRIES"
    )

    # ── Search scope lookups ──
    scope_lookup_concurrency: int = Field(default=8, ge=1)

    # ── MCP tool allowlist ──
    enabled_tools: Annotated[frozenset[str], NoDecode] = Field(
        default=KNOWN_MCP_TOOLS,
        description=(
            "Comma-separated tool names advertised on /mcp. Unset = all. "
            "Search-only ship: search,read_file (keep read_file so hits "
            "can still be opened). Restart required."
        ),
        validation_alias="KB_MCP_ENABLED_TOOLS",
    )

    @field_validator("enabled_tools", mode="before")
    @classmethod
    def _parse_enabled_tools(cls, value: object) -> frozenset[str]:
        if value is None or value == "":
            return KNOWN_MCP_TOOLS
        if isinstance(value, (frozenset, set, list, tuple)):
            names = {str(item).strip() for item in value if str(item).strip()}
        else:
            names = {part.strip() for part in str(value).split(",") if part.strip()}
        if not names:
            raise ValueError(
                "KB_MCP_ENABLED_TOOLS is empty. Known tools: "
                + ", ".join(sorted(KNOWN_MCP_TOOLS))
            )
        unknown = names - KNOWN_MCP_TOOLS
        if unknown:
            raise ValueError(
                "Unknown tool(s) in KB_MCP_ENABLED_TOOLS: "
                + ", ".join(sorted(unknown))
                + ". Known: "
                + ", ".join(sorted(KNOWN_MCP_TOOLS))
            )
        return frozenset(names)

    def disabled_tool_names(self) -> frozenset[str]:
        return KNOWN_MCP_TOOLS - self.enabled_tools

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
        durable = bool(self.database_url and self.encryption_key)
        half = bool(self.database_url) ^ bool(self.encryption_key)
        if half:
            raise ValueError(
                "OAuth storage is half-configured: set BOTH DATABASE_URL and "
                "ENCRYPTION_KEY, or neither (with "
                "ALLOW_EPHEMERAL_OAUTH_STORAGE=true for local dev)."
            )
        if durable and self.allow_ephemeral_oauth_storage:
            # Otherwise build_storage() would ignore Postgres and write to /tmp.
            raise ValueError(
                "Refuse ALLOW_EPHEMERAL_OAUTH_STORAGE when DATABASE_URL and "
                "ENCRYPTION_KEY are set — pick durable or ephemeral, not both."
            )
        if durable:
            assert self.encryption_key is not None
            try:
                bytes.fromhex(self.encryption_key.get_secret_value())
            except ValueError as exc:
                raise ValueError(
                    "ENCRYPTION_KEY is the right length but not valid hex. "
                    "Generate one with: openssl rand -hex 32"
                ) from exc
            return self
        if self.allow_ephemeral_oauth_storage:
            return self
        raise ValueError(
            "OAuth storage is not durable: set DATABASE_URL + ENCRYPTION_KEY, "
            "or set ALLOW_EPHEMERAL_OAUTH_STORAGE=true for local dev. "
            "Ephemeral storage logs out every user on pod restart."
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
