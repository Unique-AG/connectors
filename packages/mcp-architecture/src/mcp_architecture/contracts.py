"""The import contracts every scaffolded MCP keeps, which the scaffold writes to its
`[tool.importlinter]`."""

import json

_CONTRACT_TYPES = ["feature_privacy: mcp_architecture.feature_privacy.FeaturePrivacyContract"]
_LAYERS = ["main", "mcp", "contexts", "upstream | persistence", "shared", "telemetry"]
_IMPORTED_THROUGH_TOP_LEVEL = ["mcp", "contexts", "upstream", "persistence", "shared", "telemetry"]
# A contract between layers is types alone: what implements it lives in a layer above.
_CONTRACTS_IMPORT_NOTHING_OF = ["sqlalchemy", "httpx2", "cryptography"]


def render_importlinter(package: str) -> str:
    """`[tool.importlinter]` with the contracts every MCP keeps, as TOML. A JSON string, list or
    boolean is valid TOML as it is."""
    types = "".join(f"    {json.dumps(kind)},\n" for kind in _CONTRACT_TYPES)
    contracts = "".join(
        "\n[[tool.importlinter.contracts]]\n"
        + "".join(f"{key} = {json.dumps(value)}\n" for key, value in contract.items())
        for contract in _contracts(package)
    )
    return (
        f"[tool.importlinter]\nroot_package = {json.dumps(package)}\n"
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
            "name": "The domain, the storage and shared know nothing about MCP",
            "type": "forbidden",
            "source_modules": [contexts, f"{package}.persistence", f"{package}.shared"],
            "forbidden_modules": ["fastmcp", "mcp", "mcp_types"],
            "allow_indirect_imports": True,
        },
        {
            "name": "The contracts in shared are types, not implementations",
            "type": "forbidden",
            "source_modules": [f"{package}.shared.contracts"],
            "forbidden_modules": _CONTRACTS_IMPORT_NOTHING_OF,
        },
    ]
