import json
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest

from mcp_scaffold import commands, openapi
from mcp_scaffold.commands import run
from mcp_scaffold.openapi import VendorSpec
from mcp_scaffold.options import Auth, Options, Persistence, Upstream
from mcp_scaffold.pins import pinned
from mcp_scaffold.repository import register
from mcp_scaffold.scaffold import scaffold
from tests.conftest import REGISTRIES, REPO, UseVenv, link_project_environment, venvs

type Config = dict[str, dict[str, dict[str, object]]]
type Scaffolded = Callable[[str], Path]


def json_response(schema: str, code: str = "200") -> dict[str, object]:
    content = {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}}
    return {code: {"description": schema, "content": content}}


# A POST comes first and a GET without a JSON body next, so the scaffold starts from getForecast.
WEATHER_PATHS: dict[str, object] = {
    "/alerts": {
        "post": {"operationId": "subscribeAlerts", "responses": json_response("Alert", "201")}
    },
    "/health": {"get": {"operationId": "ping", "responses": {"204": {"description": "Up"}}}},
    "/forecasts/{city}": {
        "get": {
            "operationId": "getForecast",
            "parameters": [
                {"name": "city", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": json_response("Forecast"),
        }
    },
}
WEATHER_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Fictional Weather API", "version": "1.0.0"},
    "servers": [{"url": "https://weather.example.com/v1/"}],
    "paths": WEATHER_PATHS,
    "components": {
        "schemas": {
            "Alert": {"type": "object", "properties": {"id": {"type": "string"}}},
            "Forecast": {
                "type": "object",
                "required": ["city", "celsius"],
                "properties": {"city": {"type": "string"}, "celsius": {"type": "number"}},
            },
        }
    },
}


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repository the scaffold can register in, beside the shared packages a new MCP uses."""
    repo = tmp_path_factory.mktemp("repo")
    for registry in REGISTRIES:
        (repo / registry).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / registry, repo / registry)
    (repo / "packages").symlink_to((REPO / "packages").resolve())
    (repo / "services").mkdir()
    (repo / "weather.json").write_text(json.dumps(WEATHER_SPEC))
    return repo


def probe(upstream: Upstream, persistence: set[Persistence], auth: Auth) -> Options:
    return Options(
        name="-".join(["probe", upstream, *sorted(persistence or {"none"}), "mcp"]),
        description="Answers questions about the probe upstream, a stand-in for a vendor API "
        "that is long enough to wrap onto a second line of the server instructions.",
        upstream=upstream,
        spec="weather.json" if upstream is Upstream.OPENAPI else None,
        persistence=frozenset(persistence),
        auth=auth,
    )


# Each option appears alone once, and the stores once together. Custom with Postgres is the one
# server that opens a resource but takes no settings with a required field. The last is every
# option at once, as services/architecture-demo-mcp is generated.
PROBES = {
    options.name: options
    for options in [
        probe(Upstream.OPENAPI, {Persistence.REDIS}, Auth.NONE),
        probe(Upstream.HTTP, set(), Auth.UNIQUE),
        probe(Upstream.CUSTOM, {Persistence.POSTGRES}, Auth.NONE),
        probe(Upstream.HTTP, {Persistence.POSTGRES, Persistence.REDIS}, Auth.NONE),
        probe(Upstream.OPENAPI, {Persistence.POSTGRES, Persistence.REDIS}, Auth.UNIQUE),
    ]
}


@pytest.fixture(scope="module")
def scaffolded(repo: Path, request: pytest.FixtureRequest) -> Iterator[Scaffolded]:
    """Scaffolds a probe the first time a test asks for it, so each test runs alone too."""
    built: dict[str, Path] = {}

    def run_linked(commands_to_run: list[list[str]], service: Path) -> None:
        link_project_environment(service)
        run(commands_to_run, service)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(commands, "run", run_linked)
        monkeypatch.setattr(openapi, "run", run_linked)

        def scaffold_probe(name: str) -> Path:
            if name not in built:
                monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(venvs(request.config) / name))
                built[name] = scaffold(PROBES[name], repo)
            return built[name]

        yield scaffold_probe


@pytest.mark.parametrize("name", PROBES)
def test_a_scaffolded_mcp_passes_its_own_checks(scaffolded: Scaffolded, name: str) -> None:
    target = scaffolded(name)

    leftovers = [
        str(path.relative_to(target))
        for path in target.rglob("*")
        if path.is_file()
        and ".venv" not in path.parts
        and "mcp_skeleton" in path.read_text(errors="ignore")
    ]
    assert not leftovers, f"files still name the skeleton package: {leftovers}"
    assert (target / "deploy" / "helm-charts" / name / "Chart.yaml").is_file()
    assert f"services/{name}" in (target / "deploy" / "Dockerfile").read_text()
    assert (target / "tests" / "tool_surface.generated.json").is_file()
    agents = (target / "AGENTS.md").read_text()
    architecture = "../../packages/mcp-architecture/ARCHITECTURE.md"
    assert f"@{architecture}" in agents
    assert (target / architecture).is_file()


def test_a_scaffolded_mcp_pins_what_the_scaffold_pins(scaffolded: Scaffolded) -> None:
    pyproject = (scaffolded("probe-custom-postgres-mcp") / "pyproject.toml").read_text()

    pins = [*pinned("service"), *pinned("service-postgres"), *pinned("service-dev")]
    assert all(f'"{pin}",' in pyproject for pin in pins)
    assert '"mcp-runtime==' in pyproject
    assert '"mcp-openapi' not in pyproject


def test_a_new_migration_keeps_the_code_style(scaffolded: Scaffolded, use_venv: UseVenv) -> None:
    service = scaffolded("probe-custom-postgres-mcp")
    use_venv(service.name)

    run([["uv", "run", "alembic", "revision", "-m", "create things"]], service)

    (migration,) = (service / "src" / "probe_custom_postgres_mcp" / "persistence").glob(
        "migrations/versions/*_create_things.py"
    )
    assert migration.read_text().startswith('"""Create things.\n')
    run(
        [["uv", "run", "ruff", "format", "--check", "."], ["uv", "run", "ruff", "check", "."]],
        service,
    )


def test_an_openapi_mcp_starts_from_the_first_json_get_of_its_spec(
    scaffolded: Scaffolded,
) -> None:
    service = scaffolded("probe-openapi-redis-mcp")
    upstream = service / "src" / "probe_openapi_redis_mcp" / "upstream"

    assert 'EXPOSED: list[str] = ["getForecast"]' in (upstream / "routes.py").read_text()
    assert "GET_FORECAST = Operation[Forecast]" in (upstream / "operations.py").read_text()
    assert "GET_FORECAST" in (upstream / "__init__.py").read_text()
    assert 'AnyHttpUrl("https://weather.example.com/v1")' in (upstream / "settings.py").read_text()
    assert (upstream / "openapi.yml").read_text().startswith("openapi: 3.0.3\n")


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (WEATHER_PATHS, "getForecast"),
        ({"/alerts": WEATHER_PATHS["/alerts"]}, "subscribeAlerts"),
    ],
    ids=["a GET first", "any operation without one"],
)
def test_a_spec_starts_from_its_first_json_operation(
    tmp_path: Path, paths: dict[str, object], expected: str
) -> None:
    (tmp_path / "spec.json").write_text(json.dumps({**WEATHER_SPEC, "paths": paths}))

    assert VendorSpec.load("spec.json", tmp_path).operation == expected


def test_a_spec_without_a_json_operation_is_rejected(tmp_path: Path) -> None:
    paths = {"/health": WEATHER_PATHS["/health"]}
    (tmp_path / "spec.json").write_text(json.dumps({**WEATHER_SPEC, "paths": paths}))

    with pytest.raises(ValueError, match="no operation"):
        VendorSpec.load("spec.json", tmp_path)


def test_a_spec_newer_than_openapi_3_0_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "spec.json").write_text(json.dumps({**WEATHER_SPEC, "openapi": "3.1.0"}))

    with pytest.raises(ValueError, match="openapi"):
        VendorSpec.load("spec.json", tmp_path)


def test_the_scaffolds_registered_their_release_and_scope(
    repo: Path, scaffolded: Scaffolded
) -> None:
    names = [scaffolded(name).name for name in PROBES]
    config = cast(Config, json.loads((repo / "release-please-config.json").read_text()))
    manifest = cast(
        dict[str, str], json.loads((repo / ".release-please-manifest.json").read_text())
    )

    assert sorted(path.name for path in (repo / "services").iterdir()) == sorted(names)
    for name in names:
        assert config["packages"][f"services/{name}"]["component"] == name
        assert manifest[f"services/{name}"] == "0.0.0"
        assert f"{name} = services/{name}/**" in (repo / ".gitcommitizen").read_text()
        assert (
            f"          - {name}\n" in (repo / ".github/workflows/release-rerun.yaml").read_text()
        )
        assert f'"!services/{name}"' in (repo / "pnpm-workspace.yaml").read_text()


def test_registering_a_name_again_lists_it_once(tmp_path: Path) -> None:
    for registry in REGISTRIES:
        (tmp_path / registry).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / registry, tmp_path / registry)
    options = Options(
        name="probe-again-mcp",
        description="Registered twice.",
        upstream=Upstream.CUSTOM,
        persistence=frozenset(),
        auth=Auth.NONE,
    )

    register(options, tmp_path, release=True)
    registered = {registry: (tmp_path / registry).read_text() for registry in REGISTRIES}
    register(options, tmp_path, release=True)

    assert {registry: (tmp_path / registry).read_text() for registry in REGISTRIES} == registered
    assert registered[".gitcommitizen"].count("probe-again-mcp = ") == 1
