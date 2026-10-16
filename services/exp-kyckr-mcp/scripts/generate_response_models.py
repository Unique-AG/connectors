"""Generate the response models and `Operation` constants from the vendored spec."""

from pathlib import Path

from mcp_openapi.codegen import generate_operations, generate_response_models

from kyckr_mcp.openapi.routes import CLIENT_BACKED

PACKAGE = Path(__file__).resolve().parents[1] / "src/kyckr_mcp"
SPEC = PACKAGE / "openapi/kyckr-openapi.yml"
# Download links stay out of the schema. The tools remove them from the answer.
FIELDS = {
    "OrderDetails": (
        "orderId",
        "orderDate",
        "customerReference",
        "status",
        "cost",
        "user",
        "productDetails",
        "companyDetails",
    )
}

generate_response_models(
    spec_path=SPEC,
    operation_ids=CLIENT_BACKED,
    fields=FIELDS,
    allow_extra_fields=True,
    output=PACKAGE / "models/vendor_responses.py",
)
generate_operations(
    spec_path=SPEC,
    operation_ids=CLIENT_BACKED,
    operation_module="mcp_openapi.upstream",
    models_module="kyckr_mcp.models.vendor_responses",
    output=PACKAGE / "models/operations.py",
)
