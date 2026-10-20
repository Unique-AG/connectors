"""The rules a scaffolded MCP keeps. Each check returns what breaks it, empty when it holds."""

import ast
import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

from importlinter.api import read_configuration  # pyright: ignore[reportUnknownVariableType]
from importlinter.application.output import console
from importlinter.cli import lint_imports
from pydantic import BaseModel
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
# Besides a report's severity, what loosens the type check of the whole service.
_LOOSENING_OPTIONS = {"typeCheckingMode", "ignore"}


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
    for contract in required:
        name = str(contract["name"])
        actual = declared.get(name)
        if actual is None:
            problems.append(f"{name!r} is missing")
        elif actual != contract:
            problems.append(f"{name!r} was changed to {actual}; it must be {contract}")
    return problems


def _package_keeps_the_ruff_rules_the_architecture_relies_on(service: Service) -> list[str]:
    """Runs ruff with the service's own configuration and `noqa` comments ignored, so neither
    can turn these rules off."""
    result = subprocess.run(
        [
            find_ruff_bin(),
            "check",
            "--isolated",
            "--ignore-noqa",
            "--no-cache",
            "--quiet",
            "--output-format=concise",
            f"--select={','.join(_RUFF_RULES)}",
            '--config=lint.flake8-tidy-imports.ban-relative-imports="all"',
            str(service.source.relative_to(service.root)),
        ],
        cwd=service.root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), f"ruff failed: {result.stderr}"
    return result.stdout.splitlines()


def _code_keeps_the_style(service: Service) -> list[str]:
    """Runs ruff with the code style every MCP shares, so the service's own [tool.ruff] cannot
    loosen it. A `noqa` with a reason beside it still can, as Google's guide allows. The code
    generated from a vendor's spec keeps the vendor's names, so it is left out."""
    files = [
        path
        for folder in (service.source, service.root / "tests")
        for path in folder.rglob("*.py")
        if path not in service.generated
    ]
    result = subprocess.run(
        [
            find_ruff_bin(),
            "check",
            f"--config={_CODE_STYLE}",
            f"--config=lint.isort.known-first-party=[{service.package!r}]",
            f"--target-version=py{sys.version_info.major}{sys.version_info.minor}",
            "--no-cache",
            "--quiet",
            "--output-format=concise",
            *sorted(str(path.relative_to(service.root)) for path in files),
        ],
        cwd=service.root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), f"ruff failed: {result.stderr}"
    return result.stdout.splitlines()


def _type_check_keeps_the_strictness(service: Service) -> list[str]:
    """basedpyright lets a key in [tool.basedpyright] override the config it extends, and a
    pyrightconfig.json replaces that table altogether. So a report may only be made stricter, or
    restated as the shared config has it."""
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
        if value != shared.get(key)
        and (
            key in _LOOSENING_OPTIONS or (key.startswith("report") and value not in (True, "error"))
        )
    )
    return problems


def _features_are_packages(service: Service) -> list[str]:
    return [
        f"{feature.name} needs an __init__.py"
        for feature in _folders(service.contexts)
        if not (feature / "__init__.py").is_file()
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
    is_all = isinstance(node, ast.Assign) and [
        target.id for target in node.targets if isinstance(target, ast.Name)
    ] == ["__all__"]
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
        "`all` mode, and turns no report down, whatever it sets.",
        check=_type_check_keeps_the_strictness,
    ),
    Rule(
        name="feature-packages",
        summary="Each folder in contexts/ is a feature, a package with an __init__.py.",
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
