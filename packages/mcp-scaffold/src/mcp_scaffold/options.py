"""What a new MCP asks for: its name, what it talks to and what it stores. Auth is not asked:
the `new-mcp` skill works it out with the user once the MCP exists."""

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator


class Upstream(StrEnum):
    """`openapi` is mcp-openapi's typed client over the vendor's spec. `custom` is a small HTTP
    client to start from, which the agent shapes to the upstream with the user."""

    OPENAPI = "openapi"
    CUSTOM = "custom"


class Persistence(StrEnum):
    POSTGRES = "postgres"
    REDIS = "redis"


class Options(BaseModel):
    name: str
    description: str = Field(min_length=1)
    # None when the MCP calls no system of its own, such as one that only works over its storage.
    upstream: Upstream | None = None
    # The vendor's OpenAPI spec, a path or an http(s) URL. Only an OpenAPI upstream has one.
    spec: str | None = None
    # Empty when the MCP stores nothing.
    persistence: frozenset[Persistence]

    @field_validator("name")
    @classmethod
    def _kebab_case_ending_in_mcp(cls, name: str) -> str:
        """The `-mcp` suffix also keeps the package name from being a Python keyword."""
        if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*-mcp", name):
            raise ValueError("must be kebab-case and end in -mcp, e.g. weather-mcp")
        return name

    @model_validator(mode="after")
    def _spec_only_for_openapi(self) -> Self:
        if (self.upstream is Upstream.OPENAPI) != (self.spec is not None):
            raise ValueError("--spec goes with --upstream openapi, and only it")
        return self

    @property
    def package(self) -> str:
        return self.name.replace("-", "_")

    @property
    def title(self) -> str:
        return self.name.replace("-", " ").title().replace("Mcp", "MCP")

    @property
    def opens_upstream(self) -> bool:
        return self.upstream is not None

    @property
    def opens_persistence(self) -> bool:
        return bool(self.persistence)

    @property
    def stores(self) -> list[Persistence]:
        """The persistence choices in a fixed order, so generated code does not depend on it."""
        return sorted(self.persistence)
