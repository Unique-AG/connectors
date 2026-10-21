import ast
import json
import re
import shutil
import tomllib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
import yaml
from pydantic import ValidationError

from mcp_scaffold import commands, openapi
from mcp_scaffold.commands import run
from mcp_scaffold.openapi import VendorSpec
from mcp_scaffold.options import Options, Persistence, Upstream
from mcp_scaffold.pins import pinned, scaffold_version
from mcp_scaffold.pyproject import edit_pyproject
from mcp_scaffold.repository import register
from mcp_scaffold.scaffold import load_spec, scaffold
from mcp_scaffold.skeleton import NAME, PACKAGE, copy_skeleton, render_templates
from mcp_scaffold.stamp import stamped
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


def probe(upstream: Upstream | None, persistence: set[Persistence]) -> Options:
    return Options(
        name="-".join(["probe", upstream or "none", *sorted(persistence or {"none"}), "mcp"]),
        description="Answers questions about the probe upstream, a stand-in for a vendor API "
        "that is long enough to wrap onto a second line of the server instructions.",
        upstream=upstream,
        spec="weather.json" if upstream is Upstream.OPENAPI else None,
        persistence=frozenset(persistence),
    )


# Each upstream and each store appears at least once, and the stores once together. The first
# opens nothing, so its server has no lifespan; the next two open only an upstream or only a
# store. The last is every option at once: an OpenAPI upstream with Postgres and Redis.
PROBES = {
    options.name: options
    for options in [
        probe(None, set()),
        probe(Upstream.OPENAPI, set()),
        probe(None, {Persistence.REDIS}),
        probe(Upstream.CUSTOM, {Persistence.POSTGRES}),
        probe(Upstream.CUSTOM, {Persistence.POSTGRES, Persistence.REDIS}),
        probe(Upstream.OPENAPI, {Persistence.POSTGRES, Persistence.REDIS}),
    ]
}
STAMP = re.compile(
    r"mcp-scaffold-version: (?P<version>[^,]+), timestamp: (?P<timestamp>[0-9T:+-]+)"
)
# What a tool writes rather than the scaffold: uv, the codegen, pytest and the chart's schema
# script.
NOT_THE_SCAFFOLDS = {
    "uv.lock",
    "operations.py",
    "vendor_responses.py",
    "tool_surface.generated.json",
    "values.schema.json",
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
                built[name] = scaffold(PROBES[name], repo, spec=load_spec(PROBES[name], repo))
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
    chart = (target / "deploy" / "helm-charts" / name / "Chart.yaml").read_text()
    assert f"description: {json.dumps(PROBES[name].description)}\n" in chart
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
    assert '"mcp-configs==' in pyproject
    assert '"mcp-openapi==' in pyproject
    assert "mcp-openapi[codegen]" not in pyproject
    assert "[tool.mcp-openapi]" not in pyproject


def test_a_new_migration_keeps_the_code_style(scaffolded: Scaffolded, use_venv: UseVenv) -> None:
    service = scaffolded("probe-custom-postgres-mcp")
    use_venv(service.name)

    run([["uv", "run", "alembic", "revision", "-m", "create things"]], service)

    (migration,) = (service / "src" / "probe_custom_postgres_mcp" / "persistence").glob(
        "migrations/versions/*_create_things.py"
    )
    assert migration.read_text().startswith('"""Create things.\n')
    assert not STAMP.search(migration.read_text())
    run(
        [["uv", "run", "ruff", "format", "--check", "."], ["uv", "run", "ruff", "check", "."]],
        service,
    )


@pytest.mark.parametrize("name", ["probe-none-none-mcp", "probe-none-redis-mcp"])
def test_an_mcp_without_an_upstream_keeps_the_layer_empty(
    scaffolded: Scaffolded, name: str
) -> None:
    target = scaffolded(name)
    package = target / "src" / name.replace("-", "_")

    assert [path.name for path in (package / "upstream").iterdir()] == ["__init__.py"]
    assert "__all__: list[str] = []" in (package / "upstream" / "__init__.py").read_text()
    assert "UPSTREAM_" not in (target / ".env.example").read_text()
    assert "get_upstream" not in (package / "mcp" / "dependencies.py").read_text()
    assert not (target / "tests" / "test_upstream.py").exists()
    assert "mcp-openapi" not in (target / "pyproject.toml").read_text()


def test_an_openapi_mcp_starts_from_the_first_json_get_of_its_spec(
    scaffolded: Scaffolded,
) -> None:
    service = scaffolded("probe-openapi-none-mcp")
    upstream = service / "src" / "probe_openapi_none_mcp" / "upstream"

    assert 'EXPOSED: list[str] = ["getForecast"]' in (upstream / "routes.py").read_text()
    operations = upstream / "generated" / "operations.py"
    assert "GET_FORECAST = Operation[Forecast]" in operations.read_text()
    assert "GET_FORECAST" in (upstream / "__init__.py").read_text()
    assert 'AnyHttpUrl("https://weather.example.com/v1")' in (upstream / "settings.py").read_text()
    assert (upstream / "openapi.yml").read_text().splitlines()[1] == "openapi: 3.0.3"


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


@pytest.mark.parametrize(
    "description",
    [
        "Reads the long-range forecast of a city from the fictional weather service, as listed "
        "at https://weather.example.com/v1/forecasts/long-range/cities/by-region/and-by-country",
        "Answers weather questions \u26c5 and storm warnings \U0001f329 for a city.",
    ],
    ids=["a hyphen and a long URL", "an emoji"],
)
def test_the_description_reaches_every_file_as_given(tmp_path: Path, description: str) -> None:
    options = Options(name="probe-text-mcp", description=description, persistence=frozenset())
    target = tmp_path / "probe-text-mcp"
    copy_skeleton(target)
    render_templates(options, target)
    edit_pyproject(options, target, REPO)

    pyproject = tomllib.loads((target / "pyproject.toml").read_text())
    chart = (target / "deploy" / "helm-charts" / NAME / "Chart.yaml").read_text()
    server = ast.parse((target / "src" / PACKAGE / "mcp" / "server.py").read_text())
    (instructions,) = [
        node.value
        for node in server.body
        if isinstance(node, ast.Assign)
        and [ast.unparse(name) for name in node.targets] == ["INSTRUCTIONS"]
    ]

    assert pyproject["project"]["description"] == description
    assert cast(dict[str, object], yaml.safe_load(chart))["description"] == description
    assert ast.literal_eval(instructions) == description


def test_a_description_of_only_whitespace_is_rejected() -> None:
    with pytest.raises(ValidationError, match="description"):
        Options(name="probe-text-mcp", description=" \n ", persistence=frozenset())


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
    )

    register(options, tmp_path, release=True)
    registered = {registry: (tmp_path / registry).read_text() for registry in REGISTRIES}
    register(options, tmp_path, release=True)

    assert {registry: (tmp_path / registry).read_text() for registry in REGISTRIES} == registered
    assert registered[".gitcommitizen"].count("probe-again-mcp = ") == 1


@pytest.mark.parametrize("name", ["probe-openapi-none-mcp", "probe-custom-postgres-redis-mcp"])
def test_every_file_the_scaffold_wrote_carries_the_same_stamp(
    scaffolded: Scaffolded, name: str
) -> None:
    target = scaffolded(name)
    files = [
        path
        for path in target.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not {".venv", ".ruff_cache", ".import_linter_cache", ".pytest_cache", "__pycache__"}
        & set(path.parts)
        and path.name not in NOT_THE_SCAFFOLDS
    ]

    stamps = {
        path.relative_to(target).as_posix(): [
            match.groups() for match in STAMP.finditer(path.read_text())
        ]
        for path in files
    }

    assert {path: found for path, found in stamps.items() if len(found) != 1} == {}
    assert {found[0][0] for found in stamps.values()} == {scaffold_version()}
    (timestamp,) = {found[0][1] for found in stamps.values()}
    assert abs(datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds() < 3600


def test_tool_output_is_not_stamped(scaffolded: Scaffolded) -> None:
    target = scaffolded("probe-openapi-none-mcp")
    generated = target / "src" / "probe_openapi_none_mcp" / "upstream" / "generated"

    for path in [
        target / "uv.lock",
        generated / "operations.py",
        generated / "vendor_responses.py",
    ]:
        assert not STAMP.search(path.read_text()), path.name


def test_the_stamp_follows_a_line_that_has_to_stay_first(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("# syntax=docker/dockerfile:1.7\n\nFROM python\n")
    script = tmp_path / "render.sh"
    script.write_text("#!/bin/bash\nhelm template\n")

    assert (
        stamped(dockerfile, "stamp") == "# syntax=docker/dockerfile:1.7\n# stamp\n\nFROM python\n"
    )
    assert stamped(script, "stamp") == "#!/bin/bash\n# stamp\nhelm template\n"


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("models.py", "import ast\n", "# stamp\n\nimport ast\n"),
        ("__init__.py", "", "# stamp\n"),
        ("AGENTS.md", "# Title\n", "<!-- stamp -->\n# Title\n"),
        ("script.py.mako", "<% x = 1 %>\n", "## stamp\n<% x = 1 %>\n"),
        ("_helpers.tpl", "{{/* helpers */}}\n", "{{/* stamp */}}\n{{/* helpers */}}\n"),
        (
            "schema.json",
            '{\n  "type": "object"\n}\n',
            '{\n  "$comment": "stamp",\n  "type": "object"\n}\n',
        ),
    ],
)
def test_the_stamp_is_a_comment_in_the_files_own_syntax(
    tmp_path: Path, name: str, text: str, expected: str
) -> None:
    path = tmp_path / name
    path.write_text(text)

    assert stamped(path, "stamp") == expected


def test_a_file_without_a_known_comment_syntax_fails_the_stamp(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("notes\n")

    with pytest.raises(AssertionError, match="no comment syntax for notes.txt"):
        stamped(path, "stamp")
