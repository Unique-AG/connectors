"""The structural rules this package's layout depends on.

Ported from `services/backstop-mcp` with the same numbering, so a reader who knows that service
knows this one. Most are vacuous today — there are no features yet — which is the point of
having them now: the rule is in place before the code it governs, and `TestTheDetectionItself`
proves each detector actually fires, so a rule cannot pass merely by having nothing to inspect.

1. **`features/` must not import `server/`.** `features/` is what the connector does; `server/`
   is how it's exposed over MCP. The server wires features together, so it imports them freely —
   the reverse is an inversion. Tools declare collaborators as `Depends(...)` parameters rather
   than importing `server/`.

2. **`with_intelligence_client/` must not import `features/`.** The HTTP client is
   infrastructure that features consume; it importing one back is the same inversion. A type
   both sides need lives in the transport package, with `features/` supplying the implementation
   (in backstop-mcp, a Protocol in `credential.py` — this service will do the same for its
   vendor session).

3. **`with_intelligence_client/` must not import `config`.** The transport takes its own frozen
   settings types, translated from `WithIntelligenceConfig` by `dependencies`. `features/` is
   deliberately *not* subject to this rule: a feature is allowed to be configured — a transport
   is only allowed to be told.

4. **A package is entered through its `__init__`, never through its modules.** From outside,
   `from with_intelligence_mcp.db import transaction` — not `...db.engine import transaction`.
   Each package's `__all__` is then the whole of what it promises, and everything else is free
   to move. Tests walk the same rule, except tool tests, which import the tool under test from
   its own module because individual tool modules are not a public import surface.

5. **Feature model layers flow downward.** A `*Attributes` class lives in `api_responses*`, a
   `*Dto` class in `internal_dto*`, and a `*Response` class in `responses*`. Imports among
   those three run one way only (`responses` → `internal_dto` → `api_responses`). No model
   declares `extra="forbid"`. A feature's `tools/` declare their own models — a tool's wire
   contract lives beside it — and are exempt.

6. **A logic module is named after the symbol it defines.** The filename stem, or the PascalCase
   of it, must be a top-level function, class, or assignment in that file — `fetch_investor.py`
   holds `fetch_investor`, `vocabulary_service.py` holds `VocabularyService`. Vocabulary modules
   (`api_responses*`, `internal_dto*`, `responses*`, `entity_types.py`, `settings.py`,
   `dependencies.py`) keep their names; `_`-prefixed modules are private shared utilities.

7. **Every tool module is registered.** A non-private module under `features/<feature>/tools/`
   defines exactly one `@tool`-decorated function named after the file, and that name appears on
   `TOOLS`. A file that is never registered fails the suite rather than shipping an unreachable
   tool.

Rules 1–6 are asserted by walking the AST rather than importing anything, so a violation is
reported with a file and line instead of an ImportError at collection time. Rule 7 uses AST for
the `@tool` shape and imports `TOOLS` for the registry check.
"""

import ast
import pathlib

from with_intelligence_mcp.server.tools import TOOLS

_SRC = pathlib.Path(__file__).parent.parent / "src" / "with_intelligence_mcp"
_TESTS = pathlib.Path(__file__).parent

_FEATURES = _SRC / "features"
_CLIENT = _SRC / "with_intelligence_client"

_PACKAGE = "with_intelligence_mcp"
_SERVER_PREFIX = f"{_PACKAGE}.server"
_FEATURES_PREFIX = f"{_PACKAGE}.features"
_CLIENT_PREFIX = f"{_PACKAGE}.with_intelligence_client"
_CONFIG_MODULE = f"{_PACKAGE}.config"

# Packages that publish a surface: outside code imports the package, never a module inside it.
# A new package belongs here as soon as its `__init__` exports anything. `features/` and
# `server/` are not among them: they are groupings whose `__init__` is documentation, so
# `server.tools` is itself the unit being imported.
_PUBLIC_SURFACE_PACKAGES: tuple[str, ...] = (
    f"{_PACKAGE}.db",
    f"{_PACKAGE}.with_intelligence_client",
)

_MODEL_LAYERS: tuple[str, ...] = ("api_responses", "internal_dto", "responses")
_MODEL_LAYER_RANK = {name: index for index, name in enumerate(_MODEL_LAYERS)}
_CLASS_SUFFIX_LAYER = {
    "Attributes": "api_responses",
    "Dto": "internal_dto",
    "Response": "responses",
}

# Modules named for a vocabulary rather than for a symbol they define (rule 6).
_VOCABULARY_FILES = frozenset(
    {
        "__init__.py",
        "dependencies.py",
        "entity_types.py",
        "settings.py",
        *(f"{layer}.py" for layer in _MODEL_LAYERS),
    }
)


def _python_sources(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(root.rglob("*.py")) if root.exists() else []


def _imported_modules(tree: ast.AST) -> list[tuple[str, int]]:
    """Every module an AST imports, as `(dotted name, line number)`."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.append((node.module, node.lineno))
    return found


def _imports_under(source: str, prefix: str) -> list[str]:
    """Modules imported by `source` that sit at or under `prefix`. The shared detector."""
    tree = ast.parse(source)
    return [
        module
        for module, _ in _imported_modules(tree)
        if module == prefix or module.startswith(f"{prefix}.")
    ]


def _violations(source: pathlib.Path, prefix: str) -> list[str]:
    tree = ast.parse(source.read_text(), filename=str(source))
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _imported_modules(tree)
        if module == prefix or module.startswith(f"{prefix}.")
    ]


def _reaches_past_init(module: str) -> str | None:
    """The public-surface package `module` reaches past, if any (rule 4)."""
    for package in _PUBLIC_SURFACE_PACKAGES:
        if module.startswith(f"{package}."):
            return package
    return None


def _is_inside(directory: pathlib.Path, package: str) -> bool:
    """Whether `directory` is the package's own tree — where internal imports are allowed."""
    own = _SRC.parent / pathlib.Path(*package.split("."))
    return directory == own or own in directory.parents


def _layer_of(name: str) -> str | None:
    """The model layer a filename stem or module tail names."""
    for layer in _MODEL_LAYERS:
        if name == layer or name.startswith(f"{layer}_"):
            return layer
    return None


def _pascal_case(stem: str) -> str:
    return "".join(part.title() for part in stem.split("_"))


def _top_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.AnnAssign, ast.TypeAlias)):
            target = node.target if isinstance(node, ast.AnnAssign) else node.name
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _is_tool_decorator(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "tool"
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tool"


def _tool_decorated_names(tree: ast.AST) -> list[str]:
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_is_tool_decorator(decorator) for decorator in node.decorator_list)
    ]


def _feature_tool_modules() -> list[pathlib.Path]:
    """Non-private `*.py` under `features/<feature>/tools/`."""
    return [
        source
        for source in _python_sources(_FEATURES)
        if source.parent.name == "tools"
        and source.parent.parent.parent == _FEATURES
        and not source.name.startswith("_")
        and source.name != "__init__.py"
    ]


def _is_under_feature_tools(source: pathlib.Path) -> bool:
    return source.parent.name == "tools" and _FEATURES in source.parents


class TestRule1FeaturesMustNotImportServer:
    def test_no_feature_imports_server(self) -> None:
        found = [
            v for source in _python_sources(_FEATURES) for v in _violations(source, _SERVER_PREFIX)
        ]
        assert found == [], "features/ must not import server/: " + "; ".join(found)


class TestRule2ClientMustNotImportFeatures:
    def test_no_client_module_imports_features(self) -> None:
        found = [
            v for source in _python_sources(_CLIENT) for v in _violations(source, _FEATURES_PREFIX)
        ]
        assert found == [], "with_intelligence_client/ must not import features/: " + "; ".join(
            found
        )


class TestRule3ClientMustNotImportConfig:
    def test_no_client_module_imports_config(self) -> None:
        found = [
            v for source in _python_sources(_CLIENT) for v in _violations(source, _CONFIG_MODULE)
        ]
        assert found == [], (
            "with_intelligence_client/ takes its own settings types, not config: "
            + "; ".join(found)
        )


class TestRule4PackagesAreEnteredThroughTheirInit:
    def test_nothing_reaches_past_a_public_packages_init(self) -> None:
        found: list[str] = []
        for source in [*_python_sources(_SRC), *_python_sources(_TESTS)]:
            root = _SRC if _SRC in source.parents else _TESTS
            tree = ast.parse(source.read_text(), filename=str(source))
            for module, line in _imported_modules(tree):
                package = _reaches_past_init(module)
                if package is None or _is_inside(source.parent, package):
                    continue
                found.append(f"{source.relative_to(root)}:{line} imports {module}")
        assert found == [], "enter a package through its __init__, not its modules: " + "; ".join(
            found
        )


class TestRule5FeatureModelLayersFlowDownward:
    def test_class_suffixes_match_their_layer(self) -> None:
        found: list[str] = []
        for source in _python_sources(_FEATURES):
            if _is_under_feature_tools(source):
                continue
            layer = _layer_of(source.stem)
            tree = ast.parse(source.read_text(), filename=str(source))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                for suffix, expected in _CLASS_SUFFIX_LAYER.items():
                    if node.name.endswith(suffix) and layer != expected:
                        found.append(
                            f"{source.relative_to(_SRC)}:{node.lineno} {node.name} belongs "
                            + f"in {expected}*, not {source.stem}"
                        )
        assert found == [], "; ".join(found)

    def test_layer_imports_run_one_way(self) -> None:
        found: list[str] = []
        for source in _python_sources(_FEATURES):
            layer = _layer_of(source.stem)
            if layer is None:
                continue
            tree = ast.parse(source.read_text(), filename=str(source))
            for module, line in _imported_modules(tree):
                imported = _layer_of(module.rsplit(".", 1)[-1])
                if imported is None:
                    continue
                if _MODEL_LAYER_RANK[imported] >= _MODEL_LAYER_RANK[layer]:
                    found.append(
                        f"{source.relative_to(_SRC)}:{line} {layer} imports {imported} "
                        + "(layers flow responses -> internal_dto -> api_responses)"
                    )
        assert found == [], "; ".join(found)

    def test_no_model_declares_extra_forbid(self) -> None:
        found = [
            f'{source.relative_to(_SRC)} declares extra="forbid"'
            for source in _python_sources(_FEATURES)
            if '"forbid"' in source.read_text() or "'forbid'" in source.read_text()
        ]
        assert found == [], "; ".join(found)


class TestRule6ModuleNamedAfterItsSymbol:
    def test_every_logic_module_defines_its_own_name(self) -> None:
        found: list[str] = []
        for source in _python_sources(_FEATURES):
            if source.name in _VOCABULARY_FILES or source.name.startswith("_"):
                continue
            if _layer_of(source.stem) is not None:
                continue
            tree = ast.parse(source.read_text(), filename=str(source))
            names = _top_level_names(tree)
            if source.stem not in names and _pascal_case(source.stem) not in names:
                found.append(
                    f"{source.relative_to(_SRC)} defines neither {source.stem} "
                    + f"nor {_pascal_case(source.stem)}"
                )
        assert found == [], "; ".join(found)


class TestRule7EveryToolModuleIsRegistered:
    def test_each_tool_module_defines_one_tool_named_after_the_file(self) -> None:
        found: list[str] = []
        for source in _feature_tool_modules():
            names = _tool_decorated_names(ast.parse(source.read_text(), filename=str(source)))
            display = source.relative_to(_SRC)
            if len(names) != 1:
                found.append(f"{display} defines {len(names)} @tool functions, expected 1")
            elif names[0] != source.stem:
                found.append(f"{display} @tool {names[0]!r} does not match filename")
        assert found == [], "; ".join(found)

    def test_each_tool_module_appears_in_tools(self) -> None:
        registered = {getattr(fn, "__name__", "") for fn in TOOLS}
        found = [
            f"{source.relative_to(_SRC)} is not in TOOLS"
            for source in _feature_tool_modules()
            if source.stem not in registered
        ]
        assert found == [], "; ".join(found)

    def test_tools_holds_no_duplicates(self) -> None:
        names = [getattr(fn, "__name__", "") for fn in TOOLS]
        assert len(names) == len(set(names)), f"TOOLS lists a tool twice: {names}"


class TestTheDetectionItself:
    """The rules are only worth having if they fail on the things they're meant to catch.

    Every rule above is vacuous while `features/` is empty, so without these the suite would
    report seven passing guards that have never inspected anything.
    """

    def test_catches_a_feature_importing_the_server(self) -> None:
        assert _imports_under(
            "from with_intelligence_mcp.server.tools.registry import TOOLS", _SERVER_PREFIX
        ) == [f"{_PACKAGE}.server.tools.registry"]

    def test_catches_the_client_importing_a_feature(self) -> None:
        assert _imports_under(
            "from with_intelligence_mcp.features.auth import VendorSession", _FEATURES_PREFIX
        ) == [f"{_PACKAGE}.features.auth"]

    def test_catches_the_client_importing_config(self) -> None:
        assert _imports_under(
            "from with_intelligence_mcp.config import WithIntelligenceConfig", _CONFIG_MODULE
        ) == [_CONFIG_MODULE]

    def test_ignores_an_import_of_a_sibling_package(self) -> None:
        assert (
            _imports_under("from with_intelligence_mcp.db import transaction", _SERVER_PREFIX) == []
        )

    def test_catches_reaching_past_a_public_init(self) -> None:
        assert _reaches_past_init(f"{_PACKAGE}.db.engine") == f"{_PACKAGE}.db"

    def test_allows_the_package_init_itself(self) -> None:
        assert _reaches_past_init(f"{_PACKAGE}.db") is None

    def test_a_package_may_import_its_own_modules(self) -> None:
        assert _is_inside(_SRC / "db", f"{_PACKAGE}.db")
        assert not _is_inside(_SRC / "features" / "investors", f"{_PACKAGE}.db")

    def test_recognises_the_model_layers(self) -> None:
        assert _layer_of("responses") == "responses"
        assert _layer_of("internal_dto") == "internal_dto"
        assert _layer_of("api_responses_investor") == "api_responses"
        assert _layer_of("fetch_investor") is None

    def test_ranks_the_layers_downward(self) -> None:
        assert _MODEL_LAYER_RANK["api_responses"] < _MODEL_LAYER_RANK["internal_dto"]
        assert _MODEL_LAYER_RANK["internal_dto"] < _MODEL_LAYER_RANK["responses"]

    def test_pascal_cases_a_module_stem(self) -> None:
        assert _pascal_case("vocabulary_service") == "VocabularyService"

    def test_finds_the_symbols_a_module_defines(self) -> None:
        names = _top_level_names(
            ast.parse(
                "async def fetch_investor() -> None: ...\n"
                + "class VocabularyService: ...\n"
                + "PAGE_SIZE = 50\n"
                + "type ToolFunction = object\n"
            )
        )
        assert names == {"fetch_investor", "VocabularyService", "PAGE_SIZE", "ToolFunction"}

    def test_recognises_a_tool_decorated_function(self) -> None:
        names = _tool_decorated_names(
            ast.parse(
                "@tool\nasync def get_investor() -> None: ...\n"
                + "@tool(annotations=None)\nasync def search_investors() -> None: ...\n"
                + "async def helper() -> None: ...\n"
            )
        )
        assert names == ["get_investor", "search_investors"]
