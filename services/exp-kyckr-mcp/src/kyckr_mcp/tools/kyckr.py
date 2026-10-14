import re
from collections.abc import Callable, Mapping
from typing import cast

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool

from kyckr_mcp.client import KyckrApiError
from kyckr_mcp.openapi.routes import MCP_NAMES
from kyckr_mcp.settings import Settings
from kyckr_mcp.tools.wrap import (
    JsonObject,
    error_response,
    forward_payload,
    forward_response,
    payload,
    success_response,
    wrap_tool,
)

PDF_NOT_SUPPORTED_DETAIL = (
    "This document is only available as a PDF. PDF delivery is not yet supported; "
    "support is coming soon."
)


def required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ToolError(f"{field} must not be empty")
    return normalized


def optional_iso_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", normalized):
        raise ToolError("iso_code must be a 2-letter ISO 3166 alpha-2 code")
    return normalized


def optional_argument(arguments: Mapping[str, object], key: str, value: str | None) -> JsonObject:
    return {**arguments, key: value} if value is not None else dict(arguments)


def mapping(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, Mapping) else None


def order_data(response: JsonObject) -> dict[str, object] | None:
    data = mapping(response.get("data"))
    if data is not None:
        return data
    envelope_fields = {
        "success",
        "statusCode",
        "message",
        "correlationId",
        "customerReference",
        "timeStamp",
        "details",
    }
    top_level_data = {key: value for key, value in response.items() if key not in envelope_fields}
    return top_level_data if "status" in top_level_data or "orderId" in top_level_data else None


def strip_links(value: object) -> object:
    data = mapping(value)
    return (
        {key: item for key, item in data.items() if key != "links"} if data is not None else value
    )


def with_document(
    response: JsonObject,
    data: dict[str, object],
    document_json: object | None,
    detail: str | None,
) -> JsonObject:
    updated_data = {**cast(dict[str, object], strip_links(data))}
    if document_json is not None:
        updated_data["documentJson"] = document_json
    existing = response.get("details")
    details = " ".join(part for part in (existing, detail) if isinstance(part, str) and part)
    result: JsonObject = {**response, "data": updated_data}
    if details:
        result["details"] = details
    else:
        result.pop("details", None)
    return result


async def fetch_document_json(
    download_tool: Tool, order_id: str
) -> tuple[object | None, str | None]:
    try:
        result = await download_tool.run({"orderId": order_id, "format": "json"})
    except KyckrApiError as exc:
        if exc.status == 404:
            return None, PDF_NOT_SUPPORTED_DETAIL
        raise

    result_data = mapping(payload(result))
    if result_data is None:
        return None, PDF_NOT_SUPPORTED_DETAIL
    document = result_data.get("Data", result_data.get("data"))
    return (document, None) if document is not None else (None, PDF_NOT_SUPPORTED_DETAIL)


def build_search_companies() -> Callable[..., object]:
    async def search_companies(
        name: str | None = None,
        company_number: str | None = None,
        iso_code: str | None = None,
    ) -> JsonObject:
        """
        Search the Kyckr company registry by name or registration number. Either `name` or
        `company_number` must be provided. Pass `iso_code` (ISO 3166 alpha-2, e.g. 'GB', 'AU') to
        search a specific jurisdiction directly. Without `iso_code`, Kyckr performs a global search
        over stored data; once you locate the right jurisdiction, repeat the search with that
        `iso_code` to confirm the entity is currently active. The returned `id` is the Kyckr id
        required by every other tool, passed as `kyckr_id`, and is the starting point for
        `list_company_documents`. Free to call.
        """
        normalized_name = name.strip() if name else None
        normalized_number = company_number.strip() if company_number else None
        if not normalized_name and not normalized_number:
            raise ToolError("Provide either `name` or `company_number`.")
        arguments: JsonObject = {}
        if normalized_name:
            arguments["name"] = normalized_name
        if normalized_number:
            arguments["companyNumber"] = normalized_number
        normalized_iso_code = optional_iso_code(iso_code)
        if normalized_iso_code:
            arguments["isoCode"] = normalized_iso_code
        return await forward_response(arguments)

    return search_companies


def build_lite_profile(settings: Settings) -> Callable[..., object]:
    async def get_lite_profile(kyckr_id: str) -> JsonObject:
        """
        Fetch a paid Lite company profile using a confirmed `kyckr_id`. Returns basic verified
        registry details: company name, registration number, registered address, registration and
        foundation dates, legal form, legal status, activities, and registration authority.
        Consumes credits. Does not return directors, shareholders, or beneficial owners; use
        `get_enhanced_profile` for those. For orderable filings, see `list_company_documents`.
        """
        arguments = {"kyckrId": required_text(kyckr_id, "kyckr_id")}
        return await forward_response(
            optional_argument(
                arguments, "customerReference", settings.kyckr_default_customer_reference
            )
        )

    return get_lite_profile


def build_enhanced_profile(settings: Settings) -> Callable[..., object]:
    async def get_enhanced_profile(kyckr_id: str) -> JsonObject:
        """
        Fetch a paid Enhanced company profile using a confirmed `kyckr_id`. Returns everything in
        `get_lite_profile` plus representatives, ultimate beneficial owners, share capital, contact
        details, and activity declarations. Use only when ownership or representative data is
        needed; `get_lite_profile` is cheaper for basic identification. A `statusCode: 405`
        response means the enhanced profile is not available for that jurisdiction; tell the user
        and do not substitute `create_document_order`, which orders registry filings, not profile
        data.
        """
        arguments = {"kyckrId": required_text(kyckr_id, "kyckr_id")}
        return await forward_response(
            optional_argument(
                arguments, "customerReference", settings.kyckr_default_customer_reference
            )
        )

    return get_enhanced_profile


def build_company_documents(settings: Settings) -> Callable[..., object]:
    async def list_company_documents(
        kyckr_id: str,
        continuation_key: str | None = None,
    ) -> JsonObject:
        """
        List official registry documents available to order for a company. The listing is free;
        only `create_document_order` consumes credits. Each entry includes a product `id` (use as
        `product_id` when ordering), `name`, `category`, `documentDate`, expected
        `deliveryTimeMinutes`, and the credit `cost` of ordering. Paginate with `continuation_key`
        when the response includes one.
        """
        arguments: JsonObject = {"kyckrId": required_text(kyckr_id, "kyckr_id")}
        if continuation_key:
            arguments["continuationKey"] = continuation_key.strip()
        arguments = optional_argument(
            arguments, "customerReference", settings.kyckr_default_customer_reference
        )
        return await forward_response(arguments)

    return list_company_documents


def build_document_order(settings: Settings, download_tool: Tool) -> Callable[..., object]:
    async def create_document_order(kyckr_id: str, product_id: str) -> JsonObject:
        """
        Place a paid Kyckr order for an official registry document. Every successful call
        spends credits and creates a real registry order; it is the only write-side tool.
        Required: `kyckr_id` (from `search_companies`) and `product_id` (from
        `list_company_documents`). Call directly once the user has named or chosen a
        specific filing; do not ask for a separate confirmation, the cost is already known.
        Returns `data.orderId` and `data.status`. On `status: "Success"` the JSON view of
        the document is inlined under `data.documentJson`; render it to the user as a
        readable summary. If `data.documentJson` is absent, `details` says the document is
        PDF-only and PDF delivery is not yet supported; relay that message. On `status:
        "Pending"`, poll `get_order(data.orderId)` until `data.documentJson` is populated or
        `status` is `Failed`. Never mention download URLs.
        """
        arguments = {
            "kyckrId": required_text(kyckr_id, "kyckr_id"),
            "productId": required_text(product_id, "product_id"),
        }
        arguments = optional_argument(
            arguments, "customerReference", settings.kyckr_default_customer_reference
        )
        arguments = optional_argument(
            arguments, "contactEmail", settings.kyckr_default_contact_email
        )
        try:
            response = success_response(await forward_payload(arguments))
            data = order_data(response)
            if data is None:
                return response
            if data.get("status") != "Success" or data.get("orderId") is None:
                return {**response, "data": strip_links(data)}
            order_id = str(data["orderId"])
            document_json, detail = await fetch_document_json(download_tool, order_id)
            return with_document(response, data, document_json, detail)
        except (KyckrApiError, ToolError) as exc:
            return error_response(exc)

    return create_document_order


def build_get_order(download_tool: Tool) -> Callable[..., object]:
    async def get_order(order_id: str | int) -> JsonObject:
        """
        Retrieve a single Kyckr order by `order_id`. Free to call. Use to poll an order placed via
        `create_document_order` until `data.status` is `Success` or `Failed`. On `Success` the JSON
        view of the document is inlined under `data.documentJson`; render it to the user as a
        readable summary. If it is absent, `details` says the document is PDF-only and PDF
        delivery is not yet supported; relay that message. Treat `statusCode: 410` as terminal:
        the order is no longer retrievable, do not retry. Never mention download URLs.
        """
        normalized_id = required_text(str(order_id), "order_id")
        try:
            response = success_response(await forward_payload({"orderId": normalized_id}))
            data = order_data(response)
            if data is None:
                return response
            if data.get("status") != "Success":
                return {**response, "data": strip_links(data)}
            document_json, detail = await fetch_document_json(download_tool, normalized_id)
            return with_document(response, data, document_json, detail)
        except (KyckrApiError, ToolError) as exc:
            return error_response(exc)

    return get_order


def build_list_orders() -> Callable[..., object]:
    async def list_orders(
        start_date: str | None = None,
        end_date: str | None = None,
        iso_code: str | None = None,
    ) -> JsonObject:
        """
        List previously placed Kyckr orders. Free to call. Optional filters: `start_date` and
        `end_date` (ISO 8601) and `iso_code` (jurisdiction). Orders are under `data.orders[]`, with
        paging in `data.pageNumber`, `data.pageSize` and `data.totalCount`. Each entry has the same
        shape as `get_order.data`. Use to reconcile when an order id is not in context.
        """
        arguments: JsonObject = {}
        if start_date:
            arguments["startDate"] = start_date.strip()
        if end_date:
            arguments["endDate"] = end_date.strip()
        normalized_iso_code = optional_iso_code(iso_code)
        if normalized_iso_code:
            arguments["isoCode"] = normalized_iso_code
        return await forward_response(arguments)

    return list_orders


async def register(mcp: FastMCP, settings: Settings) -> None:
    download_name = MCP_NAMES["get-orders-orderId-download"]
    download_tool = await mcp.get_tool(download_name)
    assert download_tool is not None, "generated download tool is missing"
    mcp.disable(names={download_name}, components={"tool"})

    await wrap_tool(
        mcp,
        "get-companies",
        build_search_companies(),
        {"companyNumber": "company_number", "isoCode": "iso_code"},
    )
    await wrap_tool(
        mcp, "get-companies-kyckrId", build_lite_profile(settings), {"kyckrId": "kyckr_id"}
    )
    await wrap_tool(
        mcp,
        "get-companies-kyckrId-enhanced",
        build_enhanced_profile(settings),
        {"kyckrId": "kyckr_id"},
    )
    await wrap_tool(
        mcp,
        "get-companies-kyckrId-documents",
        build_company_documents(settings),
        {"kyckrId": "kyckr_id", "continuationKey": "continuation_key"},
    )
    await wrap_tool(
        mcp,
        "post-orders",
        build_document_order(settings, download_tool),
        {"kyckrId": "kyckr_id", "productId": "product_id"},
    )
    await wrap_tool(
        mcp, "get-orders-orderId", build_get_order(download_tool), {"orderId": "order_id"}
    )
    await wrap_tool(
        mcp,
        "get-order",
        build_list_orders(),
        {"startDate": "start_date", "endDate": "end_date", "isoCode": "iso_code"},
    )
