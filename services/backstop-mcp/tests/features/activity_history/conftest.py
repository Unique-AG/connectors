from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import date, datetime

import httpx
import pytest
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    GetActivityDetailQuery,
    GetActivityHistoryQuery,
    GetMeetingAttendeesQuery,
    SearchActivitiesQuery,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil
from tests.helpers import client_factory, credential
from tests.server.tools.helpers import object_dict


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_get_activity_detail_query(client: BackstopClient) -> GetActivityDetailQuery:
    return GetActivityDetailQuery(
        client=client,
        build_entity_link_util=BuildEntityLinkUtil(ui_base_url=None),
        get_meeting_attendees_query=GetMeetingAttendeesQuery(client=client),
    )


def make_get_activity_history_query(
    client: BackstopClient, *, ui_base_url: str | None = None
) -> GetActivityHistoryQuery:
    return GetActivityHistoryQuery(
        client=client,
        build_entity_link_util=BuildEntityLinkUtil(ui_base_url=ui_base_url),
        get_meeting_attendees_query=GetMeetingAttendeesQuery(client=client),
    )


def make_search_activities_query(client: BackstopClient) -> SearchActivitiesQuery:
    return SearchActivitiesQuery(client=client)


def _json_body(request: httpx.Request) -> dict[str, object]:
    return TypeAdapter(dict[str, object]).validate_json(request.content)


def serve_entity_activities(
    rows: Sequence[dict[str, object]], *, wall: int = 10_000
) -> Callable[[httpx.Request], httpx.Response]:
    """A fake `POST /entity-activities`: `rows` in served order, cut to the body's effective-date
    window and paged by `pageNum`/`pageSize`. A page starting at or past `wall` is a 500, and
    `totalCount` saturates at it, as probed."""

    def respond(request: httpx.Request) -> httpx.Response:
        attributes = object_dict(object_dict(_json_body(request)["data"])["attributes"])
        window = object_dict(object_dict(attributes["newFilters"])["effectiveDate"])
        start = date.fromisoformat(str(window["startTimestamp"])[:10])
        end = date.fromisoformat(str(window["endTimestamp"])[:10])
        page_size = int(str(attributes["pageSize"]))
        in_window = [
            row
            for row in rows
            if start <= datetime.strptime(str(row["effectiveDate"]), "%m/%d/%Y").date() <= end
        ]
        offset = (int(str(attributes["pageNum"])) - 1) * page_size
        if offset >= wall:
            return httpx.Response(500, json={"errors": [{"code": "InternalServerException"}]})
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": -1,
                    "type": "entity-activities",
                    "attributes": {
                        "totalCount": min(len(in_window), wall),
                        "results": in_window[offset : offset + page_size],
                    },
                }
            },
        )

    return respond
