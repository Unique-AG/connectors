"""The structural rules this package's layout depends on.

1. **`features/` must not import `server/`.** `features/` is what the connector does; `server/`
   is how it's exposed over MCP. The server wires features together, so it imports them freely —
   the reverse is an inversion. This used to be a convention and it was already broken once:
   a glossary middleware living under `custom_fields/` imported `tools.registry`, which only
   avoided a circular import because `custom_fields/__init__.py` happened not to import it.
   That middleware is gone; the rule remains.

2. **`backstop_client/` must not import `features/`.** The HTTP client is infrastructure that
   features consume; it importing one back is the same inversion, and it had the same near-miss.
   `client.py`/`factory.py` imported `features.auth` for the credential type and the auth
   context while `features/auth/provider.py` imported `backstop_client` — a genuine package
   cycle that only worked because `features/auth/__init__.py` is empty. Those two types now live
   in `backstop_client/credential.py` (the context as a Protocol), so the direction is one-way.

3. **`backstop_client/` must not import `config`.** The transport takes
   `BackstopTransportSettings`/`RetrySettings` — its own frozen types, translated from
   `BackstopConfig` by `create_app`. It used to take the `pydantic-settings` model directly, which
   coupled the layer to the env-parsing shape and to every knob on it, including the ones it has
   no business seeing (the custom-field schema TTL). `features/` is
   deliberately *not* subject to this rule: it may read config freely (see `features/__init__.py`),
   because a feature is allowed to be configured — a transport is only allowed to be told.

4. **A package is entered through its `__init__`, never through its modules.** From outside,
   `from backstop_mcp.features.data_hygiene import EmploymentIndexFactory` — not
   `...data_hygiene.employment_index_factory import ...`, and certainly not an internal from
   `...data_hygiene.employment_index`. Each package's `__all__` is then the whole of what it
   promises, and everything else is free to move.

   This is what makes a package able to say "call it this way". `data_hygiene/employment_index.py`
   is the fold over already-classified edges; `EmploymentIndexFactory` supplies the employment
   vocabulary, the side-loaded relationship types and a clock, from configuration, once.
   Reaching past it is how the original bug happened — `get_person` assembled its own vocabulary
   with `BackstopConfig()`, so whatever `create_app` had been given was silently ignored.
   `__all__` alone is only a convention; this rule is what makes it hold.

   Applies to the packages listed in `_PUBLIC_SURFACE_PACKAGES`. `features/` and `server/` are
   not among them: they are groupings whose `__init__` is documentation, so `features.resolution`
   and `server.runtime` are themselves the unit being imported.

5. **Feature model layers flow downward.** A `*Attributes` class lives in `api_responses*`, a
   `*Dto` class in `internal_dto*`, and a `*Response` class in `responses*`. Imports among those
   three modules run one way only (`responses` → `internal_dto` → `api_responses`) within a
   feature. No model declares `extra="forbid"`. `*Attributes` declare `extra="ignore"`;
   `extra="allow"` is only where passthrough is the point (`PersonRecordResponse`,
   `OrganizationRecordResponse`, `SystemInfoResponse`). `features/includes/` is exempt from
   the layer filenames: its
   projection models intentionally combine camelCase aliases with FastMCP descriptions, so the
   response class *is* the wire shape. `features/resolution.py` is cross-cutting rather than
   per-feature and keeps its filename.

6. **A logic module is named after the symbol it defines.** The filename stem, or the PascalCase
   of it, must be a top-level function, class, or assignment in that file — `fetch_series.py`
   holds `fetch_series`, `custom_fields_service.py` holds `CustomFieldsService`. That is how the
   tree stays readable. Modules used to be named after a mechanism (`fetch.py`, `service.py`,
   `project.py`), so you had to open a file or grep for `def` to find anything. Vocabulary
   modules (`api_responses*`, `internal_dto*`, `responses*`, `entity_types.py`,
   `includes/types.py`, `settings.py`) keep their names; `_`-prefixed modules are private shared
   utilities. `features/auth/` is out of scope; `features/resolution.py` is already exempt by
   name in rule 5.

All six are asserted by walking the AST rather than importing anything, so a violation is
reported as a failing test with a file and line instead of an ImportError at collection time.
"""

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).parent.parent / "src" / "backstop_mcp"

_FEATURES = _SRC / "features"
_BACKSTOP_CLIENT = _SRC / "backstop_client"
_SERVER_PREFIX = "backstop_mcp.server"
_FEATURES_PREFIX = "backstop_mcp.features"
_CONFIG_MODULE = "backstop_mcp.config"

# Packages that publish a surface: outside code imports the package, never a module inside it.
# Tests are deliberately exempt — they walk `src` only — so the pieces a package composes stay
# directly testable without being callable from production code that should go through the front
# door. A new package belongs here as soon as its `__init__` exports anything.
_PUBLIC_SURFACE_PACKAGES: tuple[str, ...] = (
    "backstop_mcp.backstop_client",
    "backstop_mcp.db",
    "backstop_mcp.features.accounts",
    "backstop_mcp.features.activity_history",
    "backstop_mcp.features.auth",
    "backstop_mcp.features.custom_fields",
    "backstop_mcp.features.data_hygiene",
    "backstop_mcp.features.includes",
    "backstop_mcp.features.opportunities",
    "backstop_mcp.features.org_people",
    "backstop_mcp.features.party_resolver",
    "backstop_mcp.server.tools",
)


def _imported_modules(tree: ast.AST) -> list[tuple[str, int]]:
    """Every module name this file imports, with the line it's imported on."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        # `level > 0` is a relative import, which can't escape `features/` by name anyway.
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.append((node.module, node.lineno))
    return found


def _source_id(source: pathlib.Path) -> str:
    """Test id for one module: `features/custom_fields/service.py`, not an absolute path."""
    return str(source.relative_to(_SRC))


def _imports_under(source: str, prefix: str) -> list[str]:
    """The `prefix`-rooted modules `source` imports. Both rules below are this, over real files."""
    return [
        module
        for module, _line in _imported_modules(ast.parse(source))
        if module == prefix or module.startswith(f"{prefix}.")
    ]


def _violations(source: pathlib.Path, prefix: str) -> list[str]:
    tree = ast.parse(source.read_text(), filename=str(source))
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _imported_modules(tree)
        if module == prefix or module.startswith(f"{prefix}.")
    ]


def _declares_dunder_all(node: ast.AST) -> bool:
    """Both spellings: bare `__all__ = [...]` and annotated `__all__: list[str] = [...]`.

    The annotated form parses as `AnnAssign`, not `Assign`.
    """
    if isinstance(node, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        )
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and node.target.id == "__all__"
    return False


def _package_directory(package: str) -> pathlib.Path:
    """`backstop_mcp.features.data_hygiene` → the directory that package's modules live in."""
    return _SRC.joinpath(*package.split(".")[1:])


def _is_inside(directory: pathlib.Path, package: str) -> bool:
    return directory == _package_directory(package) or directory.is_relative_to(
        _package_directory(package)
    )


def _internal_imports(source: str, directory: pathlib.Path) -> list[tuple[str, int]]:
    """Modules of a public-surface package that `source` reaches past the `__init__` for.

    A file inside a package may import its own package's modules freely — that is the package
    composing itself — so the directory the file lives in, not its name, decides.
    """
    return [
        (module, line)
        for package in _PUBLIC_SURFACE_PACKAGES
        if not _is_inside(directory, package)
        for module, line in _imported_modules(ast.parse(source))
        if module.startswith(f"{package}.")
    ]


def _internal_module_violations(source: pathlib.Path) -> list[str]:
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _internal_imports(source.read_text(), source.parent)
    ]


_MODEL_LAYERS: tuple[str, ...] = ("api_responses", "internal_dto", "responses")
_MODEL_LAYER_RANK = {name: index for index, name in enumerate(_MODEL_LAYERS)}
_MODEL_LAYER_EXEMPT_FEATURES = frozenset({"includes"})
_MODEL_LAYER_EXEMPT_FILES = frozenset({"resolution.py"})


def _feature_relative(source: pathlib.Path) -> pathlib.Path | None:
    try:
        return source.relative_to(_FEATURES)
    except ValueError:
        return None


def _is_governed_model_source(source: pathlib.Path) -> bool:
    relative = _feature_relative(source)
    if relative is None or not relative.parts:
        return False
    return (
        relative.parts[0] not in _MODEL_LAYER_EXEMPT_FEATURES
        and relative.name not in _MODEL_LAYER_EXEMPT_FILES
    )


def _model_layer_for_path(source: pathlib.Path) -> str | None:
    relative = _feature_relative(source)
    if relative is None:
        return None
    parts = relative.with_suffix("").parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    for part in parts:
        for layer in _MODEL_LAYERS:
            if part.startswith(layer):
                return layer
    return None


def _model_layer_for_module(module: str) -> str | None:
    prefix = f"{_FEATURES_PREFIX}."
    if not (module == prefix[:-1] or module.startswith(prefix)):
        return None
    parts = module[len(prefix) :].split(".")
    if not parts or parts[0] in _MODEL_LAYER_EXEMPT_FEATURES:
        return None
    for part in parts[1:]:
        for layer in _MODEL_LAYERS:
            if part.startswith(layer):
                return layer
    return None


def _expected_model_layer(class_name: str) -> str | None:
    if class_name.endswith("Attributes"):
        return "api_responses"
    if class_name.endswith("Dto"):
        return "internal_dto"
    if class_name.endswith("Response"):
        return "responses"
    return None


def _class_layer_violations(source: str, path: pathlib.Path) -> list[str]:
    tree = ast.parse(source, filename=str(path))
    actual = _model_layer_for_path(path)
    return [
        f"{path.relative_to(_SRC)}:{node.lineno} class {node.name} belongs in {expected}*"
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and (expected := _expected_model_layer(node.name)) is not None
        and actual != expected
    ]


def _layer_import_violations(source: str, path: pathlib.Path) -> list[str]:
    from_layer = _model_layer_for_path(path)
    if from_layer is None:
        return []
    from_rank = _MODEL_LAYER_RANK[from_layer]
    feature = _feature_relative(path)
    assert feature is not None
    feature_name = feature.parts[0]
    prefix = f"{_FEATURES_PREFIX}.{feature_name}."
    return [
        f"{path.relative_to(_SRC)}:{line} imports {module} (upward from {from_layer})"
        for module, line in _imported_modules(ast.parse(source, filename=str(path)))
        if module.startswith(prefix)
        and (to_layer := _model_layer_for_module(module)) is not None
        and _MODEL_LAYER_RANK[to_layer] > from_rank
    ]


def _keyword_extra_is_forbid(keyword: ast.keyword) -> bool:
    return (
        keyword.arg == "extra"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value == "forbid"
    )


def _dict_extra_is_forbid(node: ast.Dict) -> bool:
    return any(
        isinstance(key, ast.Constant)
        and key.value == "extra"
        and isinstance(value, ast.Constant)
        and value.value == "forbid"
        for key, value in zip(node.keys, node.values, strict=True)
    )


def _declares_extra_forbid(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        return any(_keyword_extra_is_forbid(keyword) for keyword in node.keywords)
    return isinstance(node, ast.Dict) and _dict_extra_is_forbid(node)


def _extra_forbid_violations(source: str, path: pathlib.Path) -> list[str]:
    tree = ast.parse(source, filename=str(path))
    return [
        f'{path.relative_to(_SRC)}:{node.lineno} declares extra="forbid"'
        for node in ast.walk(tree)
        if isinstance(node, (ast.Call, ast.Dict)) and _declares_extra_forbid(node)
    ]


def _model_config_value(stmt: ast.stmt) -> ast.expr | None:
    if (
        isinstance(stmt, ast.AnnAssign)
        and isinstance(stmt.target, ast.Name)
        and stmt.target.id == "model_config"
    ):
        return stmt.value
    if isinstance(stmt, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "model_config" for target in stmt.targets
    ):
        return stmt.value
    return None


def _config_extra(node: ast.ClassDef) -> str | None:
    for stmt in node.body:
        value = _model_config_value(stmt)
        if isinstance(value, ast.Call):
            for keyword in value.keywords:
                if (
                    keyword.arg == "extra"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    return keyword.value.value
    return None


def _attributes_extra_violations(source: str, path: pathlib.Path) -> list[str]:
    tree = ast.parse(source, filename=str(path))
    return [
        (
            f"{path.relative_to(_SRC)}:{node.lineno} class {node.name} declares "
            + f'extra={extra!r}, expected "ignore"'
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and node.name.endswith("Attributes")
        and (extra := _config_extra(node)) != "ignore"
    ]


def _governed_model_sources() -> list[pathlib.Path]:
    return sorted(source for source in _FEATURES.rglob("*.py") if _is_governed_model_source(source))


def _governed_model_layer_sources() -> list[pathlib.Path]:
    return [source for source in _governed_model_sources() if _model_layer_for_path(source)]


_LOGIC_NAME_VOCABULARY_FILES = frozenset({"entity_types.py", "settings.py", "resolution.py"})
_LOGIC_NAME_VOCABULARY_PATHS = frozenset({pathlib.Path("includes") / "types.py"})


def _pascal_case_stem(stem: str) -> str:
    """`custom_fields_service` → `CustomFieldsService`; a leading `_` is dropped."""
    return "".join(part.capitalize() for part in stem.split("_") if part)


def _is_governed_logic_source(source: pathlib.Path) -> bool:
    relative = _feature_relative(source)
    if relative is None or not relative.parts:
        return False
    if source.name == "__init__.py" or relative.parts[0] == "auth":
        return False
    if source.name in _LOGIC_NAME_VOCABULARY_FILES or relative in _LOGIC_NAME_VOCABULARY_PATHS:
        return False
    if source.name.startswith("_"):
        return False
    if _model_layer_for_path(source) is not None:
        return False
    return not any(part.startswith(layer) for part in relative.parts for layer in _MODEL_LAYERS)


def _governed_logic_sources() -> list[pathlib.Path]:
    return sorted(source for source in _FEATURES.rglob("*.py") if _is_governed_logic_source(source))


def _top_level_defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _logic_module_name_violations(source: str, path: pathlib.Path) -> list[str]:
    if not _is_governed_logic_source(path):
        return []
    stem = path.stem
    pascal = _pascal_case_stem(stem)
    defined = _top_level_defined_names(ast.parse(source, filename=str(path)))
    if stem in defined or pascal in defined:
        return []
    matching = repr(stem) if pascal == stem else f"{stem!r} or {pascal!r}"
    return [f"{path.relative_to(_SRC)} defines no symbol matching {matching}"]


class TestTheDetectionItself:
    """The rules are only worth having if they fail on the things they're meant to catch."""

    def test_catches_the_violation_the_server_rule_exists_for(self) -> None:
        # Verbatim shape of the import the old custom-field glossary middleware used to carry.
        assert _imports_under(
            "from backstop_mcp.server.tools.registry import TOOLS",
            _SERVER_PREFIX,
        ) == ["backstop_mcp.server.tools.registry"]

    def test_catches_the_violation_the_backstop_client_rule_exists_for(self) -> None:
        # Verbatim shape of the imports `client.py`/`factory.py` used to carry.
        assert _imports_under(
            "from backstop_mcp.features.auth.crypto import BackstopCredentialSecret\n"
            + "from backstop_mcp.features.auth.context import BackstopAuthContext\n",
            _FEATURES_PREFIX,
        ) == ["backstop_mcp.features.auth.crypto", "backstop_mcp.features.auth.context"]

    def test_catches_a_plain_import_too(self) -> None:
        assert _imports_under("import backstop_mcp.server.runtime", _SERVER_PREFIX) == [
            "backstop_mcp.server.runtime"
        ]

    def test_does_not_fire_on_permitted_imports(self) -> None:
        assert not _imports_under(
            "from backstop_mcp.backstop_client.client import BackstopClient\n"
            + "from backstop_mcp.features.custom_fields.service import CustomFieldsService\n"
            + "from backstop_mcp.logging import configure_logging\n",
            _SERVER_PREFIX,
        )

    def test_catches_the_violation_the_config_rule_exists_for(self) -> None:
        # Verbatim shape of the import `client.py`/`factory.py`/`retry.py` used to carry.
        assert _imports_under("from backstop_mcp.config import BackstopConfig", _CONFIG_MODULE) == [
            "backstop_mcp.config"
        ]

    def test_catches_the_violation_the_internals_rule_exists_for(self) -> None:
        # The shape `get_person.py` would carry if it reached past the package front door
        # instead of importing `features.data_hygiene` itself.
        assert _internal_imports(
            "from backstop_mcp.features.data_hygiene.service import DataHygieneService",
            _SRC / "server" / "tools",
        ) == [("backstop_mcp.features.data_hygiene.service", 1)]

    def test_the_same_import_is_fine_inside_the_feature(self) -> None:
        assert not _internal_imports(
            "from backstop_mcp.features.data_hygiene.service import DataHygieneService",
            _package_directory("backstop_mcp.features.data_hygiene"),
        )

    def test_catches_reaching_past_the_init_for_a_service_too(self) -> None:
        """Not only the pure pieces: `service` is behind the front door as well."""
        assert _internal_imports(
            "from backstop_mcp.features.custom_fields.service import CustomFieldsService",
            _SRC / "server",
        ) == [("backstop_mcp.features.custom_fields.service", 1)]

    def test_does_not_fire_on_the_package_root(self) -> None:
        assert not _internal_imports(
            "from backstop_mcp.features.data_hygiene import EmploymentIndexFactory\n"
            + "from backstop_mcp.server.runtime import get_services\n"
            + "from backstop_mcp.features.resolution import Resolved\n",
            _SRC / "server" / "tools",
        )

    def test_does_not_fire_on_a_name_that_merely_starts_with_the_prefix(self) -> None:
        assert not _imports_under("from backstop_mcp.serverless import thing", _SERVER_PREFIX)
        assert not _imports_under("from backstop_mcp.featureset import thing", _FEATURES_PREFIX)
        assert not _imports_under("from backstop_mcp.configuration import thing", _CONFIG_MODULE)

    def test_catches_an_attributes_class_outside_api_responses(self) -> None:
        assert _class_layer_violations(
            "class PartyAttributes: ...\n",
            _FEATURES / "party_resolver" / "internal_dto.py",
        ) == [
            "features/party_resolver/internal_dto.py:1 class PartyAttributes belongs in "
            + "api_responses*"
        ]

    def test_catches_a_dto_class_outside_internal_dto(self) -> None:
        assert _class_layer_violations(
            "class AccountRecordDto: ...\n",
            _FEATURES / "accounts" / "api_responses.py",
        ) == [
            "features/accounts/api_responses.py:1 class AccountRecordDto belongs in internal_dto*"
        ]

    def test_catches_a_response_class_outside_responses(self) -> None:
        assert _class_layer_violations(
            "class AsOfResponse: ...\n",
            _FEATURES / "data_hygiene" / "api_responses.py",
        ) == ["features/data_hygiene/api_responses.py:1 class AsOfResponse belongs in responses*"]

    def test_accepts_a_class_in_its_own_layer_including_a_responses_package(self) -> None:
        assert not _class_layer_violations(
            "class AccountRowResponse: ...\n",
            _FEATURES / "accounts" / "responses" / "shared.py",
        )

    def test_catches_an_upward_layer_import(self) -> None:
        assert _layer_import_violations(
            "from backstop_mcp.features.accounts.responses import AccountRowResponse\n",
            _FEATURES / "accounts" / "internal_dto.py",
        ) == [
            "features/accounts/internal_dto.py:1 imports "
            + "backstop_mcp.features.accounts.responses (upward from internal_dto)"
        ]

    def test_allows_a_downward_layer_import(self) -> None:
        assert not _layer_import_violations(
            "from backstop_mcp.features.accounts.api_responses import AccountAttributes\n",
            _FEATURES / "accounts" / "internal_dto.py",
        )

    def test_does_not_police_non_layer_files_importing_responses(self) -> None:
        assert not _layer_import_violations(
            "from backstop_mcp.features.data_hygiene.responses import AsOfResponse\n",
            _FEATURES / "data_hygiene" / "employment_index.py",
        )

    def test_catches_extra_forbid_on_a_configdict_call(self) -> None:
        assert _extra_forbid_violations(
            'model_config = ConfigDict(extra="forbid")\n',
            _FEATURES / "accounts" / "api_responses.py",
        ) == ['features/accounts/api_responses.py:1 declares extra="forbid"']

    def test_does_not_fire_on_extra_ignore(self) -> None:
        assert not _extra_forbid_violations(
            'model_config = ConfigDict(extra="ignore")\n',
            _FEATURES / "accounts" / "api_responses.py",
        )

    def test_catches_attributes_class_missing_extra_ignore(self) -> None:
        assert _attributes_extra_violations(
            "class PartyAttributes:\n    model_config = ConfigDict(extra='allow')\n",
            _FEATURES / "party_resolver" / "api_responses.py",
        ) == [
            "features/party_resolver/api_responses.py:1 class PartyAttributes declares "
            + "extra='allow', expected \"ignore\""
        ]

    def test_catches_attributes_class_with_no_extra(self) -> None:
        assert _attributes_extra_violations(
            "class PartyAttributes:\n    pass\n",
            _FEATURES / "party_resolver" / "api_responses.py",
        ) == [
            "features/party_resolver/api_responses.py:1 class PartyAttributes declares "
            + 'extra=None, expected "ignore"'
        ]

    def test_accepts_attributes_class_with_extra_ignore(self) -> None:
        assert not _attributes_extra_violations(
            'class PartyAttributes:\n    model_config = ConfigDict(extra="ignore")\n',
            _FEATURES / "party_resolver" / "api_responses.py",
        )

    def test_catches_a_logic_module_named_after_a_mechanism(self) -> None:
        assert _logic_module_name_violations(
            "def something(): ...\n",
            _FEATURES / "accounts" / "fetch.py",
        ) == ["features/accounts/fetch.py defines no symbol matching 'fetch' or 'Fetch'"]

    def test_accepts_a_logic_module_named_after_its_function(self) -> None:
        assert not _logic_module_name_violations(
            "async def fetch_series(): ...\n",
            _FEATURES / "accounts" / "fetch_series.py",
        )

    def test_accepts_a_logic_module_named_after_its_class(self) -> None:
        assert not _logic_module_name_violations(
            "class CustomFieldsService: ...\n",
            _FEATURES / "custom_fields" / "custom_fields_service.py",
        )

    def test_does_not_fire_on_a_vocabulary_module(self) -> None:
        path = _FEATURES / "party_resolver" / "api_responses.py"
        assert not _is_governed_logic_source(path)
        assert not _logic_module_name_violations("class PartyAttributes: ...\n", path)

    def test_does_not_fire_on_a_private_shared_utility(self) -> None:
        path = _FEATURES / "party_resolver" / "_party_search_types.py"
        assert not _is_governed_logic_source(path)
        assert not _logic_module_name_violations("EMAIL_FIELDS = {}\n", path)


class TestFeaturesDoNotImportServer:
    def test_the_feature_tree_is_actually_there(self) -> None:
        """Guards the guard: a moved/renamed tree must not silently vacate the rule below."""
        sources = sorted(_FEATURES.rglob("*.py"))
        assert sources, f"no python sources found under {_FEATURES}"
        packages = {p.relative_to(_FEATURES).parts[0] for p in sources if p.name != "__init__.py"}
        assert {"auth", "custom_fields", "party_resolver"} <= packages

    @pytest.mark.parametrize("source", sorted(_FEATURES.rglob("*.py")), ids=_source_id)
    def test_no_feature_module_imports_from_server(self, source: pathlib.Path) -> None:
        violations = _violations(source, _SERVER_PREFIX)
        assert not violations, (
            "features/ must not import from server/ — the server wires features together, "
            + "not the reverse. Inject the collaborator from create_app() instead:\n  "
            + "\n  ".join(violations)
        )


class TestBackstopClientDoesNotImportFeatures:
    def test_the_client_tree_is_actually_there(self) -> None:
        """Guards the guard, same as above."""
        sources = sorted(_BACKSTOP_CLIENT.rglob("*.py"))
        assert sources, f"no python sources found under {_BACKSTOP_CLIENT}"
        modules = {p.name for p in sources}
        assert {"client.py", "factory.py", "credential.py"} <= modules

    @pytest.mark.parametrize("source", sorted(_BACKSTOP_CLIENT.rglob("*.py")), ids=_source_id)
    def test_no_client_module_imports_from_features(self, source: pathlib.Path) -> None:
        violations = _violations(source, _FEATURES_PREFIX)
        assert not violations, (
            "backstop_client/ must not import from features/ — it is infrastructure features "
            + "consume, and importing one back is a package cycle. Put the shared type in "
            + "backstop_client/credential.py (a Protocol, if features owns the "
            + "implementation):\n  "
            + "\n  ".join(violations)
        )


class TestBackstopClientDoesNotImportConfig:
    def test_the_settings_module_is_actually_there(self) -> None:
        """Guards the guard: without somewhere to put them, the rule below is unsatisfiable."""
        assert (_BACKSTOP_CLIENT / "settings.py").is_file()

    @pytest.mark.parametrize("source", sorted(_BACKSTOP_CLIENT.rglob("*.py")), ids=_source_id)
    def test_no_client_module_imports_config(self, source: pathlib.Path) -> None:
        violations = _violations(source, _CONFIG_MODULE)
        assert not violations, (
            "backstop_client/ must not import config — it takes its own frozen settings types "
            + "from backstop_client/settings.py, which create_app translates BackstopConfig "
            + "into. Add the field to BackstopTransportSettings (or RetrySettings) and map it "
            + "in app.transport_settings instead:\n  "
            + "\n  ".join(violations)
        )


class TestPackagesAreEnteredThroughTheirInit:
    def test_every_listed_package_actually_publishes_something(self) -> None:
        """Guards the guard: a package with no `__all__` has no front door to insist on."""
        for package in _PUBLIC_SURFACE_PACKAGES:
            init = _package_directory(package) / "__init__.py"
            assert init.is_file(), f"no __init__.py for {package}"
            exported = any(
                _declares_dunder_all(node) for node in ast.walk(ast.parse(init.read_text()))
            )
            assert exported, f"{package}/__init__.py declares no __all__"

    def test_a_package_still_composes_its_own_modules(self) -> None:
        """The rule is only meaningful if something inside the package assembles the parts."""
        factory = (
            _package_directory("backstop_mcp.features.data_hygiene") / "employment_index_factory.py"
        )
        imported = {module for module, _line in _imported_modules(ast.parse(factory.read_text()))}

        assert "backstop_mcp.features.data_hygiene.employment_index" in imported

    @pytest.mark.parametrize("source", sorted(_SRC.rglob("*.py")), ids=_source_id)
    def test_no_module_reaches_past_another_packages_init(self, source: pathlib.Path) -> None:
        violations = _internal_module_violations(source)
        assert not violations, (
            "import the package, not a module inside it — a package's __all__ is the whole of "
            + "what it promises, and reaching past it means assembling collaborators the package "
            + "is responsible for assembling (which is how a tool came to re-read "
            + "BackstopConfig() and ignore what create_app was given). Export the name from that "
            + "package's __init__ and import it from there:\n  "
            + "\n  ".join(violations)
        )


class TestFeatureModelLayers:
    def test_the_layer_files_are_actually_there(self) -> None:
        """Guards the guard: a vacated tree must not silently skip the assertions below."""
        sources = _governed_model_layer_sources()
        assert sources, "no api_responses/internal_dto/responses sources found under features/"
        layers = {_model_layer_for_path(source) for source in sources}
        assert layers == set(_MODEL_LAYERS)

    def test_includes_is_exempt(self) -> None:
        includes = _FEATURES / "includes" / "responses.py"
        assert includes.is_file()
        assert not _is_governed_model_source(includes)
        assert not _class_layer_violations(includes.read_text(), includes)

    @pytest.mark.parametrize("source", _governed_model_sources(), ids=_source_id)
    def test_suffixed_classes_live_in_their_layer(self, source: pathlib.Path) -> None:
        violations = _class_layer_violations(source.read_text(), source)
        assert not violations, (
            "a *Attributes class lives in api_responses*, a *Dto class in internal_dto*, "
            + "and a *Response class in responses*:\n  "
            + "\n  ".join(violations)
        )

    @pytest.mark.parametrize("source", _governed_model_layer_sources(), ids=_source_id)
    def test_layer_imports_run_downward(self, source: pathlib.Path) -> None:
        violations = _layer_import_violations(source.read_text(), source)
        assert not violations, (
            "model-layer imports run responses → internal_dto → api_responses, never upward:\n  "
            + "\n  ".join(violations)
        )

    @pytest.mark.parametrize("source", sorted(_SRC.rglob("*.py")), ids=_source_id)
    def test_no_model_declares_extra_forbid(self, source: pathlib.Path) -> None:
        violations = _extra_forbid_violations(source.read_text(), source)
        assert not violations, 'no model may declare extra="forbid":\n  ' + "\n  ".join(violations)

    @pytest.mark.parametrize("source", _governed_model_layer_sources(), ids=_source_id)
    def test_attributes_declare_extra_ignore(self, source: pathlib.Path) -> None:
        violations = _attributes_extra_violations(source.read_text(), source)
        assert not violations, (
            '*Attributes default to extra="ignore"; extra="allow" is only for passthrough '
            + "responses:\n  "
            + "\n  ".join(violations)
        )


class TestLogicModuleNames:
    def test_the_logic_modules_are_actually_there(self) -> None:
        """Guards the guard: a vacated tree must not silently skip the assertion below."""
        sources = _governed_logic_sources()
        assert sources, "no logic modules found"

    @pytest.mark.parametrize("source", _governed_logic_sources(), ids=_source_id)
    def test_logic_module_defines_a_matching_symbol(self, source: pathlib.Path) -> None:
        violations = _logic_module_name_violations(source.read_text(), source)
        assert not violations, (
            "a logic module is named after the function (or class) it exposes, not after a "
            + "mechanism:\n  "
            + "\n  ".join(violations)
        )
