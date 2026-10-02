from collections.abc import Mapping
from typing import Protocol, cast

import httpx
from kiota_abstractions.method import Method
from kiota_abstractions.request_adapter import RequestAdapter
from kiota_abstractions.request_information import RequestInformation
from kiota_abstractions.serialization.parsable import Parsable
from kiota_abstractions.serialization.parsable_factory import ParsableFactory
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client.client import request_with_query

type _ErrorMap = dict[str, type[ParsableFactory[ODataError]]]


class _Sends(Protocol):
    async def send_async[M: Parsable](
        self,
        request_info: RequestInformation,
        parsable_factory: ParsableFactory[M],
        error_map: _ErrorMap,
    ) -> M | None: ...

    async def send_no_response_content_async(
        self, request_info: RequestInformation, error_map: _ErrorMap
    ) -> None: ...


class _ParsableContent(Protocol):
    def set_content_from_parsable(
        self,
        request_adapter: RequestAdapter[httpx.Request],
        content_type: str,
        values: Parsable,
    ) -> None: ...


def request_with_json_body(
    client: GraphServiceClient,
    method: Method,
    url_template: str,
    path_parameters: Mapping[str, object],
    *,
    query: Mapping[str, str],
    body: Parsable,
) -> RequestInformation:
    request = request_with_query(method, url_template, path_parameters, query=query)
    cast("_ParsableContent", request).set_content_from_parsable(
        cast("RequestAdapter[httpx.Request]", client.request_adapter), "application/json", body
    )
    return request


async def send_parsed[M: Parsable](
    client: GraphServiceClient, request: RequestInformation, factory: ParsableFactory[M]
) -> M | None:
    return await _sends(client).send_async(request, factory, {"XXX": ODataError})


async def send_no_response_content(client: GraphServiceClient, request: RequestInformation) -> None:
    await _sends(client).send_no_response_content_async(request, {"XXX": ODataError})


def _sends(client: GraphServiceClient) -> _Sends:
    return cast("_Sends", client.request_adapter)
