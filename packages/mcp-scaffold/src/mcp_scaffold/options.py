"""What a new MCP asks for: its name, what it talks to, what it stores and its auth."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class Upstream(StrEnum):
    OPENAPI = "openapi"
    HTTP = "http"
    CUSTOM = "custom"


class Persistence(StrEnum):
    POSTGRES = "postgres"
    REDIS = "redis"


class Auth(StrEnum):
    NONE = "none"
    UNIQUE = "unique"


class Options(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
    description: str = Field(min_length=1)
    upstream: Upstream
    # The vendor's OpenAPI spec, a path or an http(s) URL. Only an OpenAPI upstream has one.
    spec: str | None = None
    # Empty when the MCP stores nothing.
    persistence: frozenset[Persistence]
    auth: Auth

    @model_validator(mode="after")
    def _spec_only_for_openapi(self) -> Self:
        wanted = self.upstream is Upstream.OPENAPI
        assert wanted == (self.spec is not None), "--spec goes with --upstream openapi, and only it"
        return self

    @property
    def package(self) -> str:
        return self.name.replace("-", "_")

    @property
    def title(self) -> str:
        return self.name.replace("-", " ").title().replace("Mcp", "MCP")

    @property
    def opens_upstream(self) -> bool:
        """A custom upstream is written by hand, so the server does not open one yet."""
        return self.upstream is not Upstream.CUSTOM

    @property
    def opens_persistence(self) -> bool:
        return bool(self.persistence)

    @property
    def stores(self) -> list[Persistence]:
        """The persistence choices in a fixed order, so generated code does not depend on it."""
        return sorted(self.persistence)
