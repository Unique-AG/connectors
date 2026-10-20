"""The import contracts every scaffolded MCP declares in `[tool.importlinter]`, as import-linter
reads them back."""

import json

CONTRACT_TYPES = [
    "feature_privacy: mcp_architecture.feature_privacy.FeaturePrivacyContract",
    "command_query_separation: "
    "mcp_architecture.command_query_separation.CommandQuerySeparationContract",
]
LAYERS = ["main", "mcp", "contexts", "upstream | persistence", "telemetry"]
_IMPORTED_THROUGH_TOP_LEVEL = ["mcp", "upstream", "persistence", "telemetry"]


def required_contracts(package: str) -> list[dict[str, object]]:
    contexts = f"{package}.contexts"
    return [
        {
            "name": "Layers only import downwards",
            "type": "layers",
            "containers": [package],
            "layers": LAYERS,
            "exhaustive": True,
        },
        {
            "name": "Context features do not import each other in a cycle",
            "type": "acyclic_siblings",
            "ancestors": [contexts],
            "depth": 0,
        },
        {
            "name": "A context feature is imported through its top level only",
            "type": "feature_privacy",
            "container": contexts,
        },
        {
            "name": "A query never imports a command",
            "type": "command_query_separation",
            "container": contexts,
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
    ]


def render_importlinter(package: str) -> str:
    """`[tool.importlinter]` with the required contracts, as the scaffold writes it. A JSON
    string, list or integer is valid TOML as it is."""
    types = "".join(f"    {json.dumps(kind)},\n" for kind in CONTRACT_TYPES)
    contracts = "".join(
        "\n[[tool.importlinter.contracts]]\n"
        + "".join(f"{key} = {json.dumps(value)}\n" for key, value in contract.items())
        for contract in required_contracts(package)
    )
    return (
        f"[tool.importlinter]\nroot_package = {json.dumps(package)}\n"
        f"contract_types = [\n{types}]\n{contracts}"
    )
