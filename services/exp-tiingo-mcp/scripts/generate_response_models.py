"""Generate response models for every operation the server uses, and an `Operation` constant for
each one the tools call through `OperationClient`, from the vendored spec.

Run from the project root: `uv run scripts/generate_response_models.py`.
"""

from pathlib import Path

from tiingo_mcp.helpers.codegen import generate_operations, generate_response_models
from tiingo_mcp.openapi.routes import CLIENT_BACKED, RESPONSE_MODELS

PACKAGE = Path(__file__).resolve().parents[1] / "src/tiingo_mcp"
# Fields a tool returns for a model; the rest is pruned from the spec before codegen.
FIELDS = {"DailyPriceBar": ("date", "open", "high", "low", "close", "volume", "adjClose")}

generate_response_models(
    spec_path=PACKAGE / "openapi/tiingo-openapi.yml",
    operation_ids=RESPONSE_MODELS,
    fields=FIELDS,
    output=PACKAGE / "models/vendor_responses.py",
)
generate_operations(
    spec_path=PACKAGE / "openapi/tiingo-openapi.yml",
    operation_ids=CLIENT_BACKED,
    operation_module="tiingo_mcp.helpers.upstream",
    models_module="tiingo_mcp.models.vendor_responses",
    output=PACKAGE / "models/operations.py",
)
