"""The rules a scaffolded MCP keeps. Each check returns what breaks it, empty when it holds."""

import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

from importlinter.api import read_configuration  # pyright: ignore[reportUnknownVariableType]
from importlinter.application.output import console
from importlinter.cli import lint_imports
from pydantic import BaseModel, TypeAdapter
from ruff.__main__ import find_ruff_bin

from mcp_architecture.contracts import CONTRACT_TYPES, required_contracts
from mcp_architecture.service import Service

_FEATURE_FOLDERS = {"commands", "queries"}
# import-linter reads `root_package` back as `root_packages`. `include_external_packages` only
# adds nodes to the graph, for a contract of the service's own about a third-party package. Any
# other session option, such as `exclude_type_checking_imports`, changes what every contract sees.
_SESSION_OPTIONS = {"root_packages", "contract_types", "include_external_packages"}
_RUFF_RULES = ["INP001", "N999", "TID252"]
_CODE_STYLE = Path(__file__).parent / "code_style.toml"
_TYPE_CHECK = Path(__file__).parent / "type_check.json"
# What [tool.basedpyright] may set besides restating type_check.json or making a report stricter.
_SERVICE_TYPE_CHECK_OPTIONS = {"extends", "venv", "venvPath", "pythonVersion"}
_TYPE_CHECKED = ["src", "tests"]
_PYRIGHT_COMMENT = re.compile(r"#\s*pyright:\s*(?P<directive>.*)")


class Rule(BaseModel, frozen=True):
    name: str
    summary: str
    check: Callable[[Service], list[str]]


def _imports_keep_the_contracts(service: Service) -> list[str]:
    with console.capture() as captured:
        exit_code = lint_imports(
            config_filename=str(service.pyproject), no_cache=True, no_logo=True
        )
    return [] if exit_code == 0 else [captured.get()]


def _every_required_contract_is_declared(service: Service) -> list[str]:
    configuration = cast(dict[str, object], read_configuration(str(service.pyproject)))
    session = cast(dict[str, object], configuration["session_options"])
    declared_types = cast(list[str], session.get("contract_types", []))
    contracts = cast(list[dict[str, object]], configuration["contracts_options"])
    declared = {str(contract["name"]): contract for contract in contracts}
    required = required_contracts(service.package)
    required_types = {str(contract["type"]) for contract in required}
    problems = [
        *(
            f"[tool.importlinter] may not set {option}"
            for option in sorted(session.keys() - _SESSION_OPTIONS)
        ),
        *(
            f"contract_types lacks {kind!r}"
            for kind in CONTRACT_TYPES
            if kind not in declared_types
        ),
        *(
            f"contract_types may not redefine a type the required contracts use: {kind!r}"
            for kind in declared_types
            if kind not in CONTRACT_TYPES and kind.split(":")[0].strip() in required_types
        ),
    ]
    for contract in map(_as_read_back, required):
        name = str(contract["name"])
        actual = declared.get(name)
        if actual is None:
            problems.append(f"{name!r} is missing")
        elif actual != contract:
            problems.append(f"{name!r} was changed to {actual}; it must be {contract}")
    return problems


def _as_read_back(contract: dict[str, object]) -> dict[str, object]:
    """import-linter reads a TOML boolean back as the string `True` or `False`."""
    return {
        key: str(value) if isinstance(value, bool) else value for key, value in contract.items()
    }


def _package_keeps_the_ruff_rules_the_architecture_relies_on(service: Service) -> list[str]:
    """Runs ruff with the service's own configuration and `noqa` comments ignored, so neither
    can turn these rules off."""
    return _ruff(
        service,
        "--isolated",
        "--ignore-noqa",
        f"--select={','.join(_RUFF_RULES)}",
        '--config=lint.flake8-tidy-imports.ban-relative-imports="all"',
        str(service.source.relative_to(service.root)),
    )


def _code_keeps_the_style(service: Service) -> list[str]:
    """Runs ruff with the code style every MCP shares, so the service's own [tool.ruff] cannot
    loosen it. A `noqa` naming its rule still can, as Google's guide allows. The code generated
    from a vendor's spec keeps the vendor's names, so it is left out."""
    files = [path for path in _python_files(service) if path not in service.generated]
    return _ruff(
        service,
        f"--config={_CODE_STYLE}",
        f"--config=lint.isort.known-first-party=[{service.package!r}]",
        f"--target-version=py{sys.version_info.major}{sys.version_info.minor}",
        *sorted(str(path.relative_to(service.root)) for path in files),
    )


def _type_check_keeps_the_strictness(service: Service) -> list[str]:
    """basedpyright lets a key in [tool.basedpyright] override the config it extends, a
    pyrightconfig.json replace that table altogether, and a `# pyright:` comment change the check
    of one file. So the table may only set what is the service's own, restate the shared config
    or make a report stricter, and a comment may only ignore a named rule on its line."""
    shared = cast(dict[str, object], json.loads(_TYPE_CHECK.read_text()))
    table = service.type_check
    extends = table.get("extends")
    extended = service.root / extends if isinstance(extends, str) else None
    problems: list[str] = []
    if (service.root / "pyrightconfig.json").is_file():
        problems.append("pyrightconfig.json replaces [tool.basedpyright]; remove it")
    if extended is None or not extended.is_file() or json.loads(extended.read_text()) != shared:
        problems.append(f"[tool.basedpyright] must extend mcp-architecture's {_TYPE_CHECK.name}")
    problems.extend(
        f"[tool.basedpyright] may not set {key} = {value!r}"
        for key, value in table.items()
        if not _keeps_the_type_check(key=key, value=value, shared=shared)
    )
    problems.extend(
        f"{path.relative_to(service.root)}:{line}: a `# pyright:` comment may only be "
        f"`ignore[rule]`, not `{directive}`"
        for path in _python_files(service)
        for line, directive in _pyright_directives(path)
        if not directive.startswith("ignore[")
    )
    return problems


def _features_are_packages(service: Service) -> list[str]:
    return [
        *(
            f"{feature.name} needs an __init__.py"
            for feature in _folders(service.contexts)
            if not (feature / "__init__.py").is_file()
        ),
        *(
            f"contexts/{path.name} belongs in a feature"
            for path in sorted(service.contexts.glob("*"))
            if path.is_file() and path.name != "__init__.py"
        ),
    ]


def _features_hold_only_commands_and_queries(service: Service) -> list[str]:
    return [
        *(
            f"{feature.name} may only have {sorted(_FEATURE_FOLDERS)} folders, not {folder.name}"
            for feature in _folders(service.contexts)
            for folder in _folders(feature)
            if folder.name not in _FEATURE_FOLDERS
        ),
        *(
            f"{operation.relative_to(service.contexts)} nests {nested.name}"
            for feature in _folders(service.contexts)
            for kind in _folders(feature)
            for operation in _folders(kind)
            for nested in _folders(operation)
        ),
    ]


def _tool_folders_do_not_nest(service: Service) -> list[str]:
    return [
        f"tools/{tool.name} nests {nested.name}"
        for tool in _folders(service.tools)
        for nested in _folders(tool)
    ]


def _feature_inits_only_re_export(service: Service) -> list[str]:
    """The command/query contract resolves a name taken from a feature's top level to the module
    it is re-exported from. A name defined in the `__init__.py` itself would hide what it uses."""
    return [
        f"{feature.name}/__init__.py:{node.lineno}: define it in a command, a query or a model "
        "module, and re-export it here"
        for feature in _folders(service.contexts)
        if (feature / "__init__.py").is_file()
        for node in ast.parse((feature / "__init__.py").read_text()).body
        if not _is_re_export(node)
    ]


def _context_modules_lead_with_one_public_function(service: Service) -> list[str]:
    problems: list[str] = []
    for module in _context_modules(service):
        body = ast.parse(module.read_text()).body
        definitions = [
            node.name
            for node in body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        ]
        public = [node.name for node in _functions(body) if not node.name.startswith("_")]
        constants = [
            target.id
            for node in body
            if isinstance(node, ast.Assign | ast.AnnAssign)
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name) and not target.id.startswith("_")
        ]
        name = module.relative_to(service.contexts)
        if len(public) > 1:
            problems.append(f"{name}: keep one public function, make the others private: {public}")
        if public and definitions[0] != public[0]:
            problems.append(f"{name}: define {public[0]} first")
        if constants:
            problems.append(f"{name}: make module constants private: {constants}")
    return problems


def _context_functions_take_keyword_arguments_only(service: Service) -> list[str]:
    return [
        f"{module.relative_to(service.contexts)}: put a bare * before the parameters of "
        f"{function.name}"
        for module in _context_modules(service)
        for function in _functions(ast.parse(module.read_text()).body)
        if function.args.posonlyargs or function.args.args or function.args.vararg
    ]


class _Location(BaseModel):
    row: int
    column: int


class _Diagnostic(BaseModel):
    filename: Path
    location: _Location
    code: str | None
    message: str


_DIAGNOSTICS = TypeAdapter(list[_Diagnostic])


def _ruff(service: Service, *arguments: str) -> list[str]:
    """JSON output carries no colour, whatever FORCE_COLOR says."""
    result = subprocess.run(
        [find_ruff_bin(), "check", "--no-cache", "--quiet", "--output-format=json", *arguments],
        cwd=service.root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), f"ruff failed: {result.stderr}"
    return [
        f"{diagnostic.filename.relative_to(service.root)}:{diagnostic.location.row}:"
        f"{diagnostic.location.column}: {diagnostic.code} {diagnostic.message}"
        for diagnostic in _DIAGNOSTICS.validate_json(result.stdout or "[]")
    ]


def _keeps_the_type_check(*, key: str, value: object, shared: dict[str, object]) -> bool:
    if key == "include":
        return value == _TYPE_CHECKED
    return (
        key in _SERVICE_TYPE_CHECK_OPTIONS
        or value == shared.get(key)
        or (key.startswith("report") and value in (True, "error"))
    )


def _python_files(service: Service) -> list[Path]:
    return sorted(
        path
        for folder in (service.source, service.root / "tests")
        for path in folder.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _pyright_directives(path: Path) -> Iterator[tuple[int, str]]:
    tokens = tokenize.generate_tokens(io.StringIO(path.read_text()).readline)
    for token in tokens:
        match = _PYRIGHT_COMMENT.match(token.string) if token.type == tokenize.COMMENT else None
        if match:
            yield token.start[0], match["directive"].strip()


def _folders(parent: Path) -> Iterator[Path]:
    if not parent.is_dir():
        return iter(())
    return (
        path for path in sorted(parent.iterdir()) if path.is_dir() and path.name != "__pycache__"
    )


def _context_modules(service: Service) -> list[Path]:
    return sorted(
        path
        for path in service.contexts.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    )


def _functions(body: list[ast.stmt]) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]


def _is_re_export(node: ast.stmt) -> bool:
    is_docstring = isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    targets = (
        node.targets
        if isinstance(node, ast.Assign)
        else [node.target]
        if isinstance(node, ast.AnnAssign)
        else []
    )
    is_all = [target.id for target in targets if isinstance(target, ast.Name)] == ["__all__"]
    return isinstance(node, ast.ImportFrom) or is_docstring or is_all


RULES = [
    Rule(
        name="import-contracts",
        summary="Imports keep the contracts under [tool.importlinter]. Move the code to the layer "
        "it belongs in; never loosen a contract.",
        check=_imports_keep_the_contracts,
    ),
    Rule(
        name="required-contracts",
        summary="[tool.importlinter] declares every contract the architecture requires, as it "
        "is, and no option that loosens them.",
        check=_every_required_contract_is_declared,
    ),
    Rule(
        name="required-lint",
        summary="The package keeps the ruff rules the architecture relies on, whatever "
        "[tool.ruff] or a noqa says: INP001, since import-linter does not see a folder without "
        "an __init__.py; N999, since a module name is snake_case; and TID252 with "
        'ban-relative-imports = "all", since the contracts follow absolute imports only.',
        check=_package_keeps_the_ruff_rules_the_architecture_relies_on,
    ),
    Rule(
        name="code-style",
        summary="The code keeps the style in mcp-architecture's code_style.toml, the Google Python "
        "Style Guide as far as ruff checks it, whatever [tool.ruff] says. `uv run ruff check "
        "--fix` fixes most of it.",
        check=_code_keeps_the_style,
    ),
    Rule(
        name="type-check",
        summary="[tool.basedpyright] extends mcp-architecture's type_check.json, basedpyright's "
        "`all` mode. Besides extends, venv, venvPath, pythonVersion and include = "
        '["src", "tests"], it only restates the shared config or makes a report stricter. A '
        "`# pyright:` comment only ignores a named rule on its line.",
        check=_type_check_keeps_the_strictness,
    ),
    Rule(
        name="feature-packages",
        summary="Each folder in contexts/ is a feature, a package with an __init__.py, and "
        "contexts/ holds no module of its own besides its __init__.py.",
        check=_features_are_packages,
    ),
    Rule(
        name="feature-folders",
        summary="A feature holds only commands/ and queries/, with at most one folder per "
        "command or query.",
        check=_features_hold_only_commands_and_queries,
    ),
    Rule(
        name="feature-inits",
        summary="A feature's __init__.py only re-exports: imports, __all__ and a docstring.",
        check=_feature_inits_only_re_export,
    ),
    Rule(
        name="tool-folders", summary="A tool folder does not nest.", check=_tool_folders_do_not_nest
    ),
    Rule(
        name="one-public-function",
        summary="A context module has at most one public function, defined first, and only "
        "private constants.",
        check=_context_modules_lead_with_one_public_function,
    ),
    Rule(
        name="keyword-only",
        summary="A context function takes keyword arguments only.",
        check=_context_functions_take_keyword_arguments_only,
    ),
]
