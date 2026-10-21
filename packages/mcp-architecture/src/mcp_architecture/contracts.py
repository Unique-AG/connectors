"""The import contracts every scaffolded MCP declares in `[tool.importlinter]`."""

import json
import tomllib
from itertools import pairwise
from typing import cast

_CONTRACT_TYPES = ["feature_privacy: mcp_architecture.feature_privacy.FeaturePrivacyContract"]
_LAYERS = ["main", "mcp", "contexts", "upstream | persistence", "utils", "telemetry"]
_IMPORTED_THROUGH_TOP_LEVEL = ["mcp", "contexts", "upstream", "persistence", "utils", "telemetry"]
_TABLE = "[tool.importlinter]"
_CONTRACT = "[[tool.importlinter.contracts]]"


def render_importlinter(package: str) -> str:
    """`[tool.importlinter]` with the contracts every MCP keeps, as the scaffold writes it. A JSON
    string, list or boolean is valid TOML as it is."""
    return _render(package, _CONTRACT_TYPES)


def restore_importlinter(pyproject: str, package: str) -> str:
    """`pyproject` with its `[tool.importlinter]` as `render_importlinter` writes it, followed by
    the contracts and contract types of the MCP's own, kept as they are written."""
    lines = pyproject.splitlines(keepends=True)
    start = next((index for index, line in enumerate(lines) if line.rstrip() == _TABLE), None)
    if start is None:
        return f"{pyproject.rstrip()}\n\n{render_importlinter(package)}"
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("[")
            and not lines[index].startswith(("[tool.importlinter", "[[tool.importlinter"))
        ),
        len(lines),
    )
    # Blank lines and comments right above the next table belong to it.
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
        end -= 1
    block = lines[start:end]
    written = cast(dict[str, dict[str, dict[str, object]]], tomllib.loads("".join(block)))
    types = cast(list[str], written["tool"]["importlinter"].get("contract_types", []))
    shared = {str(contract["name"]) for contract in _contracts(package)}
    _, *contracts = _split_contracts(block)
    own = "".join(
        f"\n{contract.strip('\n')}\n"
        for contract in contracts
        if _contract_name(contract) not in shared
    )
    tail = "".join(lines[end:]).lstrip("\n")
    return (
        "".join(lines[:start])
        + _render(package, [*_CONTRACT_TYPES, *(t for t in types if t not in _CONTRACT_TYPES)])
        + own
        + (f"\n{tail}" if tail else "")
    )


def _split_contracts(lines: list[str]) -> list[str]:
    """The table's own options, then each contract with the comments right above it."""
    starts = [
        next(
            above
            for above in range(index, -1, -1)
            if above == 0 or not lines[above - 1].startswith("#")
        )
        for index, line in enumerate(lines)
        if line.rstrip() == _CONTRACT
    ]
    return ["".join(lines[a:b]) for a, b in pairwise([0, *starts, len(lines)])]


def _contract_name(contract: str) -> str:
    parsed = cast(
        dict[str, list[dict[str, object]]],
        tomllib.loads(contract.replace(_CONTRACT, "[[contract]]", 1)),
    )
    return str(parsed["contract"][0].get("name"))


def _render(package: str, contract_types: list[str]) -> str:
    types = "".join(f"    {json.dumps(kind)},\n" for kind in contract_types)
    contracts = "".join(
        f"\n{_CONTRACT}\n"
        + "".join(f"{key} = {json.dumps(value)}\n" for key, value in contract.items())
        for contract in _contracts(package)
    )
    return (
        f"{_TABLE}\nroot_package = {json.dumps(package)}\n"
        # Puts fastmcp and mcp in the graph, for the contract that keeps them out of the domain.
        "include_external_packages = true\n"
        f"contract_types = [\n{types}]\n{contracts}"
    )


def _contracts(package: str) -> list[dict[str, object]]:
    contexts = f"{package}.contexts"
    return [
        {
            "name": "Layers only import downwards",
            "type": "layers",
            "containers": [package],
            "layers": _LAYERS,
            "exhaustive": True,
        },
        *(
            {
                "name": f"{layer} is imported through its top level only",
                "type": "protected",
                "protected_modules": [f"{package}.{layer}.*"],
                "allowed_importers": [f"{package}.{layer}"],
            }
            for layer in _IMPORTED_THROUGH_TOP_LEVEL
        ),
        {
            "name": "A context feature is imported through its top level only",
            "type": "feature_privacy",
            "container": contexts,
        },
        {
            "name": "No package imports its siblings in a cycle",
            "type": "acyclic_siblings",
            "ancestors": [package],
        },
        {
            # Indirect imports are allowed: contexts reach fastmcp through upstream, whose
            # UpstreamError is a ToolError.
            "name": "The domain and the storage know nothing about MCP",
            "type": "forbidden",
            "source_modules": [contexts, f"{package}.persistence"],
            "forbidden_modules": ["fastmcp", "mcp", "mcp_types"],
            "allow_indirect_imports": True,
        },
    ]
