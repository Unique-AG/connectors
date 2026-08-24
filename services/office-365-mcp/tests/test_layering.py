"""The structural rules this package's layout depends on.

**A tool is a file, and these are the rules that keep it one.** `tools/get_me.py` owns its name,
the prose that teaches a model when to reach for it, its Graph permissions, its arguments, its
answer shape, its request and its refusals. `shared/` is what a second tool will not be free to
disagree with it about. `graph_client/` is the transport they borrow.

1. **`shared/` imports no tool module, and only `shared/seam.py` imports FastMCP.** `shared/` is
   what two tools must not disagree about and a tool is what disagrees, so the direction is one-way.
   FastMCP is not banned outright because the On-Behalf-Of token dependency and the `ToolError` a
   Graph refusal becomes are types every tool must say identically; allowing them in one named file
   keeps the framework out of the handle grammar, the message shape and the rest of the vocabulary.

2. **`graph_client/` imports nothing of this application.** It takes its own frozen `GraphSettings`
   rather than reading config, because a transport is allowed to be *told* and not to be configured;
   anything it imported back would be a package cycle and a second place the environment is read.

3. **`tools/` imports `shared/`, `graph_client/` and FastMCP, and nothing else of this package.**
   Not `server/`: a tool that reached into it would have its wiring somewhere other than in itself,
   which is the shape this layout exists to avoid.

4. **No tool module imports another tool module.** Two tool files sharing a description constant, an
   error text or a helper would re-create the tool-declaration module they exist instead of, one
   import at a time; what two tools genuinely need is shared vocabulary and belongs in `shared/`,
   where the dependency is visible. `tools/__init__.py` is the only exemption: it is the registry,
   and the union of their permissions could not be derived otherwise.

   **The package's own front door is not a way round it.** `from .. import tools` and `from
   office_365_mcp import tools`, under an alias or not, spell no sibling's name — the module they
   name is `office_365_mcp` — yet the registry has already bound every tool module as an attribute
   of it, so the *member* is matched as well.
   `importlib.import_module("office_365_mcp.tools.get_me")` is deliberately not chased: like rule 6,
   this is a tripwire rather than a barrier.

5. **A config class is only instantiated at the composition root.** Anything downstream constructing
   its own re-reads the environment and silently ignores what `create_app` injected, which is how a
   tool ends up configured differently from the app it runs in. Only *calling* a config type is the
   violation, and `main.py` is exempt as the entrypoint that hands `create_app` its `AppConfig`.

6. **One speller per handle family: `shared/handles.py` alone spells or parses a `teams:///` URI.**
   Two modules that each knew how to write `teams:///chats/…` would be free to disagree, and the
   disagreement would look like a handle one tool produced and another answers 404 to. A literal
   carrying the scheme is an implementation when something is *done* to it and prose when it merely
   sits there — the failure message of `test_no_other_module_builds_or_parses_a_handle` is that
   definition — and the check is text-level, so a module that writes the scheme in pieces is
   deliberately not chased.

7. **No module may address a single meeting recording.** Both ways to reach an individual
   `callRecording` are defects: its `content` is an MP4 of a meeting that can run thirty hours and
   that a model cannot watch, and its `recordingContentUrl` is a Graph URL only this connector's
   bearer token opens, so handing it to a caller is either useless or a token leak. "Return
   metadata and availability, never the bytes" is the whole shape of
   `tools/list_meeting_recordings.py`, and it is a failing test rather than a paragraph because the
   change that breaks it is a small-looking convenience someone adds later.

8. **A package is entered through its `__init__`, never through its modules.** Applies to the
   packages in `_PUBLIC_SURFACE_PACKAGES`, each of which publishes an `__all__`: reaching past one
   means assembling collaborators the package is responsible for assembling, which is how a tool
   came to re-read its own config, and on `tools/` it stops the registry being the one place every
   tool module is named — the list a selection is filtered over and every Graph scope sign-in asks
   for is derived from. `shared/` is deliberately not listed because it publishes no surface: its
   *modules* are the units and every consumer names which of them it depends on at the import line,
   so an `__init__` re-exporting the lot would hide the one thing the package exists to show. A
   package joins the list as soon as its `__init__` exports anything.

Every rule is paired with a guard that fails once the rule has nothing left to check, because a rule
written down while it forbids nothing gets deleted for the wrong reason later, or worse, kept while
the thing it covers quietly leaves. None of the rules is conditional: a rule that stops running is a
failure and not a skip. All are asserted by walking the AST rather than importing anything, so a
violation is a failing test with a file and line instead of an ImportError at collection time.
"""

import ast
import pathlib
import re
import sys

import pytest

_SRC = pathlib.Path(__file__).parent.parent / "src" / "office_365_mcp"

_SHARED = _SRC / "shared"
_TOOLS = _SRC / "tools"
_GRAPH_CLIENT = _SRC / "graph_client"

_PACKAGE = "office_365_mcp"
_SHARED_PREFIX = "office_365_mcp.shared"
_TOOLS_PREFIX = "office_365_mcp.tools"
_SERVER_PREFIX = "office_365_mcp.server"
_CONFIG_MODULE = "office_365_mcp.config"
_GRAPH_CLIENT_PREFIX = "office_365_mcp.graph_client"
_MCP_FRAMEWORK = "fastmcp"

# Rule 8. The rule walks `src` only, so tests stay free to reach the pieces a package composes.
_PUBLIC_SURFACE_PACKAGES: tuple[str, ...] = (
    "office_365_mcp.graph_client",
    "office_365_mcp.server",
    "office_365_mcp.tools",
)

_SEAM = _SHARED / "seam.py"

_HANDLE_SCHEME = "teams:///"
_HANDLE_OWNER = _SHARED / "handles.py"
_HANDLE_FAMILIES = frozenset({"chats", "teams", "meetings", "transcripts"})
_HANDLE_FAMILY = re.compile(re.escape(_HANDLE_SCHEME) + r"([A-Za-z_]*)")

# Regex syntax never appears in prose a model reads, so it tells a matcher from a mention.
_PATTERN_SYNTAX: tuple[str, ...] = (r"\A", r"\Z", "[^", "(?")

# A parser is a second *reader* of the grammar, written with string methods rather than a regex, so
# the pattern-syntax check never sees it.
_BUILDING_METHODS = frozenset({"format", "join"})
_PARSING_METHODS = frozenset(
    {
        "startswith",
        "endswith",
        "removeprefix",
        "removesuffix",
        "split",
        "rsplit",
        "partition",
        "rpartition",
    }
)

# A handle handed to `re.compile`/`re.match`/`re.sub`/… is matched, whether or not the pattern
# carries any of `_PATTERN_SYNTAX`.
_REGEX_MODULE = "re"

# Adjacency decides: a run that reaches the handover — an f-string interpolation or a concatenated
# expression — without whitespace is a handle being assembled (`f"teams:///meetings/{x}"`,
# `"teams:///chats/" + chat_id`); one that wanders back into a sentence first is a paragraph.
_WHITESPACE = re.compile(r"\s")

_RECORDING_ITEM_NAMES = frozenset({"by_call_recording_id", "recording_content_url"})

# Rule 7's guard finds the listing by what it does — `…by_online_meeting_id(id).recordings` — rather
# than by path, which would fail the day the listing moved.
_RECORDINGS_COLLECTION = frozenset({"online_meetings", "recordings"})

# The `BaseSettings` classes in config.py, which read the environment when constructed.
_CONFIG_CLASSES = frozenset({"AppConfig", "DatabaseConfig", "EntraConfig", "SurfaceConfig"})

_COMPOSITION_ROOTS = frozenset({"app.py", "main.py"})


def _sources(directory: pathlib.Path) -> list[pathlib.Path]:
    return sorted(directory.rglob("*.py"))


def _tool_modules() -> list[pathlib.Path]:
    return [source for source in _sources(_TOOLS) if source.name != "__init__.py"]


def _imported_modules(tree: ast.AST, package: str | None = None) -> list[tuple[str, int]]:
    """Every module name this file imports, with the line it's imported on.

    Unresolved, `from ..server.readiness import ready_response` inside `tools/get_me.py` never
    spells `server` at `level == 0` and is invisible to every rule below. The snippets in
    `TestTheDetectionItself` arrive without a `package`, so their relative imports are skipped.
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

    Rule 4's front door: `from .. import tools as _tools` imports the module `office_365_mcp` and
    binds the whole tool package, so no rule above sees a tool module. Any alias is caught, because
    the alias is the *binding* and `alias.name` is what was imported. Callers must match a member
    **exactly**, never by prefix: `from office_365_mcp.shared import identity` names a module of a
    package nothing forbids, and `graph_client_for` names a function rather than a module.
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
    """`None` if the import walks above the top of the tree, which `ast` parses happily and Python
    raises `ImportError` for at runtime."""
    parts = package.split(".")
    remaining = len(parts) - (level - 1)
    if remaining < 0:
        return None
    base = parts[:remaining]
    if module:
        base = base + module.split(".")
    return ".".join(base) if base else None


def _dotted_module(source: pathlib.Path) -> str:
    """Anchored on the `office_365_mcp` directory in `source`'s own path rather than on `_SRC`, so
    the throwaway copy of the tree `TestTheDetectionItself` builds resolves the way
    `src/office_365_mcp` does."""
    parts = source.with_suffix("").parts
    module_parts = parts[parts.index("office_365_mcp") :]
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    return ".".join(module_parts)


def _package_of(source: pathlib.Path) -> str:
    """The value `__package__` has inside `source`: what its relative imports resolve against."""
    module = _dotted_module(source)
    if source.name == "__init__.py":
        return module
    return module.rsplit(".", 1)[0]


def _source_id(source: pathlib.Path) -> str:
    return str(source.relative_to(_SRC))


def _reaches(tree: ast.AST, prefix: str, package: str | None = None) -> list[tuple[str, int]]:
    """Two ways in: a module at or under `prefix`, matched by prefix, and the package imported *as
    a member* of the package above it — rule 4's front door, which names `prefix` nowhere — matched
    exactly. See `_imported_members` for why exactly."""
    return [
        (module, line)
        for module, line in _imported_modules(tree, package)
        if module == prefix or module.startswith(f"{prefix}.")
    ] + [(member, line) for member, line in _imported_members(tree, package) if member == prefix]


def _imports_under(source: str, prefix: str, package: str | None = None) -> list[str]:
    return [module for module, _line in _reaches(ast.parse(source), prefix, package)]


def _violations(source: pathlib.Path, prefix: str) -> list[str]:
    tree = ast.parse(source.read_text(), filename=str(source))
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _reaches(tree, prefix, _package_of(source))
    ]


def _package_directory(package: str) -> pathlib.Path:
    return _SRC.joinpath(*package.split(".")[1:])


def _is_inside(directory: pathlib.Path, package: str) -> bool:
    return directory == _package_directory(package) or directory.is_relative_to(
        _package_directory(package)
    )


def _internal_imports(
    source: str, directory: pathlib.Path, package: str | None = None
) -> list[tuple[str, int]]:
    """A file inside a package may import its own package's modules freely — that is the package
    composing itself, `tools/__init__.py` naming every tool module being the clearest case — so the
    directory the file lives in, not its name, decides."""
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
    return any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        for node in ast.walk(ast.parse(init.read_text()))
    )


def _own_package_violations(source: pathlib.Path) -> list[str]:
    return _violations(source, _PACKAGE)


def _config_constructions(source: str) -> list[tuple[str, int]]:
    """`AppConfig.model_validate({...})` is not a construction: it validates the data it is handed
    rather than gathering its own."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Name) and called.id in _CONFIG_CLASSES:
            found.append((called.id, node.lineno))
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


def _handle_spellings(source: str) -> list[str]:
    """Rule 6 in code. Literal runs inside an f-string are left to the building check; judging them
    separately would report the owner's own lines twice."""
    tree = ast.parse(source)
    parents = _parents(tree)
    bound = _scheme_bindings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            found.extend(f"line {node.lineno} builds a handle" for _ in _built_handles(node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _HANDLE_SCHEME not in node.value or isinstance(parents.get(id(node)), ast.JoinedStr):
                continue
            if any(syntax in node.value for syntax in _PATTERN_SYNTAX):
                found.append(f"line {node.lineno} matches a handle")
                continue
            use = _use_made_of(node, parents, adjacency=node.value)
            if use is not None:
                found.append(f"line {node.lineno} {use} a handle")
        elif isinstance(node, ast.Name) and node.id in bound and isinstance(node.ctx, ast.Load):
            use = _use_made_of(node, parents, adjacency=None)
            if use is not None:
                found.append(
                    f"line {node.lineno} {use} a handle through {node.id} "
                    + f"(bound on line {bound[node.id]})"
                )
    return found


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    """What a literal is used for is a question about its parent."""
    return {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _scheme_bindings(tree: ast.AST) -> dict[str, int]:
    """The binding is never the violation: `_SCHEME = "teams:///"` is a grammar's root and
    `_HINT = "teams:///..."` is a refusal, and the two are the same statement. Remembering the name
    is what lets the *use* of either be judged like the literal itself."""
    bound: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if _HANDLE_SCHEME not in value.value:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bound.setdefault(target.id, node.lineno)
    return bound


def _use_made_of(
    node: ast.expr, parents: dict[int, ast.AST], *, adjacency: str | None
) -> str | None:
    """`adjacency` is the literal's own text, or None for a name. A name has no run to judge, so `+`
    on one is left alone, which is how a refusal's hint constant goes on being concatenated with
    more prose."""
    parent = parents.get(id(node))
    if isinstance(parent, ast.FormattedValue):
        return "builds"
    if isinstance(parent, ast.BinOp):
        if isinstance(parent.op, ast.Mod):
            return "spells"
        if isinstance(parent.op, ast.Add) and adjacency is not None:
            other = parent.right if parent.left is node else parent.left
            hands_over = not _is_literal_text(other)
            reaches_it = not _WHITESPACE.search(adjacency.rsplit(_HANDLE_SCHEME, 1)[1])
            return "spells" if hands_over and reaches_it else None
        return None
    if isinstance(parent, ast.Attribute):
        return "spells" if parent.attr in _BUILDING_METHODS else None
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute):
        called = parent.func
        if called.attr in _PARSING_METHODS or called.attr in _BUILDING_METHODS:
            return "spells"
        if isinstance(called.value, ast.Name) and called.value.id == _REGEX_MODULE:
            return "matches"
        return None
    if isinstance(parent, ast.List | ast.Tuple | ast.Set):
        # `"/".join(("teams:///chats", chat_id))` — a segment handed to a joiner.
        joined = parents.get(id(parent))
        return (
            "spells"
            if isinstance(joined, ast.Call)
            and isinstance(joined.func, ast.Attribute)
            and joined.func.attr in _BUILDING_METHODS
            else None
        )
    return None


def _is_literal_text(node: ast.expr) -> bool:
    """A long description in this codebase is a chain of `+`-ed string literals, so the whole chain
    has to read as one literal. Otherwise every paragraph that shows a handle on its own line would
    look like a concatenation building one."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_literal_text(node.left) and _is_literal_text(node.right)
    return False


def _built_handles(node: ast.JoinedStr) -> list[ast.Constant]:
    parts = node.values
    return [
        part
        for index, part in enumerate(parts)
        if isinstance(part, ast.Constant)
        and isinstance(part.value, str)
        and _HANDLE_SCHEME in part.value
        and index + 1 < len(parts)
        and isinstance(parts[index + 1], ast.FormattedValue)
        and not _WHITESPACE.search(part.value.rsplit(_HANDLE_SCHEME, 1)[1])
    ]


def _handle_violations(source: pathlib.Path) -> list[str]:
    return [
        f"{source.relative_to(_SRC)} {spelling}"
        for spelling in _handle_spellings(source.read_text())
    ]


def _registry_imports() -> set[str]:
    """Both spellings, because either is how a module gets into `_TOOL_MODULES`: the names of
    `from office_365_mcp.tools import get_me, list_chats`, and the tail of
    `import office_365_mcp.tools.get_me`."""
    tree = ast.parse((_TOOLS / "__init__.py").read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module == _TOOLS_PREFIX or node.level == 1):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(
                alias.name.rsplit(".", 1)[-1]
                for alias in node.names
                if alias.name.startswith(f"{_TOOLS_PREFIX}.")
            )
    return found


def _attribute_names(source: str) -> set[str]:
    """Attribute names rather than text so that rule 7 constrains code and leaves prose alone: the
    module it guards has to be able to name the Graph `recordingContentUrl` property it deliberately
    does not return."""
    return {node.attr for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Attribute)}


def _recording_listings() -> list[pathlib.Path]:
    return [
        source
        for source in _sources(_SRC)
        if _attribute_names(source.read_text()) >= _RECORDINGS_COLLECTION
    ]


def _recording_item_violations(source: pathlib.Path) -> list[str]:
    reached = sorted(_attribute_names(source.read_text()) & _RECORDING_ITEM_NAMES)
    return [f"{source.relative_to(_SRC)} reaches {name}" for name in reached]


def _a_tool_file_containing(
    source: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> pathlib.Path:
    """On disk rather than as a string because a relative import resolves only against a real
    package: `from .. import tools` is `office_365_mcp` seen from `office_365_mcp.tools.list_chats`,
    and nothing but the file's own path says which. `_SRC` is repointed at the copy, so the
    violation comes back named the way the real rules name one."""
    module = tmp_path / "office_365_mcp" / "tools" / "list_chats.py"
    module.parent.mkdir(parents=True)
    module.write_text(source)
    monkeypatch.setattr(sys.modules[__name__], "_SRC", tmp_path / "office_365_mcp")
    return module


class TestTheDetectionItself:
    def test_catches_the_violation_the_shared_rule_exists_for(self) -> None:
        assert _imports_under(
            "from office_365_mcp.tools.get_me import SignedInUser", _TOOLS_PREFIX
        ) == ["office_365_mcp.tools.get_me"]

    def test_catches_a_plain_import_too(self) -> None:
        assert _imports_under("import office_365_mcp.tools.get_me", _TOOLS_PREFIX) == [
            "office_365_mcp.tools.get_me"
        ]

    def test_catches_a_relative_import_that_escapes_the_layer(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src = tmp_path / "office_365_mcp"
        module = src / "shared" / "identity.py"
        module.parent.mkdir(parents=True)
        module.write_text("from ..tools.get_me import SignedInUser\n")
        monkeypatch.setattr(sys.modules[__name__], "_SRC", src)

        assert _violations(module, _TOOLS_PREFIX) == [
            "shared/identity.py:1 imports office_365_mcp.tools.get_me"
        ]

    def test_catches_a_tool_reaching_its_siblings_through_the_front_door(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _a_tool_file_containing("from .. import tools\n", tmp_path, monkeypatch)

        assert _violations(module, _TOOLS_PREFIX) == [
            "tools/list_chats.py:1 imports office_365_mcp.tools"
        ]

    def test_catches_the_same_reach_spelled_absolutely(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _a_tool_file_containing(
            "from office_365_mcp import tools\n", tmp_path, monkeypatch
        )

        assert _violations(module, _TOOLS_PREFIX) == [
            "tools/list_chats.py:1 imports office_365_mcp.tools"
        ]

    def test_catches_it_under_an_alias(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _a_tool_file_containing(
            "from .. import tools as _siblings\n"
            + "PERMISSIONS = _siblings.get_me.GRAPH_PERMISSIONS\n",
            tmp_path,
            monkeypatch,
        )

        assert _violations(module, _TOOLS_PREFIX) == [
            "tools/list_chats.py:1 imports office_365_mcp.tools"
        ]

    def test_catches_it_inside_a_function_body(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _a_tool_file_containing(
            "def register(mcp: object, transport: object) -> tuple[str, ...]:\n"
            + "    from office_365_mcp import tools\n"
            + "    return tools.get_me.GRAPH_PERMISSIONS\n",
            tmp_path,
            monkeypatch,
        )

        assert _violations(module, _TOOLS_PREFIX) == [
            "tools/list_chats.py:2 imports office_365_mcp.tools"
        ]

    def test_does_not_fire_on_a_member_that_is_not_the_package(self) -> None:
        assert not _imports_under(
            "from office_365_mcp.shared import identity, seam\n"
            + "from office_365_mcp.graph_client import graph_client_for\n",
            _TOOLS_PREFIX,
        )
        assert not _internal_imports(
            "from office_365_mcp.graph_client import graph_client_for\n", _SRC
        )

    def test_catches_the_violation_the_mcp_framework_rule_exists_for(self) -> None:
        assert _imports_under(
            "from fastmcp.exceptions import ToolError\nimport fastmcp\n", _MCP_FRAMEWORK
        ) == ["fastmcp.exceptions", "fastmcp"]

    def test_the_mcp_framework_rule_leaves_the_protocol_types_alone(self) -> None:
        """`mcp` is the protocol SDK, a different distribution from the server framework."""
        assert not _imports_under(
            "from mcp.types import TextContent\nfrom fastmcpx import thing", _MCP_FRAMEWORK
        )

    def test_catches_the_violation_the_transport_rule_exists_for(self) -> None:
        assert _imports_under(
            "from office_365_mcp.shared.identity import PROFILE\n"
            + "from office_365_mcp.config import AppConfig\n"
            + "from office_365_mcp.server import ready_response\n",
            _PACKAGE,
        ) == ["office_365_mcp.shared.identity", "office_365_mcp.config", "office_365_mcp.server"]

    def test_the_transport_rule_leaves_the_sdk_and_its_own_modules_alone(self) -> None:
        assert not [
            module
            for module in _imports_under(
                "from office_365_mcp.graph_client.settings import GraphSettings\n"
                + "from msgraph.graph_service_client import GraphServiceClient\n",
                _PACKAGE,
            )
            if not module.startswith(_GRAPH_CLIENT_PREFIX)
        ]

    def test_catches_a_tool_reaching_into_the_layer_that_exposes_it(self) -> None:
        assert _imports_under(
            "from office_365_mcp.server import ready_response\n"
            + "from office_365_mcp.server.readiness import ready_response\n",
            _SERVER_PREFIX,
        ) == ["office_365_mcp.server", "office_365_mcp.server.readiness"]

    def test_does_not_fire_on_permitted_imports(self) -> None:
        """A `_imports_under` that matched loosely would make every rule above pass by forbidding
        the whole language."""
        assert not _imports_under(
            "from office_365_mcp.shared.identity import PROFILE\n"
            + "from office_365_mcp.graph_client import graph_client_for\n"
            + "from office_365_mcp.logging import configure_logging\n"
            + "from fastmcp import FastMCP\n",
            _TOOLS_PREFIX,
        )

    def test_catches_the_violation_the_internals_rule_exists_for(self) -> None:
        reached = _internal_imports(
            "from office_365_mcp.server.readiness import ready_response", _SRC
        )

        assert reached == [("office_365_mcp.server.readiness", 1)]

    def test_catches_reaching_past_the_registry_for_a_tool_file(self) -> None:
        assert _internal_imports("from office_365_mcp.tools.get_me import register", _SRC) == [
            ("office_365_mcp.tools.get_me", 1)
        ]

    def test_the_same_import_is_fine_inside_the_package(self) -> None:
        assert not _internal_imports(
            "from office_365_mcp.tools import get_me",
            _package_directory("office_365_mcp.tools"),
        )

    def test_does_not_fire_on_the_package_root(self) -> None:
        assert not _internal_imports(
            "from office_365_mcp.tools import register_tools, resolve\n"
            + "from office_365_mcp.server import ready_response, surface_manifest\n"
            + "from office_365_mcp.graph_client import create_graph_transport\n"
            + "from office_365_mcp.shared.identity import PROFILE\n",
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
            "from office_365_mcp.config import EntraConfig\n"
            + "def build_auth(entra: EntraConfig) -> str:\n"
            + "    return entra.client_id\n"
        )

    def test_does_not_fire_on_validating_supplied_data(self) -> None:
        assert not _config_constructions("AppConfig.model_validate({'port': 1})")

    def test_catches_a_handle_being_built(self) -> None:
        assert _handle_spellings(
            "def uri(chat_id: str, message_id: str) -> str:\n"
            + '    return f"teams:///chats/{chat_id}/messages/{message_id}"\n'
        ) == ["line 2 builds a handle"]

    def test_catches_a_handle_being_matched(self) -> None:
        assert _handle_spellings(
            '_CHAT = re.compile(r"\\Ateams:///chats/([^/]+)/messages/([^/]+)\\Z")\n'
        ) == ["line 1 matches a handle"]

    def test_catches_a_handle_assembled_by_concatenation(self) -> None:
        assert _handle_spellings(
            "def uri(chat_id: str, message_id: str) -> str:\n"
            + '    return "teams:///chats/" + chat_id + "/messages/" + message_id\n'
        ) == ["line 2 spells a handle"]

    def test_catches_a_handle_assembled_with_format(self) -> None:
        assert _handle_spellings(
            '_TEMPLATE = "teams:///chats/{chat_id}/messages/{message_id}"\n'
            + "def uri(chat: str, message: str) -> str:\n"
            + "    return _TEMPLATE.format(chat_id=chat, message_id=message)\n"
        ) == ["line 3 spells a handle through _TEMPLATE (bound on line 1)"]

    def test_catches_a_handle_assembled_with_join(self) -> None:
        assert _handle_spellings(
            "def uri(chat_id: str, message_id: str) -> str:\n"
            + '    return "/".join(("teams:///chats", chat_id, "messages", message_id))\n'
        ) == ["line 2 spells a handle"]

    def test_catches_a_handle_assembled_with_percent_formatting(self) -> None:
        assert _handle_spellings(
            "def uri(chat_id: str, message_id: str) -> str:\n"
            + '    return "teams:///chats/%s/messages/%s" % (chat_id, message_id)\n'
        ) == ["line 2 spells a handle"]

    def test_catches_an_f_string_that_reaches_the_scheme_through_a_constant(self) -> None:
        """No literal in the f-string carries the scheme, so the building check cannot see it: what
        gives it away is the constant being *built with*."""
        assert _handle_spellings(
            '_SCHEME = "teams:///"\n'
            + "def uri(chat_id: str) -> str:\n"
            + '    return f"{_SCHEME}chats/{chat_id}"\n'
        ) == ["line 3 builds a handle through _SCHEME (bound on line 1)"]

    def test_catches_a_hand_rolled_parser(self) -> None:
        found = _handle_spellings(
            "def parse(uri: str) -> tuple[str, str] | None:\n"
            + '    if not uri.startswith("teams:///"):\n'
            + "        return None\n"
            + '    chat, _, message = uri.removeprefix("teams:///chats/").partition("/messages/")\n'
            + "    return chat, message\n"
        )

        # Sorted rather than in source order: the walk is breadth-first, so two literals at
        # different depths come out in tree order, not file order.
        assert sorted(found) == ["line 2 spells a handle", "line 4 spells a handle"]

    def test_leaves_a_handle_shown_to_a_model_alone(self) -> None:
        """Prose is most of what the scheme is written in here, which is the property the text-level
        check must keep."""
        assert not _handle_spellings(
            '"""The `teams:///` grammar: every shape this connector mints."""\n'
            + '_BAD = "A readable handle looks like teams:///chats/{chat_id}/messages/{id}."\n'
            + '_SEEN = "e.g. teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000 — "\n'
            + '_ELSE = "a teams:///transcripts/... handle is not one this connector reads"\n'
            + '_DESC = f"""Pass teams:///transcripts/{{meeting_id}}/{{transcript_id}}, up to'
            + ' {MAX_TURNS} turns."""\n'
        )

    def test_leaves_a_schema_example_alone(self) -> None:
        """A real handle has a percent-encoded id and no whitespace anywhere, so it looks exactly
        like one being built."""
        assert not _handle_spellings(
            "uri: str = Field(\n"
            + '    description="The message to read.",\n'
            + '    examples=["teams:///chats/19%3Aabc%40thread.v2/messages/1700000000000"],\n'
            + ")\n"
        )

    def test_leaves_a_json_schema_extra_example_alone(self) -> None:
        assert not _handle_spellings(
            'uri: str = Field(json_schema_extra={"example": "teams:///transcripts/AAA/BBB"})\n'
        )

    def test_leaves_a_docstring_that_is_the_shape_alone(self) -> None:
        assert not _handle_spellings(
            "def meeting_uri(meeting_id: str) -> str:\n"
            + '    """teams:///meetings/{meeting_id}"""\n'
            + "    return _handle(meeting_id)\n"
        )

    def test_leaves_a_refusal_fragment_alone(self) -> None:
        assert not _handle_spellings(
            '_HINT = "teams:///meetings/..."\n'
            + "def refuse() -> str:\n"
            + '    return _HINT + " is the shape this tool takes"\n'
        )

    def test_catches_the_violation_the_recording_content_rule_exists_for(self) -> None:
        found = _attribute_names(
            "async def fetch(client, meeting_id, recording_id):\n"
            + "    item = client.me.online_meetings.by_online_meeting_id(meeting_id)"
            + ".recordings.by_call_recording_id(recording_id)\n"
            + "    return await item.content.get(), item.recording_content_url\n"
        )

        assert found & _RECORDING_ITEM_NAMES == _RECORDING_ITEM_NAMES

    def test_the_recording_content_rule_leaves_the_collection_and_the_prose_alone(self) -> None:
        found = _attribute_names(
            '"""Not returned: recordingContentUrl needs our own bearer token."""\n'
            + "page = await client.me.online_meetings.by_online_meeting_id(m).recordings.get()\n"
        )

        assert not found & _RECORDING_ITEM_NAMES

    def test_does_not_fire_on_a_name_that_merely_starts_with_the_prefix(self) -> None:
        assert not _imports_under("from office_365_mcp.toolsmith import thing", _TOOLS_PREFIX)
        assert not _imports_under("from office_365_mcp.sharedish import thing", _SHARED_PREFIX)
        assert not _imports_under("from office_365_mcp.configuration import thing", _CONFIG_MODULE)


class TestSharedIsUpstreamOfEveryTool:
    def test_the_shared_tree_is_actually_there(self) -> None:
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
        """Rule 3 is permissive, so what makes it a rule is that all three permitted dependencies
        are genuinely used: a `tools/` that stopped reaching for `shared/` would have copied the
        vocabulary into the tool files instead."""
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


class TestNoToolKnowsAboutAnotherTool:
    def test_there_is_more_than_one_tool_to_confuse(self) -> None:
        """A rule that no tool module imports another says nothing about a package holding one."""
        modules = _tool_modules()
        assert len(modules) > 1, f"fewer than two tool modules under {_TOOLS}"
        imported = _registry_imports()
        missing = sorted({source.stem for source in modules} - imported)
        assert not missing, (
            "tools/__init__.py must import every tool module — the Graph scopes sign-in asks for "
            + "are derived from them, so one it does not name is a tool whose permission never "
            + f"reaches the consent screen (missing {missing})"
        )

    @pytest.mark.parametrize("source", _tool_modules(), ids=_source_id)
    def test_no_tool_module_imports_another_tool_module(self, source: pathlib.Path) -> None:
        own = _dotted_module(source)
        violations = [
            violation
            for violation in _violations(source, _TOOLS_PREFIX)
            if f"imports {own}" not in violation
        ]
        assert not violations, (
            "a tool file must not import another tool file — that is what independent means, and "
            + "it is the rule this whole layout exists for. What two tools need is shared "
            + "vocabulary and belongs in shared/, where the fact that two of them depend on it is "
            + "visible; what one tool needs stays in that tool. A description, an error text or a "
            + "helper borrowed across is how a tool-declaration module grows back:\n  "
            + "\n  ".join(violations)
        )


class TestEachHandleFamilyHasOneHome:
    def test_the_owner_actually_writes_every_family(self) -> None:
        assert _HANDLE_OWNER.is_file(), f"no such file: {_HANDLE_OWNER}"
        # A bare `teams:///` with no family after it is the docstring naming the scheme itself.
        families: list[str] = _HANDLE_FAMILY.findall(_HANDLE_OWNER.read_text())
        written = {family for family in families if family}

        assert written == _HANDLE_FAMILIES, (
            f"{_HANDLE_OWNER.name} spells the handle families {sorted(written)}, and rule 6 gives "
            + f"it {sorted(_HANDLE_FAMILIES)}"
        )

    def test_the_owner_both_builds_and_matches_them(self) -> None:
        spellings = _handle_spellings(_HANDLE_OWNER.read_text())

        assert any("builds" in spelling for spelling in spellings), (
            f"{_HANDLE_OWNER.name} no longer builds a handle"
        )
        assert any("matches" in spelling for spelling in spellings), (
            f"{_HANDLE_OWNER.name} no longer parses a handle"
        )

    @pytest.mark.parametrize(
        "source", [s for s in _sources(_SRC) if s != _HANDLE_OWNER], ids=_source_id
    )
    def test_no_other_module_builds_or_parses_a_handle(self, source: pathlib.Path) -> None:
        violations = _handle_violations(source)
        assert not violations, (
            "shared/handles.py is the only module that may build or parse a teams:/// URI — a "
            + "second speller is free to disagree with it, and the disagreement looks like a "
            + "handle one tool produced and another cannot read. Build that module's handle type "
            + "and read its `uri`, or call its parser. What is caught here is a literal something "
            + "is DONE to: concatenated with a value, %-formatted, .format()ed, .join()ed, matched "
            + "with re.*, or taken apart with startswith/removeprefix/split/partition — and, where "
            + "the report names a constant, the line that builds or parses with it rather than the "
            + "line that bound it. Showing the shape to a model is prose and is not this: a "
            + "description, an `examples=`, a `json_schema_extra` example, a docstring that is the "
            + "shape, and a refusal that quotes it are all left alone:\n  "
            + "\n  ".join(violations)
        )


class TestNoModuleReachesForRecordingBytes:
    """Rule 7."""

    def test_the_recordings_listing_is_actually_there(self) -> None:
        listings = _recording_listings()
        assert listings, (
            "nothing under src/ reads a meeting's recordings collection "
            + f"({'.'.join(sorted(_RECORDINGS_COLLECTION))}), so rule 7 forbids something nothing "
            + "does. This rule is PERMANENT and is not the thing to delete: it is the only door to "
            + "a recording's bytes. If the listing moved, this guard should have found it wherever "
            + "it went — check that the new home still walks the collection through "
            + "`online_meetings.by_online_meeting_id(...).recordings`. If the listing was "
            + "genuinely removed, the recordings surface is gone and that is the change to explain"
        )

    @pytest.mark.parametrize("source", _sources(_SRC), ids=_source_id)
    def test_no_module_addresses_a_single_recording(self, source: pathlib.Path) -> None:
        violations = _recording_item_violations(source)
        assert not violations, (
            "nothing here may address one meeting recording — the only things behind that door are "
            + "an MP4 of a meeting up to 30 hours long, which cannot enter a model's context and "
            + "which delegated callers other than the organiser may not download at all, and a "
            + "content URL that only this connector's token opens. List the collection and report "
            + "metadata, duration and access instead:\n  "
            + "\n  ".join(violations)
        )


class TestPackagesAreEnteredThroughTheirInit:
    """Rule 8."""

    @pytest.mark.parametrize("package", _PUBLIC_SURFACE_PACKAGES)
    def test_every_listed_package_actually_publishes_something(self, package: str) -> None:
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
        """A renamed entrypoint would silently widen the exemption."""
        for relative in sorted(_COMPOSITION_ROOTS):
            assert (_SRC / relative).is_file(), f"no such file: {relative}"

    def test_the_composition_root_really_does_build_every_config(self) -> None:
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
