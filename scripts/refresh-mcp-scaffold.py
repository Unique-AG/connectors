"""Carry the current mcp-scaffold shell onto an existing Python MCP, then repair call sites.

Step 1 generates a throwaway service with the same upstream and stores and copies the shell
across. Tools, contexts, and the service's own upstream client stay. A hand-written Zitadel
sign-in stays too. Stamps copied from the throwaway use the HEAD commit and its committer
date, so two runs on the same commit write the same bytes.

Step 2 syncs the lock, formats with the ruff the scaffold pins, and runs basedpyright. When
the new `build_server` signature is what fails the type check, the missing persistence
argument is inserted and the type check runs once more.

From the repository root:

    python3 scripts/refresh-mcp-scaffold.py world-check-mcp

The service's pyproject says which options to pass: an OpenAPI spec, and Redis or Postgres
when those dependencies are already declared. Credentials sign-in is not inferred.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

PROBE_NAME = "probe-refresh-mcp"
STAMP = re.compile(r"mcp-scaffold-(?:version|commit): [^,\n]+, timestamp: [^\n]+")
IMPORTED_DISTRIBUTIONS = {
    "unique_mcp": "unique-mcp",
    "unique_sdk": "unique-sdk",
    "unique_toolkit": "unique-toolkit",
}
REFERENCE_SERVICE = "architecture-demo-mcp"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "service", help="kebab-case service directory under services/, ending in -mcp"
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    service = repo / "services" / args.service
    if not (service / "pyproject.toml").is_file():
        sys.exit(f"{service.relative_to(repo)} has no pyproject.toml")

    print(f"==> step 1: refresh the scaffold shell of {args.service}")
    probe_root = _render_probe(repo, service, args.service)
    try:
        _apply_shell(repo, service, probe_root / "probe", args.service)
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)

    print("==> step 2: lock, format, and repair interfaces the type check reports")
    _lock_and_sync(service)
    _ruff(service)
    diagnostics = _typecheck(service)
    if diagnostics and _repair_build_server_calls(service):
        print("inserted the persistence argument at build_server call sites")
        _ruff(service)
        diagnostics = _typecheck(service)
    if diagnostics:
        _print_diagnostics(diagnostics)
        sys.exit(1)
    print("type check passed")


def _render_probe(repo: Path, service: Path, name: str) -> Path:
    """A throwaway MCP from the current scaffold, with this service's package names."""
    project = tomllib.loads((service / "pyproject.toml").read_text())
    description = str(project["project"]["description"])
    spec = project.get("tool", {}).get("mcp-openapi", {}).get("spec")
    dependencies = [str(item) for item in project["project"]["dependencies"]]
    persistence: list[str] = []
    if any(item.startswith("py-key-value-aio") for item in dependencies):
        persistence.append("redis")
    if any(
        item.startswith(("asyncpg", "sqlalchemy", "alembic")) for item in dependencies
    ):
        persistence.append("postgres")

    parent = Path(tempfile.mkdtemp(prefix="mcp-scaffold-refresh-"))
    worktree = parent / "repo"
    probe_dir = parent / "probe"
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), "HEAD"],
            cwd=repo,
            check=True,
        )
        try:
            command = [
                "uv",
                "run",
                "--project",
                "packages/mcp-scaffold",
                "mcp-scaffold",
                PROBE_NAME,
                "--description",
                description,
                "--no-release",
            ]
            if spec:
                spec_path = (
                    spec
                    if spec.startswith(("http://", "https://"))
                    else f"services/{name}/{spec}"
                )
                command.extend(["--upstream", "openapi", "--spec", spec_path])
            elif any((service / "src").rglob("upstream/client.py")):
                command.extend(["--upstream", "custom"])
            if persistence:
                command.extend(["--persistence", *persistence])
            subprocess.run(command, cwd=worktree, check=True)
            shutil.copytree(
                worktree / "services" / PROBE_NAME,
                probe_dir,
                ignore=shutil.ignore_patterns(
                    ".venv",
                    "__pycache__",
                    ".ruff_cache",
                    ".pytest_cache",
                    ".import_linter_cache",
                ),
            )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=repo,
                check=False,
            )
            subprocess.run(["git", "worktree", "prune"], cwd=repo, check=False)
        _rename_probe(probe_dir, name)
        _normalize_stamps(probe_dir, repo)
    except Exception:
        shutil.rmtree(parent, ignore_errors=True)
        raise
    return parent


def _rename_probe(probe: Path, service: str) -> None:
    package = service.replace("-", "_")
    probe_package = PROBE_NAME.replace("-", "_")
    title = service.replace("-", " ").title().replace("Mcp", "MCP")
    probe_title = PROBE_NAME.replace("-", " ").title().replace("Mcp", "MCP")
    replacements = (
        (probe_package, package),
        (PROBE_NAME, service),
        (probe_title, title),
    )
    paths = sorted(probe.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in paths:
        if path.is_file():
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                text = ""
            renamed = text
            for old, new in replacements:
                renamed = renamed.replace(old, new)
            if renamed != text:
                path.write_text(renamed)
        renamed_name = path.name
        for old, new in replacements:
            renamed_name = renamed_name.replace(old, new)
        if renamed_name != path.name:
            path.rename(path.with_name(renamed_name))


def _normalize_stamps(probe: Path, repo: Path) -> None:
    """One stamp for the whole run, taken from HEAD so the output does not depend on the clock."""
    commit = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    committed = subprocess.run(
        ["git", "log", "-1", "--format=%cI"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    timestamp = datetime.fromisoformat(committed).astimezone(UTC)
    stamp = f"mcp-scaffold-commit: {commit}, timestamp: {timestamp.isoformat(timespec='seconds')}"
    for path in probe.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if STAMP.search(text):
            path.write_text(STAMP.sub(stamp, text, count=1))


def _apply_shell(repo: Path, service: Path, probe: Path, name: str) -> None:
    package = name.replace("-", "_")
    source = service / "src" / package
    generated = probe / "src" / package
    _copy_new(generated / "telemetry" / "setup.py", source / "telemetry" / "setup.py")
    for relative in (
        "shared/__init__.py",
        "shared/contracts/__init__.py",
        "shared/utils/__init__.py",
    ):
        _copy_new(generated / relative, source / relative)
    _copy_new(
        generated / "persistence" / "persistence.py",
        source / "persistence" / "persistence.py",
    )
    _merge_store(
        source / "persistence" / "store.py", generated / "persistence" / "store.py"
    )
    _merge_persistence_init(source / "persistence" / "__init__.py", package)
    _retire_utils(source / "utils")
    _merge_server(source / "mcp" / "server.py", package)
    _merge_main(source / "main.py", package)
    _merge_dependencies(source / "mcp" / "dependencies.py", package)
    _merge_http(source / "mcp" / "http.py", generated / "mcp" / "http.py")
    _merge_offline_server(
        service / "tests" / "offline_server.py", probe / "tests" / "offline_server.py"
    )
    _merge_conftest(service / "tests" / "conftest.py", probe / "tests" / "conftest.py")
    _append_uvicorn_test(
        service / "tests" / "test_server.py", probe / "tests" / "test_server.py"
    )
    _merge_pyproject(service / "pyproject.toml", probe / "pyproject.toml", repo, source)
    _merge_dockerfile(
        service / "deploy" / "Dockerfile", probe / "deploy" / "Dockerfile"
    )
    _merge_values(
        service / "deploy" / "helm-charts" / name / "values.yaml",
        probe / "deploy" / "helm-charts" / name / "values.yaml",
    )
    _merge_agents(service / "AGENTS.md", probe / "AGENTS.md")
    _merge_env(service / ".env.example", probe / ".env.example")


def _copy_new(generated: Path, destination: Path) -> None:
    text = generated.read_text()
    if destination.is_file() and _unstamped(destination.read_text()) == _unstamped(
        text
    ):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text)
    print(f"  wrote {destination}")


def _unstamped(text: str) -> str:
    return STAMP.sub("STAMP", text)


def _merge_store(service: Path, generated: Path) -> None:
    current = service.read_text() if service.is_file() else ""
    if "def open_store(" in current:
        return
    fresh = generated.read_text().rstrip() + "\n"
    sign_in = _extract_function(current, "sign_in_store")
    if sign_in:
        sign_in = sign_in.replace(
            "The provider exists before the server lifespan, so it gets a store of its own that lives as\n"
            "    long as the process.",
            "The provider exists before the lifespan opens `Persistence`, so it gets a store of its own\n"
            "    that lives as long as the process.",
        )
        fresh = fresh.rstrip() + "\n\n\n" + sign_in
    if service.is_file() and _unstamped(service.read_text()) == _unstamped(fresh):
        return
    service.write_text(fresh if fresh.endswith("\n") else fresh + "\n")
    print(f"  wrote {service}")


def _merge_persistence_init(path: Path, package: str) -> None:
    current = path.read_text()
    if "open_persistence" in current and "sign_in_store" in current:
        return
    stamp = _first_stamp(current)
    docstring = ""
    if current.startswith(stamp + '\n\n"""'):
        docstring = current.split('"""', 2)[1]
        docstring = f'"""{docstring}"""\n\n'
    elif '"""' in current:
        docstring = '"""' + current.split('"""', 2)[1] + '"""\n\n'
    names = ["Persistence", "PersistenceSettings", "StoreSettings", "open_persistence"]
    if "def sign_in_store(" in (path.parent / "store.py").read_text():
        names.append("sign_in_store")
    exports = ",\n    ".join(f'"{name}"' for name in names)
    imports = [
        f"from {package}.persistence.persistence import open_persistence",
        f"from {package}.persistence.persistence import Persistence",
        f"from {package}.persistence.persistence import PersistenceSettings",
    ]
    if "sign_in_store" in names:
        imports.append(f"from {package}.persistence.store import sign_in_store")
    imports.append(f"from {package}.persistence.store import StoreSettings")
    path.write_text(
        f"{stamp}\n\n{docstring}"
        + "\n".join(imports)
        + f"\n\n__all__ = [\n    {exports},\n]\n"
    )
    print(f"  wrote {path}")


def _retire_utils(utils: Path) -> None:
    init = utils / "__init__.py"
    if not init.is_file():
        return
    others = [path for path in utils.rglob("*") if path.is_file() and path != init]
    if others or re.search(r"^(?:import|from) ", init.read_text(), re.MULTILINE):
        sys.exit(f"{utils} has helpers; move them to shared/ before refreshing")
    init.unlink()
    utils.rmdir()
    print(f"  removed {utils}")


def _merge_server(path: Path, package: str) -> None:
    text = path.read_text()
    if "open_persistence:" in text:
        return
    if "def create_server(" not in text:
        sys.exit(f"{path} has no create_server")
    text = text.replace(
        "from collections.abc import AsyncGenerator\n",
        "from collections.abc import AsyncGenerator, Callable\n",
    )
    text = text.replace(
        "from contextlib import asynccontextmanager\n",
        "from contextlib import AbstractAsyncContextManager\nfrom contextlib import asynccontextmanager\n",
    )
    approval = f"from {package}.mcp.approval import ApprovalGate\n"
    persistence = f"from {package}.persistence import Persistence\n"
    if approval in text and persistence not in text:
        text = text.replace(approval, approval + persistence)
    elif (
        f"from {package}.upstream import open_upstream\n" in text
        and persistence not in text
    ):
        text = text.replace(
            f"from {package}.upstream import open_upstream\n",
            persistence + f"from {package}.upstream import open_upstream\n",
        )
    text = text.replace(
        "def create_server(\n    upstream: UpstreamSettings,\n    transport: httpx2.AsyncBaseTransport | None = None,\n    auth: AuthProvider | None = None,\n) -> FastMCP:\n",
        "def create_server(\n"
        "    upstream: UpstreamSettings,\n"
        "    open_persistence: Callable[[], AbstractAsyncContextManager[Persistence]],\n"
        "    transport: httpx2.AsyncBaseTransport | None = None,\n"
        "    *,\n"
        "    auth: AuthProvider | None = None,\n"
        ") -> FastMCP:\n"
        '    """Build the server. `open_persistence` opens every store, so the tests can open their own."""\n',
    )
    text = text.replace(
        "            open_upstream(http, upstream) as upstream_resource,\n",
        "            open_upstream(http, upstream) as upstream_resource,\n"
        "            open_persistence() as persistence_resource,\n",
    )
    text = text.replace(
        'yield {"upstream": upstream_resource, "approvals": ApprovalGate()}',
        "yield {\n"
        '                "upstream": upstream_resource,\n'
        '                "persistence": persistence_resource,\n'
        '                "approvals": ApprovalGate(),\n'
        "            }",
    )
    text = text.replace(
        'yield {"upstream": upstream_resource}',
        "yield {\n"
        '                "upstream": upstream_resource,\n'
        '                "persistence": persistence_resource,\n'
        "            }",
    )
    if "open_persistence:" not in text:
        sys.exit(f"{path} did not match the scaffold's create_server signature")
    path.write_text(text)
    print(f"  wrote {path}")


def _merge_main(path: Path, package: str) -> None:
    text = path.read_text()
    if "open_persistence" in text:
        return
    if "create_auth" not in text:
        sys.exit(
            f"{path} has no create_auth and no persistence wiring; refresh it by hand"
        )
    stamp = _first_stamp(text)
    path.write_text(
        f"""{stamp}

from functools import partial

from mcp_configs import from_environment
from mcp_configs import LoggingSettings
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings

from {package}.mcp import AuthMode
from {package}.mcp import AuthSettings
from {package}.mcp import create_auth
from {package}.mcp import create_server
from {package}.mcp import run_server
from {package}.persistence import open_persistence
from {package}.persistence import PersistenceSettings
from {package}.telemetry import init_telemetry
from {package}.upstream import UpstreamSettings


def main() -> None:
    init_telemetry(LoggingSettings())
    server_settings = ServerSettings()
    persistence_settings = PersistenceSettings()
    # Read only in zitadel mode, so a server without sign-in starts without its variables.
    zitadel = from_environment(ZitadelSettings) if AuthSettings().mode is AuthMode.ZITADEL else None
    auth = create_auth(zitadel=zitadel, server=server_settings, store=persistence_settings.store)
    persistence = partial(open_persistence, persistence_settings)
    server = create_server(from_environment(UpstreamSettings), persistence, auth=auth)
    run_server(server, server_settings)


if __name__ == "__main__":
    main()
"""
    )
    print(f"  wrote {path}")


def _merge_dependencies(path: Path, package: str) -> None:
    text = path.read_text()
    if "def get_persistence(" in text:
        return
    import_line = f"from {package}.persistence import Persistence\n"
    anchor = f"from {package}.upstream import Upstream\n"
    if anchor not in text:
        sys.exit(f"{path} does not import Upstream")
    text = text.replace(anchor, import_line + anchor)
    function = (
        "\n\ndef get_persistence(ctx: Context = CurrentContext()) -> Persistence:\n"
        '    return cast(Persistence, ctx.lifespan_context["persistence"])\n'
    )
    text = text.replace(
        "def get_upstream(ctx: Context = CurrentContext()) -> Upstream:\n",
        function + "\ndef get_upstream(ctx: Context = CurrentContext()) -> Upstream:\n",
    )
    path.write_text(text)
    print(f"  wrote {path}")


def _merge_http(service: Path, generated: Path) -> None:
    text = service.read_text()
    if "log_config" in text:
        return
    generated_text = generated.read_text()
    match = re.search(
        r"(# `None`, not `\{\}`:.*\n\s*uvicorn_config=\{[^}]+\},)",
        generated_text,
    )
    if match is None or "uvicorn_config=" not in text:
        sys.exit(f"{service} has no uvicorn_config the scaffold's http.py can replace")
    text = re.sub(r"uvicorn_config=\{[^}]+\},", match.group(1), text, count=1)
    service.write_text(text)
    print(f"  wrote {service}")


def _merge_offline_server(service: Path, generated: Path) -> None:
    if "def open_fake_persistence(" in service.read_text():
        return
    settings = _extract_function(service.read_text(), "fake_upstream_settings")
    if not settings:
        sys.exit(f"{service} has no fake_upstream_settings")
    text = generated.read_text()
    text = _first_stamp(service.read_text()) + "\n" + text.split("\n", 1)[1]
    text = _replace_function(text, "fake_upstream_settings", settings)
    service.write_text(text)
    print(f"  wrote {service}")


def _merge_conftest(service: Path, generated: Path) -> None:
    if "def persistence(" in service.read_text():
        return
    service_fixtures = set(
        re.findall(r"^def (\w+)\(", service.read_text(), re.MULTILINE)
    )
    generated_fixtures = set(
        re.findall(r"^def (\w+)\(", generated.read_text(), re.MULTILINE)
    )
    extra = service_fixtures - generated_fixtures
    if extra:
        sys.exit(f"{service} has fixtures the scaffold does not: {sorted(extra)}")
    text = (
        _first_stamp(service.read_text())
        + "\n"
        + generated.read_text().split("\n", 1)[1]
    )
    service.write_text(text)
    print(f"  wrote {service}")


def _append_uvicorn_test(service: Path, generated: Path) -> None:
    text = service.read_text()
    if "def test_uvicorn_logs_through_the_pino_handler(" in text:
        return
    function = _extract_function(
        generated.read_text(), "test_uvicorn_logs_through_the_pino_handler"
    )
    if not function:
        return
    service.write_text(text.rstrip() + "\n\n\n" + function)
    print(f"  wrote {service}")


def _merge_pyproject(service: Path, generated: Path, repo: Path, source: Path) -> None:
    current_project = tomllib.loads(service.read_text())
    fresh_project = tomllib.loads(generated.read_text())
    imported = _imported_distributions(source)
    reference = _reference_dependencies(repo)
    runtime = _merged_requirements(
        [str(item) for item in current_project["project"]["dependencies"]],
        [str(item) for item in fresh_project["project"]["dependencies"]],
        imported,
        reference,
    )
    dev = _merged_requirements(
        [str(item) for item in current_project["dependency-groups"]["dev"]],
        [str(item) for item in fresh_project["dependency-groups"]["dev"]],
        imported,
        reference,
    )
    text = _replace_toml_array(service.read_text(), "dependencies", runtime)
    text = _replace_toml_array(text, "dev", dev)
    poe = _section(generated.read_text(), "[tool.poe.tasks]")
    if "[tool.poe.tasks]" not in text:
        text = text.replace(
            "[tool.pytest.ini_options]", poe + "\n[tool.pytest.ini_options]"
        )
    text = text.replace(
        "# The code style every MCP keeps: the Google Python Style Guide as far as ruff checks it.\n"
        "# Add to it here, as for generated code, but never loosen it.\n",
        "# The code style every MCP keeps. Add to it here; a rule turned off here is an exception for review.\n",
    )
    text = text.replace('target-version = "py314"\nexclude = [".venv"]\n', "")
    if "mcp-observability = " not in text:
        text = text.replace(
            'mcp-configs = { path = "../../packages/mcp-configs" }\n',
            'mcp-configs = { path = "../../packages/mcp-configs" }\n'
            'mcp-observability = { path = "../../packages/mcp-observability" }\n',
        )
    contracts = _contracts(generated.read_text())
    text = re.sub(
        r"\n# The (?:architecture|import contracts).*\Z",
        "\n" + contracts,
        text,
        count=1,
        flags=re.DOTALL,
    )
    if text != service.read_text():
        service.write_text(text)
        print(f"  wrote {service}")


def _merge_dockerfile(service: Path, generated: Path) -> None:
    text = service.read_text()
    line = next(
        (
            item
            for item in generated.read_text().splitlines(keepends=True)
            if "packages/mcp-observability" in item
        ),
        "",
    )
    if not line or line in text:
        return
    anchor = next(
        item
        for item in text.splitlines(keepends=True)
        if "packages/mcp-configs" in item
    )
    text = text.replace(anchor, anchor + line, 1)
    service.write_text(text)
    print(f"  wrote {service}")


def _merge_values(service: Path, generated: Path) -> None:
    if not service.is_file():
        return
    fresh = next(
        (
            line
            for line in generated.read_text().splitlines()
            if "configure_logging" in line
        ),
        "",
    )
    text = service.read_text()
    current = next(
        (line for line in text.splitlines() if "configure_logging" in line), ""
    )
    if not fresh or not current or fresh == current:
        return
    service.write_text(text.replace(current, fresh, 1))
    print(f"  wrote {service}")


def _merge_agents(service: Path, generated: Path) -> None:
    text = service.read_text()
    if "Persistence.store" in text:
        return
    current = next(
        (line for line in text.splitlines() if line.startswith("- Persistence:")), ""
    )
    fresh = next(
        (
            line
            for line in generated.read_text().splitlines()
            if line.startswith("- Persistence:")
        ),
        "",
    )
    if not current or not fresh:
        return
    merged = fresh
    if "sign-in state only" in current:
        merged = merged.rstrip(".") + ", for Zitadel sign-in state only (`REDIS_URL`)."
    if "No screening records." in current:
        merged = merged + " No screening records."
    service.write_text(text.replace(current, merged, 1))
    print(f"  wrote {service}")


def _merge_env(service: Path, generated: Path) -> None:
    text = service.read_text()
    if re.search(r"^REDIS_URL=", text, re.MULTILINE):
        return
    redis = next(
        (
            line
            for line in generated.read_text().splitlines()
            if line.startswith("REDIS_URL=")
        ),
        "REDIS_URL=redis://localhost:6379/0",
    )
    text = re.sub(r"^# REDIS_URL=.*\n", "", text, count=1, flags=re.MULTILINE)
    marker = "# Tracing is opt-in"
    if marker in text:
        text = text.replace(marker, f"{redis}\n\n{marker}", 1)
    else:
        text = text.rstrip() + f"\n\n{redis}\n"
    service.write_text(text)
    print(f"  wrote {service}")


def _merged_requirements(
    current: list[str], fresh: list[str], imported: set[str], reference: dict[str, str]
) -> list[str]:
    """Keep the service's order. Versions come from the scaffold; a dependency it dropped stays
    when the service still imports it, pinned like the reference MCP."""
    fresh_by_name = {_distribution(item): item for item in fresh}
    merged: list[tuple[str, str]] = []
    for item in current:
        name = _distribution(item)
        if name in fresh_by_name:
            chosen = fresh_by_name[name]
            merged.append((name, _with_extras(chosen, _extras(chosen) | _extras(item))))
        elif name in imported:
            chosen = reference.get(name, item)
            merged.append((name, _with_extras(chosen, _extras(chosen) | _extras(item))))
    present = {name for name, _requirement in merged}
    fresh_names = [_distribution(item) for item in fresh]
    for item in fresh:
        name = _distribution(item)
        if name in present:
            continue
        index = fresh_names.index(name)
        insert_at = len(merged)
        for later in fresh_names[index + 1 :]:
            positions = [
                position
                for position, (existing, _) in enumerate(merged)
                if existing == later
            ]
            if positions:
                insert_at = positions[0]
                break
        else:
            for earlier in reversed(fresh_names[:index]):
                positions = [
                    position
                    for position, (existing, _) in enumerate(merged)
                    if existing == earlier
                ]
                if positions:
                    insert_at = positions[0] + 1
                    break
        merged.insert(insert_at, (name, _with_extras(item, _extras(item))))
        present.add(name)
    return [requirement for _name, requirement in merged]


def _reference_dependencies(repo: Path) -> dict[str, str]:
    path = repo / "services" / REFERENCE_SERVICE / "pyproject.toml"
    if not path.is_file():
        return {}
    project = tomllib.loads(path.read_text())
    return {
        _distribution(str(item)): str(item)
        for item in project["project"]["dependencies"]
    }


def _imported_distributions(source: Path) -> set[str]:
    found: set[str] = set()
    for path in source.rglob("*.py"):
        text = path.read_text()
        for module, distribution in IMPORTED_DISTRIBUTIONS.items():
            if re.search(rf"^(?:import|from) {module}\b", text, re.MULTILINE):
                found.add(distribution)
    return found


def _distribution(requirement: str) -> str:
    return re.split(r"[\[=<>!~ ]", requirement, maxsplit=1)[0]


def _extras(requirement: str) -> set[str]:
    match = re.search(r"\[([^\]]+)\]", requirement)
    return set(match.group(1).split(",")) if match else set()


def _with_extras(requirement: str, extras: set[str]) -> str:
    name = _distribution(requirement)
    version = requirement.split("==", 1)[1]
    bracket = f"[{','.join(sorted(extras))}]" if extras else ""
    return f"{name}{bracket}=={version}"


def _replace_toml_array(text: str, key: str, items: list[str]) -> str:
    body = ",\n".join(f'    "{item}"' for item in items)
    pattern = rf"{re.escape(key)} = \[\n(?:.*\n)*?\]"
    replacement = f"{key} = [\n{body},\n]"
    new, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        sys.exit(f"did not find a {key} array in pyproject.toml")
    return new


def _section(text: str, header: str) -> str:
    start = text.index(header)
    end = text.find("\n[", start + len(header))
    return text[start:end].rstrip() + "\n"


def _contracts(text: str) -> str:
    marker = "# The import contracts every MCP keeps"
    if marker not in text:
        sys.exit("the scaffold pyproject has no import-linter contracts")
    return text[text.index(marker) :].rstrip() + "\n"


def _extract_function(source: str, name: str) -> str:
    match = re.search(rf"^def {name}\(.*(?:\n(?!def |class ).*)*", source, re.MULTILINE)
    return match.group(0).rstrip() + "\n" if match else ""


def _replace_function(source: str, name: str, replacement: str) -> str:
    pattern = rf"^def {name}\(.*(?:\n(?!def |class ).*)*"
    new, count = re.subn(
        pattern, replacement.rstrip() + "\n", source, count=1, flags=re.MULTILINE
    )
    if count != 1:
        sys.exit(f"did not find def {name}")
    return new


def _first_stamp(text: str) -> str:
    match = STAMP.search(text)
    if match is None:
        sys.exit("a scaffold file is missing its stamp")
    line_start = text.rfind("\n", 0, match.start()) + 1
    return text[line_start : match.end()]


def _lock_and_sync(service: Path) -> None:
    subprocess.run(["uv", "lock"], cwd=service, check=True)
    subprocess.run(["uv", "sync"], cwd=service, check=True)


def _ruff(service: Path) -> None:
    # Format first: a repaired call is one long line, and ruff check does not wrap it.
    subprocess.run(["uv", "run", "ruff", "format", "."], cwd=service, check=True)
    subprocess.run(
        ["uv", "run", "ruff", "check", "--fix", "."], cwd=service, check=True
    )
    subprocess.run(["uv", "run", "ruff", "format", "."], cwd=service, check=True)


def _typecheck(service: Path) -> list[dict[str, object]]:
    completed = subprocess.run(
        ["uv", "run", "basedpyright", "--outputjson"],
        cwd=service,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        sys.exit(completed.returncode)
    diagnostics = [
        item
        for item in payload.get("generalDiagnostics", [])
        if item.get("severity") == "error"
    ]
    return diagnostics


def _repair_build_server_calls(service: Path) -> bool:
    changed = False
    for path in (service / "tests").rglob("*.py"):
        text = path.read_text()
        rewritten, did = _rewrite_build_server_calls(text)
        if not did:
            continue
        if "from key_value.aio.stores.memory import MemoryStore" not in rewritten:
            rewritten = (
                "from key_value.aio.stores.memory import MemoryStore\n" + rewritten
            )
        if "import Persistence" not in rewritten and "Persistence(" in rewritten:
            package = service.name.replace("-", "_")
            rewritten = f"from {package}.persistence import Persistence\n" + rewritten
        path.write_text(rewritten)
        changed = True
        print(f"  repaired {path}")
    return changed


def _rewrite_build_server_calls(source: str) -> tuple[str, bool]:
    pieces: list[str] = []
    cursor = 0
    changed = False
    needle = "build_server("
    while True:
        found = source.find(needle, cursor)
        if found == -1:
            pieces.append(source[cursor:])
            break
        if source[max(0, found - 4) : found] == "def ":
            pieces.append(source[cursor : found + len(needle)])
            cursor = found + len(needle)
            continue
        open_paren = found + len(needle) - 1
        close = _matching_paren(source, open_paren)
        arguments = _split_arguments(source[open_paren + 1 : close])
        pieces.append(source[cursor:found])
        if len(arguments) == 2 and not any(
            "Persistence" in argument or argument.strip() == "persistence"
            for argument in arguments
        ):
            pieces.append(
                f"build_server({arguments[0]}, Persistence(store=MemoryStore()), {arguments[1]})"
            )
            changed = True
        else:
            pieces.append(source[found : close + 1])
        cursor = close + 1
    return "".join(pieces), changed


def _matching_paren(source: str, open_paren: int) -> int:
    depth = 0
    for index in range(open_paren, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    sys.exit("unbalanced build_server call")


def _split_arguments(arguments: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(arguments):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(arguments[start:index].strip())
            start = index + 1
    tail = arguments[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _print_diagnostics(diagnostics: list[dict[str, object]]) -> None:
    print("type check failed:", file=sys.stderr)
    for item in diagnostics:
        print(
            f"  {item.get('file')}:{item.get('range')} {item.get('message')}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
