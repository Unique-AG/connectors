"""The structural rules this package's layout depends on.

**A tool is a file, and these are the rules that keep it one.** `tools/get_me.py` owns its name, the
prose that teaches a model when to reach for it, its Graph permissions, its arguments, its answer
shape, its request and its refusals. `shared/` is what a second tool will not be free to disagree
with it about. `graph_client/` is the transport they borrow. What follows is the whole of what that
costs, numbered as the finished layout numbers it — three of the eight rules cannot be asserted with
one tool and one shared module, and they are named below where they are missing rather than
renumbered around, so that the PR that makes one assertable adds a class and changes nothing else.

`features/`, which was to hold what a tool did, and the tool-declaration module `server/` was to
hold, are the shape this replaces; the first is deleted here and the second was never written. The
two numbered rules that held those halves apart went with them.

1. **`shared/` imports no tool module, and only `shared/seam.py` imports FastMCP.** `shared/` is
   what two tools must not disagree about; a tool is what disagrees. The direction is therefore
   one-way by construction. The FastMCP half is narrower than a blanket ban because it has to be:
   the On-Behalf-Of token dependency and the `ToolError` a Graph refusal becomes are exactly the
   things every tool must say identically, and they are FastMCP types. So they are allowed in one
   named file — the seam — and nowhere else, which is what keeps the framework out of the rest of
   the vocabulary: `identity.py` today, and everything that joins it.

2. **`graph_client/` imports nothing of this application.** Not `shared/`, not `tools/`, not
   `config`, not anything else under `office_mcp` — the transport is infrastructure its callers
   consume, and it takes its own frozen `GraphSettings` rather than reading config, because a
   transport is allowed to be *told* and not to be configured. Anything it imported back would be a
   package cycle and a second place the environment is read.

3. **`tools/` imports `shared/`, `graph_client/` and FastMCP, and nothing else of this package.**
   Those three are the whole of what a tool file is allowed to lean on: the vocabulary, the
   transport, the framework. Not `server/` — a tool that reached into it would be a tool file in
   name only, with its wiring somewhere else, which is the shape this layout exists to avoid.

5. **A config class is only instantiated at the composition root.** `create_app` builds each one
   exactly once and injects it; anything downstream constructing its own re-reads the environment
   and so silently ignores what it was given — which is how a tool ends up configured differently
   from the app it runs in. Reading config types (annotations, imports) is unrestricted; only
   *calling* them is the violation. `main.py` is exempt as a process entrypoint: it is the root of
   its own program and hands `create_app` the config it built.

8. **A package is entered through its `__init__`, never through its modules.** Applies to the
   packages in `_PUBLIC_SURFACE_PACKAGES`: `graph_client/`, `server/` and `tools/`, each of which
   publishes an `__all__` that is the whole of what it promises. Reaching past one means
   assembling collaborators the package is responsible for assembling — which is how a tool came
   to re-read its own config and ignore what `create_app` was given — and on `tools/` it is
   precisely how somebody imports `tools/get_me.py` directly and stops the registry being the one
   place every tool module is named — which is the list a selection is filtered over and every
   Graph scope sign-in asks for is derived from.

   `shared/` is deliberately not listed, because it publishes no surface. It is a grouping whose
   `__init__` is documentation and whose *modules* are the units — `shared/identity.py` is who the
   signed-in user is, `shared/seam.py` is how a tool is attached to the outside — and every consumer
   names which of them it depends on at the import line. That visibility is what the package is
   *for*, so an `__init__` re-exporting the lot would hide the one thing it exists to show. A
   package joins the list as soon as its `__init__` exports anything.

**Rules 4, 6 and 7 are absent, and each is absent because it would hold vacuously.** Every rule here
is paired with a guard that fails if the rule has stopped having anything to check — an empty tree
to walk, a missing file to forbid reaching past, a framework nothing imports any more, a package
with no `__all__` to insist on — and the same discipline says a rule may not arrive before its
guard can pass. A rule that is written down while it forbids nothing is a rule that gets deleted for
the wrong reason later, or worse, kept while the thing it covers quietly leaves.

* **Rule 4, no tool module imports another tool module** — the rule this layout exists for — needs
  two tool modules to have anything to say, and its guard in the finished tree asserts exactly that.
  It arrives with the second tool.
* **Rule 6, one speller per handle family: `shared/handles.py` alone builds or parses a `teams:///`
  URI** — needs a handle. Nothing here mints one: a profile is not addressable. It arrives with the
  first tool whose answer is another tool's argument, which is the same PR as rule 4's.
* **Rule 7, no module addresses a single meeting recording** — the permanent one, and the only door
  to a recording's bytes — needs a recordings listing to be the surface it protects. It arrives with
  the tool that lists them.

None of the rules that *are* here is conditional: every package they are about exists today, so a
rule that stops running is a failure and not a skip.

All rules are asserted by walking the AST rather than importing anything, so a violation is
reported as a failing test with a file and line instead of an ImportError at collection time.
"""

import ast
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).parent.parent / "src" / "office_mcp"

_SHARED = _SRC / "shared"
_TOOLS = _SRC / "tools"
_GRAPH_CLIENT = _SRC / "graph_client"

_PACKAGE = "office_mcp"
_SHARED_PREFIX = "office_mcp.shared"
_TOOLS_PREFIX = "office_mcp.tools"
_SERVER_PREFIX = "office_mcp.server"
_CONFIG_MODULE = "office_mcp.config"
_GRAPH_CLIENT_PREFIX = "office_mcp.graph_client"
_MCP_FRAMEWORK = "fastmcp"

# Packages that publish a surface: outside code imports the package, never a module inside it.
# Tests are deliberately exempt — the rule walks `src` only — so the pieces a package composes stay
# directly testable without being callable from production code that should go through the front
# door. `shared/` is not here on purpose; see rule 8.
_PUBLIC_SURFACE_PACKAGES: tuple[str, ...] = (
    "office_mcp.graph_client",
    "office_mcp.server",
    "office_mcp.tools",
)

# The one file under `shared/` that is allowed to speak MCP, because being the seam is what it is
# for. Named rather than pattern-matched: the exemption is a decision about one file.
_SEAM = _SHARED / "seam.py"

# The `BaseSettings` classes in config.py, which read the environment when constructed.
_CONFIG_CLASSES = frozenset({"AppConfig", "DatabaseConfig", "EntraConfig", "SurfaceConfig"})

# Files allowed to construct one, relative to `_SRC`. Both are the root of a program: `app.py` is
# the composition root, and `main.py` is the server entrypoint that hands it its `AppConfig`.
_COMPOSITION_ROOTS = frozenset({"app.py", "main.py"})


def _sources(directory: pathlib.Path) -> list[pathlib.Path]:
    return sorted(directory.rglob("*.py"))


def _tool_modules() -> list[pathlib.Path]:
    """The tool files: everything under `tools/` except the registry that composes them."""
    return [source for source in _sources(_TOOLS) if source.name != "__init__.py"]


def _imported_modules(tree: ast.AST, package: str | None = None) -> list[tuple[str, int]]:
    """Every module name this file imports, with the line it's imported on.

    A relative import (`level > 0`) is resolved to an absolute dotted name against `package` —
    the importing file's own `__package__` — before it's reported. Without that resolution,
    `from ..server.readiness import ready_response` inside `tools/get_me.py` would never spell
    `server` at `level == 0` and would be invisible to every rule below. Without a `package`
    (the ad-hoc source snippets in `TestTheDetectionItself` below, which name no real file),
    relative imports are skipped: there is nothing to resolve them against.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    found.append((node.module, node.lineno))
            elif package is not None:
                resolved = _resolved_import_target(package, node.level, node.module)
                if resolved is not None:
                    found.append((resolved, node.lineno))
    return found


def _imported_members(tree: ast.AST, package: str | None = None) -> list[tuple[str, int]]:
    """Every `from X import name`, as the module `name` would be if it is one, with its line.

    The blind spot this exists for: `from .. import tools as _tools` inside `shared/identity.py`
    imports the module `office_mcp` and binds the whole tool package under a name, so every tool
    module is an attribute of it and no rule above ever sees one. `from office_mcp import tools` is
    the same import spelled absolutely. Both are caught here, and under any alias, because the alias
    is the *binding* and `alias.name` is what was imported.

    Matched **exactly** by the rules that use this, never as a prefix: `from office_mcp.shared
    import identity` names a module of a package nothing forbids, and `from office_mcp.graph_client
    import graph_client_for` names a function rather than a module at all. Only a member that *is*
    the forbidden package is a violation of anything.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 0:
            base = node.module
        elif package is not None:
            base = _resolved_import_target(package, node.level, node.module)
        else:
            base = None
        if base is None:
            continue
        found.extend((f"{base}.{alias.name}", node.lineno) for alias in node.names)
    return found


def _resolved_import_target(package: str, level: int, module: str | None) -> str | None:
    """The absolute dotted module a relative import's `level`/`module` resolve to.

    Mirrors Python's own relative-import resolution: `level` dots walk up from `package` (the
    importing file's `__package__`) by `level - 1` components, and `module` — if the import
    names one (`from . import x` doesn't) — is appended beneath that. Returns `None` if the
    import walks above the top of the tree, which `ast` parses fine but Python raises
    `ImportError` for at runtime.
    """
    parts = package.split(".")
    remaining = len(parts) - (level - 1)
    if remaining < 0:
        return None
    base = parts[:remaining]
    if module:
        base = base + module.split(".")
    return ".".join(base) if base else None


def _dotted_module(source: pathlib.Path) -> str:
    """The dotted module name `source` would import as, e.g. `office_mcp.tools.get_me`.

    Found by anchoring on the `office_mcp` directory in `source`'s own path, rather than by
    relativizing against the module-level `_SRC` constant — so a temporary copy of the tree
    (as `TestTheDetectionItself` below uses to prove the escape is caught) resolves the same
    way the real `src/office_mcp` does.
    """
    parts = source.with_suffix("").parts
    module_parts = parts[parts.index("office_mcp") :]
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    return ".".join(module_parts)


def _package_of(source: pathlib.Path) -> str:
    """The value `__package__` has inside `source`, i.e. what its relative imports resolve against.

    For a plain module `foo/bar/baz.py` that's `foo.bar` — the package containing it. For
    `foo/bar/__init__.py` it's `foo.bar` itself, since the module IS the package there.
    """
    module = _dotted_module(source)
    if source.name == "__init__.py":
        return module
    return module.rsplit(".", 1)[0]


def _source_id(source: pathlib.Path) -> str:
    """Test id for one module: `tools/get_me.py`, not an absolute path."""
    return str(source.relative_to(_SRC))


def _reaches(tree: ast.AST, prefix: str, package: str | None = None) -> list[tuple[str, int]]:
    """Every import in `tree` that reaches `prefix`, by module or through the package's front door.

    Two questions, because there are two ways in. The module a file imports is `prefix` itself or
    something under it (`import office_mcp.tools`, `from office_mcp.tools.get_me import …`), or the
    file imports the package *as a member* of the package above it (`from .. import tools`), which
    names `prefix` nowhere and hands over every module inside it just the same. The second is
    matched exactly and the first by prefix — see `_imported_members` for why.
    """
    return [
        (module, line)
        for module, line in _imported_modules(tree, package)
        if module == prefix or module.startswith(f"{prefix}.")
    ] + [(member, line) for member, line in _imported_members(tree, package) if member == prefix]


def _imports_under(source: str, prefix: str, package: str | None = None) -> list[str]:
    """The `prefix`-rooted modules `source` imports. Every import rule below is this."""
    return [module for module, _line in _reaches(ast.parse(source), prefix, package)]


def _violations(source: pathlib.Path, prefix: str) -> list[str]:
    tree = ast.parse(source.read_text(), filename=str(source))
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _reaches(tree, prefix, _package_of(source))
    ]


def _package_directory(package: str) -> pathlib.Path:
    """`office_mcp.graph_client` → the directory that package's modules live in."""
    return _SRC.joinpath(*package.split(".")[1:])


def _is_inside(directory: pathlib.Path, package: str) -> bool:
    return directory == _package_directory(package) or directory.is_relative_to(
        _package_directory(package)
    )


def _internal_imports(
    source: str, directory: pathlib.Path, package: str | None = None
) -> list[tuple[str, int]]:
    """Modules of a public-surface package that `source` reaches past the `__init__` for.

    A file inside a package may import its own package's modules freely — that is the package
    composing itself, and `tools/__init__.py` naming every tool module is the clearest case of
    it — so the directory the file lives in, not its name, decides.
    """
    return [
        (module, line)
        for surface in _PUBLIC_SURFACE_PACKAGES
        if not _is_inside(directory, surface)
        for module, line in _imported_modules(ast.parse(source), package)
        if module.startswith(f"{surface}.")
    ]


def _internal_module_violations(source: pathlib.Path) -> list[str]:
    reached = _internal_imports(source.read_text(), source.parent, _package_of(source))
    return [f"{source.relative_to(_SRC)}:{line} imports {module}" for module, line in reached]


def _declares_all(init: pathlib.Path) -> bool:
    """Whether `init` assigns an `__all__`, which is the front door it insists on being used."""
    return any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        for node in ast.walk(ast.parse(init.read_text()))
    )


def _own_package_violations(source: pathlib.Path) -> list[str]:
    """Every import `source` makes of this application, whatever part of it."""
    return _violations(source, _PACKAGE)


def _config_constructions(source: str) -> list[tuple[str, int]]:
    """Calls in `source` that construct a config class, with the line each is on.

    Only calls count. Importing a config type, annotating a parameter with one, or handing one
    to `isinstance` are all how an injected config is *used*, and none of them read the
    environment. `AppConfig.model_validate({...})` is likewise left alone: it validates the data
    it is given rather than gathering its own.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Name) and called.id in _CONFIG_CLASSES:
            found.append((called.id, node.lineno))
        # `config.EntraConfig()` — the same construction reached through its module.
        elif isinstance(called, ast.Attribute) and called.attr in _CONFIG_CLASSES:
            found.append((called.attr, node.lineno))
    return found


def _config_construction_violations(source: pathlib.Path) -> list[str]:
    relative = source.relative_to(_SRC)
    if relative.as_posix() in _COMPOSITION_ROOTS:
        return []
    return [
        f"{relative}:{line} constructs {name}()"
        for name, line in _config_constructions(source.read_text())
    ]


class TestTheDetectionItself:
    """The rules are only worth having if they fail on the things they're meant to catch."""

    def test_catches_the_violation_the_shared_rule_exists_for(self) -> None:
        assert _imports_under(
            "from office_mcp.tools.get_me import SignedInUser", _TOOLS_PREFIX
        ) == ["office_mcp.tools.get_me"]

    def test_catches_a_plain_import_too(self) -> None:
        assert _imports_under("import office_mcp.tools.get_me", _TOOLS_PREFIX) == [
            "office_mcp.tools.get_me"
        ]

    def test_catches_a_relative_import_that_escapes_the_layer(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`from ..tools.get_me import SignedInUser` inside `shared/identity.py` never spells
        `tools` at `level == 0`, so a level-blind check is silently invisible to exactly the
        violation rule 1 exists to catch. Proves the fix against the real checker (`_violations`,
        what the rules below run) over an actual file on disk.
        """
        src = tmp_path / "office_mcp"
        module = src / "shared" / "identity.py"
        module.parent.mkdir(parents=True)
        module.write_text("from ..tools.get_me import SignedInUser\n")
        monkeypatch.setattr(sys.modules[__name__], "_SRC", src)

        assert _violations(module, _TOOLS_PREFIX) == [
            "shared/identity.py:1 imports office_mcp.tools.get_me"
        ]

    def test_catches_a_reach_into_the_tool_package_through_its_front_door(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The escape a check on module names alone never sees. `from .. import tools` — spelled
        absolutely, or under an alias — names `office_mcp` and nothing else, while binding the whole
        tool package: the registry imports every tool module, so each one is an attribute of the
        object that import produced. The alias is the binding and `alias.name` is the import, which
        is why the check is on the member.
        """
        src = tmp_path / "office_mcp"
        module = src / "shared" / "identity.py"
        module.parent.mkdir(parents=True)
        module.write_text("from .. import tools as _tools\nPROFILE = _tools.get_me.SignedInUser\n")
        monkeypatch.setattr(sys.modules[__name__], "_SRC", src)

        assert _violations(module, _TOOLS_PREFIX) == [
            "shared/identity.py:1 imports office_mcp.tools"
        ]

    def test_does_not_fire_on_a_member_that_is_not_the_package(self) -> None:
        """The negative control for the member check, and the reason it matches exactly rather than
        by prefix: `from office_mcp.shared import identity` names a module of a package no rule
        forbids, and `from office_mcp.graph_client import graph_client_for` names a function. A
        prefix match on members would make rule 8 fire on both."""
        assert not _imports_under(
            "from office_mcp.shared import identity, seam\n"
            + "from office_mcp.graph_client import graph_client_for\n",
            _TOOLS_PREFIX,
        )
        assert not _internal_imports("from office_mcp.graph_client import graph_client_for\n", _SRC)

    def test_catches_the_violation_the_mcp_framework_rule_exists_for(self) -> None:
        assert _imports_under(
            "from fastmcp.exceptions import ToolError\nimport fastmcp\n", _MCP_FRAMEWORK
        ) == ["fastmcp.exceptions", "fastmcp"]

    def test_the_mcp_framework_rule_leaves_the_protocol_types_alone(self) -> None:
        """`mcp` is the protocol SDK, a different distribution from the server framework, and a
        name that merely begins with `fastmcp` is not it either."""
        assert not _imports_under(
            "from mcp.types import TextContent\nfrom fastmcpx import thing", _MCP_FRAMEWORK
        )

    def test_catches_the_violation_the_transport_rule_exists_for(self) -> None:
        """Anything of this application at all, not only the three named packages: the transport
        takes settings and a token and knows nothing else."""
        assert _imports_under(
            "from office_mcp.shared.identity import PROFILE\n"
            + "from office_mcp.config import AppConfig\n"
            + "from office_mcp.server import ready_response\n",
            _PACKAGE,
        ) == ["office_mcp.shared.identity", "office_mcp.config", "office_mcp.server"]

    def test_the_transport_rule_leaves_the_sdk_and_its_own_modules_alone(self) -> None:
        """`graph_client` composing itself is the package doing its job, and `msgraph` is what it
        is *for*."""
        assert not [
            module
            for module in _imports_under(
                "from office_mcp.graph_client.settings import GraphSettings\n"
                + "from msgraph.graph_service_client import GraphServiceClient\n",
                _PACKAGE,
            )
            if not module.startswith(_GRAPH_CLIENT_PREFIX)
        ]

    def test_catches_a_tool_reaching_into_the_layer_that_exposes_it(self) -> None:
        assert _imports_under(
            "from office_mcp.server import ready_response\n"
            + "from office_mcp.server.readiness import ready_response\n",
            _SERVER_PREFIX,
        ) == ["office_mcp.server", "office_mcp.server.readiness"]

    def test_does_not_fire_on_permitted_imports(self) -> None:
        """The negative control, and the one that keeps every rule above from being a rule
        against importing anything: each is one call to `_imports_under`, so a helper that
        matched loosely would turn "a tool imports only shared/, graph_client/ and FastMCP" into
        "a tool imports nothing" and every rule would pass by forbidding the whole language.
        These three are exactly what rule 3 permits a tool file, plus a cross-cutting module.
        """
        assert not _imports_under(
            "from office_mcp.shared.identity import PROFILE\n"
            + "from office_mcp.graph_client import graph_client_for\n"
            + "from office_mcp.logging import configure_logging\n"
            + "from fastmcp import FastMCP\n",
            _TOOLS_PREFIX,
        )

    def test_catches_the_violation_the_internals_rule_exists_for(self) -> None:
        # `server` stands in for any listed package here; the rule is about the front door, not
        # about which package happens to be behind it. The importing directory is `_SRC` — i.e.
        # `app.py`, the composition root, which is the likeliest place to reach past one.
        reached = _internal_imports("from office_mcp.server.readiness import ready_response", _SRC)

        assert reached == [("office_mcp.server.readiness", 1)]

    def test_catches_reaching_past_the_registry_for_a_tool_file(self) -> None:
        """The case rule 8 gained with `tools/`: importing a tool module directly is how the
        registry stops being the one place every tool is named, and both what a selection is
        filtered over and what sign-in asks for are derived from exactly that list."""
        assert _internal_imports("from office_mcp.tools.get_me import register", _SRC) == [
            ("office_mcp.tools.get_me", 1)
        ]

    def test_the_same_import_is_fine_inside_the_package(self) -> None:
        assert not _internal_imports(
            "from office_mcp.tools import get_me",
            _package_directory("office_mcp.tools"),
        )

    def test_does_not_fire_on_the_package_root(self) -> None:
        assert not _internal_imports(
            "from office_mcp.tools import register_tools, resolve\n"
            + "from office_mcp.server import ready_response, surface_manifest\n"
            + "from office_mcp.graph_client import create_graph_transport\n"
            + "from office_mcp.shared.identity import PROFILE\n",
            _SRC,
        )

    def test_catches_the_violation_the_config_construction_rule_exists_for(self) -> None:
        assert _config_constructions(
            "def graph_settings() -> None:\n    entra = EntraConfig()\n"
        ) == [("EntraConfig", 2)]

    def test_catches_a_config_built_through_its_module_too(self) -> None:
        assert _config_constructions("cfg = config.AppConfig()") == [("AppConfig", 1)]

    def test_does_not_fire_on_using_an_injected_config(self) -> None:
        assert not _config_constructions(
            "from office_mcp.config import EntraConfig\n"
            + "def build_auth(entra: EntraConfig) -> str:\n"
            + "    return entra.client_id\n"
        )

    def test_does_not_fire_on_validating_supplied_data(self) -> None:
        """`model_validate` is handed its values; it does not go looking for them."""
        assert not _config_constructions("AppConfig.model_validate({'port': 1})")

    def test_does_not_fire_on_a_name_that_merely_starts_with_the_prefix(self) -> None:
        assert not _imports_under("from office_mcp.toolsmith import thing", _TOOLS_PREFIX)
        assert not _imports_under("from office_mcp.sharedish import thing", _SHARED_PREFIX)
        assert not _imports_under("from office_mcp.configuration import thing", _CONFIG_MODULE)


class TestSharedIsUpstreamOfEveryTool:
    def test_the_shared_tree_is_actually_there(self) -> None:
        """Guards the guard: the rule is parametrized over `shared/`, so an empty tree makes it
        zero tests that pass by not existing."""
        modules = [source for source in _sources(_SHARED) if source.name != "__init__.py"]
        assert modules, f"no shared modules found under {_SHARED}"

    @pytest.mark.parametrize("source", _sources(_SHARED), ids=_source_id)
    def test_no_shared_module_imports_a_tool(self, source: pathlib.Path) -> None:
        violations = _violations(source, _TOOLS_PREFIX)
        assert not violations, (
            "shared/ must not import tools/ — it is what tools must not disagree about, and a "
            + "tool is what disagrees. Whatever the tool has that shared/ needs is either the "
            + "tool's own (leave it there and pass the value in) or shared vocabulary (move it "
            + "here):\n  "
            + "\n  ".join(violations)
        )


class TestOnlyTheSeamSpeaksMcp:
    def test_the_seam_actually_speaks_it(self) -> None:
        """Guards the guard from both sides: if `seam.py` stopped importing FastMCP the exemption
        would be a dead letter, and if the file were renamed the rule would forbid the framework
        everywhere under `shared/` — including from the one file whose job it is."""
        assert _SEAM.is_file(), f"no such file: {_SEAM}"
        assert _imports_under(_SEAM.read_text(), _MCP_FRAMEWORK, _package_of(_SEAM)), (
            f"{_SEAM.name} no longer imports FastMCP, so it is no longer the seam"
        )

    @pytest.mark.parametrize("source", [s for s in _sources(_SHARED) if s != _SEAM], ids=_source_id)
    def test_no_other_shared_module_imports_the_mcp_framework(self, source: pathlib.Path) -> None:
        violations = _violations(source, _MCP_FRAMEWORK)
        assert not violations, (
            "only shared/seam.py may import FastMCP — the rest of the shared vocabulary answers "
            + "with its own types and raises Graph failures, and turning either into something an "
            + "MCP client sees is the seam's job or the tool's. Return the fact (or raise) and let "
            + "the tool decide what to say:\n  "
            + "\n  ".join(violations)
        )


class TestTheTransportImportsNothingOfThisApplication:
    def test_the_client_tree_and_its_own_settings_are_actually_there(self) -> None:
        """Guards the guard: without somewhere to put settings, the config half is unsatisfiable,
        and without modules there is nothing to walk."""
        sources = _sources(_GRAPH_CLIENT)
        assert sources, f"no python sources found under {_GRAPH_CLIENT}"
        assert {"client.py", "settings.py"} <= {source.name for source in sources}

    @pytest.mark.parametrize("source", _sources(_GRAPH_CLIENT), ids=_source_id)
    def test_no_client_module_imports_anything_of_ours(self, source: pathlib.Path) -> None:
        violations = [
            violation
            for violation in _own_package_violations(source)
            if _GRAPH_CLIENT_PREFIX not in violation
        ]
        assert not violations, (
            "graph_client/ must import nothing of this application — it is infrastructure its "
            + "callers consume, and it takes its own frozen settings from graph_client/settings.py "
            + "rather than reading config. Add the field to those settings and map it in "
            + "create_app, or put the shared type here (a Protocol, if the caller owns the "
            + "implementation):\n  "
            + "\n  ".join(violations)
        )


class TestAToolLeansOnlyOnSharedAndTheTransport:
    def test_a_tool_actually_imports_all_three(self) -> None:
        """Guards the guard: rule 3 is permissive, so what makes it a rule rather than a sentence
        is that the three permitted dependencies are genuinely used — if `tools/` stopped reaching
        for `shared/`, the vocabulary would have been copied into the tool files instead."""
        sources = _tool_modules()
        assert sources, f"no tool modules found under {_TOOLS}"
        for prefix in (_SHARED_PREFIX, _GRAPH_CLIENT_PREFIX, _MCP_FRAMEWORK):
            used = [
                module
                for source in sources
                for module in _imports_under(source.read_text(), prefix, _package_of(source))
            ]
            assert used, f"no tool module imports {prefix}"

    @pytest.mark.parametrize("source", _sources(_TOOLS), ids=_source_id)
    def test_no_tool_module_imports_the_layer_that_exposes_it(self, source: pathlib.Path) -> None:
        violations = _violations(source, _SERVER_PREFIX)
        assert not violations, (
            "a tool file must not import server/ — that is the shape it exists instead of, and a "
            + "tool that reaches into it has its wiring somewhere other than in itself. Bring it "
            + "into this file, and put anything a second tool needs into shared/:\n  "
            + "\n  ".join(violations)
        )


class TestPackagesAreEnteredThroughTheirInit:
    """Rule 8."""

    @pytest.mark.parametrize("package", _PUBLIC_SURFACE_PACKAGES)
    def test_every_listed_package_actually_publishes_something(self, package: str) -> None:
        """Guards the guard: a package with no `__all__` has no front door to insist on."""
        init = _package_directory(package) / "__init__.py"
        assert init.is_file(), f"no __init__.py for {package}"
        assert _declares_all(init), f"{package}/__init__.py declares no __all__"

    @pytest.mark.parametrize("source", _sources(_SRC), ids=_source_id)
    def test_no_module_reaches_past_another_packages_init(self, source: pathlib.Path) -> None:
        violations = _internal_module_violations(source)
        assert not violations, (
            "import the package, not a module inside it — a package's __all__ is the whole of "
            + "what it promises, and reaching past it means assembling collaborators the package "
            + "is responsible for assembling (which is how a tool came to re-read its own config "
            + "and ignore what create_app was given). Export the name from that package's "
            + "__init__ and import it from there:\n  "
            + "\n  ".join(violations)
        )


class TestConfigIsBuiltOnlyAtTheCompositionRoot:
    def test_every_exempt_file_actually_exists(self) -> None:
        """Guards the guard: a renamed entrypoint would silently widen the exemption."""
        for relative in sorted(_COMPOSITION_ROOTS):
            assert (_SRC / relative).is_file(), f"no such file: {relative}"

    def test_the_composition_root_really_does_build_every_config(self) -> None:
        """And guards it from the other side: if `app.py` stopped constructing the config
        classes, they would be built somewhere else and this rule would be vacuous."""
        built = {name for name, _line in _config_constructions((_SRC / "app.py").read_text())}

        assert built >= _CONFIG_CLASSES, f"app.py does not build {_CONFIG_CLASSES - built}"

    @pytest.mark.parametrize("source", _sources(_SRC), ids=_source_id)
    def test_no_module_outside_the_root_builds_its_own_config(self, source: pathlib.Path) -> None:
        violations = _config_construction_violations(source)
        assert not violations, (
            "only create_app() may construct a config — building one here re-reads the "
            + "environment and quietly ignores whatever create_app was given. Take the value "
            + "as a parameter and let the composition root pass it in:\n  "
            + "\n  ".join(violations)
        )
