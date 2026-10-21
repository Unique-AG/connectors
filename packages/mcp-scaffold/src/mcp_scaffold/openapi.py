"""An OpenAPI upstream: the vendored spec, its first operation, and the codegen's constants."""

import ast
import json
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from typing import Self, cast

import yaml
from mcp_openapi.vendoring import HTTP_METHODS, as_yaml
from pydantic import BaseModel, Field

from mcp_scaffold.commands import run
from mcp_scaffold.options import Options
from mcp_scaffold.skeleton import PACKAGE, quoted


class VendorSpec(BaseModel):
    """The vendor's OpenAPI spec, and what a new MCP takes from it."""

    text: str
    operation: str
    """What a new MCP starts with: the first operation that answers JSON, a GET if one does."""
    api_url: str | None
    url: str | None
    """Where the spec was fetched from, which `mcp-openapi-codegen --refresh-spec` reads again."""

    @classmethod
    def load(cls, source: str, repo: Path) -> Self:
        url = source if source.startswith(("http://", "https://")) else None
        if url is not None:
            with cast(HTTPResponse, urllib.request.urlopen(source, timeout=30)) as response:
                text = response.read().decode()
        else:
            text = (repo / source).read_text()
        spec = _OpenApi.model_validate(yaml.safe_load(text))
        operations = [
            (method, operation.operation_id)
            for item in spec.paths.values()
            for method, raw in item.items()
            if method in HTTP_METHODS
            for operation in [_Operation.model_validate(raw)]
            if operation.operation_id is not None and operation.answers_json
        ]
        if not operations:
            raise ValueError("the spec has no operation with an operationId that answers JSON")
        reads = [operation for method, operation in operations if method == "get"]
        servers = [
            server.url
            for server in spec.servers
            if server.url.startswith(("http://", "https://")) and "{" not in server.url
        ]
        return cls(
            text=as_yaml(text),
            operation=(reads or [operation for _, operation in operations])[0],
            api_url=servers[0].rstrip("/") if servers else None,
            url=url,
        )


def write_spec(spec: VendorSpec, target: Path) -> None:
    """Vendor the spec, and start from its first operation, served and typed both."""
    layer = target / "src" / PACKAGE / "upstream"
    (layer / "openapi.yml").write_text(spec.text)
    (layer / "routes.py").write_text(_ROUTES.format(exposed=json.dumps([spec.operation])))
    operation_ids = "operation-ids = []"
    spec_path = f'spec = "src/{PACKAGE}/upstream/openapi.yml"\n'
    edits = [
        (
            target / "pyproject.toml",
            operation_ids,
            operation_ids.replace("[]", f'["{spec.operation}"]'),
        )
    ]
    if spec.url is not None:
        edits.append(
            (
                target / "pyproject.toml",
                spec_path,
                f"{spec_path}spec-source = {quoted(spec.url)}\n",
            )
        )
    if spec.api_url is not None:
        default_url = f'AnyHttpUrl("{_EXAMPLE_API_URL}")'
        env_url = f"UPSTREAM_API_URL={_EXAMPLE_API_URL}"
        edits += [
            (
                layer / "settings.py",
                default_url,
                default_url.replace(_EXAMPLE_API_URL, spec.api_url),
            ),
            (target / ".env.example", env_url, env_url.replace(_EXAMPLE_API_URL, spec.api_url)),
        ]
    for path, old, new in edits:
        text = path.read_text()
        assert old in text, f"{path.name} no longer has {old!r}"
        path.write_text(text.replace(old, new))


def generate_operations(options: Options, target: Path) -> Path:
    """Run the codegen, and export the `Operation` constants it writes from `upstream`.

    Returns the `upstream/__init__.py` it writes, which is the scaffold's own, unlike the codegen's
    output."""
    run([["uv", "sync"], ["uv", "run", "mcp-openapi-codegen"]], target)
    upstream = target / "src" / options.package / "upstream"
    constants = [
        name.id
        for node in ast.parse((upstream / "generated" / "operations.py").read_text()).body
        if isinstance(node, ast.Assign)
        for name in node.targets
        if isinstance(name, ast.Name)
    ]
    exported = ["open_upstream", "Upstream", "upstream_http", "upstream_tools"]
    names = sorted([*exported, *constants, "UpstreamError", "UpstreamSettings"])
    (upstream / "__init__.py").write_text(
        f"""from mcp_openapi.upstream import UpstreamError

from {options.package}.upstream.client import {", ".join(sorted(exported))}
from {options.package}.upstream.generated.operations import {", ".join(constants)}
from {options.package}.upstream.settings import UpstreamSettings

__all__ = {json.dumps(names)}
"""
    )
    return upstream / "__init__.py"


class _Response(BaseModel):
    content: dict[str, object] = {}
    ref: str | None = Field(default=None, alias="$ref")


class _Operation(BaseModel):
    operation_id: str | None = Field(default=None, alias="operationId")
    # YAML reads an unquoted `200:` as an int.
    responses: dict[str | int, _Response] = {}

    @property
    def answers_json(self) -> bool:
        """mcp-openapi's codegen only types an operation whose success response is JSON."""
        return any(
            str(code).startswith("2")
            and (
                response.ref is not None
                or any(media.startswith("application/json") for media in response.content)
            )
            for code, response in self.responses.items()
        )


class _Server(BaseModel):
    url: str


class _OpenApi(BaseModel):
    """The parts of a spec the scaffold reads. It vendors the rest untouched."""

    openapi: str = Field(pattern=r"^3\.0\.", description="mcp-openapi reads OpenAPI 3.0 only")
    servers: list[_Server] = []
    paths: dict[str, dict[str, object]] = {}


_ROUTES = """\
# operationIds served as tools straight from the spec: the MCP's first version. Promote one
# to a tool of our own by removing it here, as mcp-architecture's ARCHITECTURE.md describes.
# Every other one is hidden.
EXPOSED: list[str] = {exposed}
"""
# The upstream settings' default, replaced by the spec's server.
_EXAMPLE_API_URL = "https://api.example.com"
