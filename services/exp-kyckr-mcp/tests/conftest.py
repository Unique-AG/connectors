import pytest
from pydantic import SecretStr

from kyckr_mcp.settings import Settings


def response_schema() -> dict[str, object]:
    return {
        "200": {
            "description": "OK",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    }


def operation(
    operation_id: str,
    method: str,
    parameters: list[dict[str, object]] | None = None,
    request_body: dict[str, object] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "operationId": operation_id,
        "summary": operation_id,
        "responses": response_schema(),
    }
    if parameters:
        result["parameters"] = parameters
    if request_body:
        result["requestBody"] = request_body
    return {method: result}


def parameter(name: str, location: str, required: bool = False) -> dict[str, object]:
    return {
        "name": name,
        "in": location,
        "required": required,
        "schema": {"type": "string"},
    }


def request_body(properties: list[str]) -> dict[str, object]:
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {name: {"type": "string"} for name in properties},
                }
            }
        },
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(
        mcp_api_key=SecretStr("test-mcp-key"),
        kyckr_api_key=SecretStr("test-kyckr-key"),
        _env_file=None,
    )


@pytest.fixture
def spec() -> dict[str, object]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Kyckr", "version": "2.0"},
        "paths": {
            "/companies": operation(
                "get-companies",
                "get",
                [
                    parameter("isoCode", "query"),
                    parameter("name", "query"),
                    parameter("companyNumber", "query"),
                ],
            ),
            "/companies/{kyckrId}/lite": operation(
                "get-companies-kyckrId",
                "get",
                [parameter("kyckrId", "path", True), parameter("customerReference", "query")],
            ),
            "/companies/{kyckrId}/enhanced": operation(
                "get-companies-kyckrId-enhanced",
                "get",
                [
                    parameter("kyckrId", "path", True),
                    parameter("showDirectorships", "query"),
                    parameter("customerReference", "query"),
                    parameter("extend", "query"),
                ],
            ),
            "/companies/{kyckrId}/documents": operation(
                "get-companies-kyckrId-documents",
                "get",
                [
                    parameter("kyckrId", "path", True),
                    parameter("continuationKey", "query"),
                    parameter("customerReference", "query"),
                ],
            ),
            "/orders": {
                **operation(
                    "get-order",
                    "get",
                    [
                        parameter("startDate", "query"),
                        parameter("endDate", "query"),
                        parameter("isoCode", "query"),
                    ],
                ),
                **operation(
                    "post-orders",
                    "post",
                    request_body=request_body(
                        ["kyckrId", "productId", "customerReference", "contactEmail"]
                    ),
                ),
            },
            "/orders/{orderId}": operation(
                "get-orders-orderId",
                "get",
                [parameter("orderId", "path", True)],
            ),
            "/orders/{orderId}/download": operation(
                "get-orders-orderId-download",
                "get",
                [parameter("orderId", "path", True), parameter("format", "query", True)],
            ),
        },
    }
