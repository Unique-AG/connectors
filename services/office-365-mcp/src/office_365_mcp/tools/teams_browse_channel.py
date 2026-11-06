from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import unquote, urlsplit

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.teams.item.channels.item.messages.messages_request_builder import (
    MessagesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import CHANNEL_PERMISSION, MessageHandle
from office_365_mcp.shared.messages import TeamsMessage, event_of
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_browse_channel"

STEP = "channel_messages"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHANNEL_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "channel_id": "19:general@thread.tacv2",
}

MAX_POSTS = 50

type _MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_FOREIGN_PAGE_TOKEN = (
    "`page_token` is not the `next_page_token` of a page of this channel. Pass the "
    "`next_page_token` of the previous call of this tool unchanged, with the same `team_id` and "
    "`channel_id`. This same value fails again, so do not retry it."
)

_DESCRIPTION = f"""\
Reads one page of a Teams channel's posts and their replies in one call. The posts are ordered by \
reply activity rather than post date: the thread with the newest message comes first.

Notes:
- One page holds at most {MAX_POSTS} posts. This tool has no date filter.
- If `next_page_token` is set, more posts exist. To read them, call this tool again with the same \
`team_id` and `channel_id`, and pass the token unchanged as `page_token`. The page size stays \
the one of the first call.
- To answer a question about a period, read pages until the last thread of a page has no message \
from the period. Keep the posts and replies whose `created_at` is in the period.\
"""


class ChannelPosts(BaseModel):
    messages: list[TeamsMessage] = Field(
        description="The channel's posts and their replies, in thread order."
    )
    more_posts_in_channel: bool | None = Field(
        description=(
            "Whether more posts exist beyond this page; null unless "
            "`include_window_completeness` is set."
        )
    )
    posts_cut_to_limit: bool | None = Field(
        description=(
            "Whether the page held more posts than `limit`; null unless "
            "`include_window_completeness` is set. Null on a next page, because a next page "
            "keeps every post."
        )
    )
    next_page_token: str | None = Field(
        description=(
            "Pass this unchanged as `page_token` to read the next page. Null on the last page."
        )
    )


async def teams_browse_channel(
    client: GraphServiceClient,
    *,
    team_id: str,
    channel_id: str,
    limit: int,
    include_window_completeness: bool,
    page_token: str | None = None,
) -> ChannelPosts:
    assert 1 <= limit <= MAX_POSTS, f"limit must be within 1..{MAX_POSTS}, got {limit}"

    channel_messages = client.teams.by_team_id(team_id).channels.by_channel_id(channel_id).messages
    configuration: RequestConfiguration[_MessagesQuery] | None = None
    if page_token is None:
        configuration = RequestConfiguration[_MessagesQuery](
            query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                expand=["replies"], top=limit
            )
        )
    else:
        base_url = channel_messages.request_adapter.base_url  # pyright: ignore[reportUnknownMemberType]
        channel_messages = channel_messages.with_url(
            _own_continuation(page_token, base_url=base_url, team_id=team_id, channel_id=channel_id)
        )
    with graph_errors(TOOL_NAME, step=STEP):
        page = await channel_messages.get(request_configuration=configuration)
        assert page is not None, "Graph answered a channel message listing with no collection"

    posts = [message for message in (page.value or []) if _is_a_post(message)]
    kept = posts if page_token is not None else posts[:limit]

    messages: list[TeamsMessage] = []
    for post in kept:
        assert post.id is not None, "Graph returned a channel message with no id"
        messages.append(
            TeamsMessage.from_message(
                post, handle=MessageHandle(post.id, team_id=team_id, channel_id=channel_id)
            )
        )
        messages.extend(
            TeamsMessage.from_message(
                reply,
                handle=MessageHandle(
                    _reply_id(reply), team_id=team_id, channel_id=channel_id, reply_to_id=post.id
                ),
            )
            for reply in _replies(post)
        )

    return ChannelPosts(
        messages=messages,
        more_posts_in_channel=bool(page.odata_next_link) if include_window_completeness else None,
        posts_cut_to_limit=(
            len(kept) < len(posts) if include_window_completeness and page_token is None else None
        ),
        next_page_token=page.odata_next_link,
    )


def _own_continuation(link: str, *, base_url: str, team_id: str, channel_id: str) -> str:
    parts, base = urlsplit(link), urlsplit(base_url)
    messages_path = f"{base.path}/teams/{team_id}/channels/{channel_id}/messages"
    if (
        not link.isprintable()
        or (parts.scheme, parts.netloc) != (base.scheme, base.netloc)
        or unquote(parts.path) != messages_path
    ):
        raise ToolError(_FOREIGN_PAGE_TOKEN)
    return link


def _is_a_post(message: ChatMessage) -> bool:
    return event_of(message) is None


def _replies(post: ChatMessage) -> list[ChatMessage]:
    return sorted((reply for reply in post.replies or [] if _is_a_post(reply)), key=_sent_at)


def _sent_at(message: ChatMessage) -> datetime:
    return message.created_date_time or datetime.min.replace(tzinfo=UTC)


def _reply_id(reply: ChatMessage) -> str:
    assert reply.id is not None, "Graph returned a channel reply with no id"
    return reply.id


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Browse a Teams Channel",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def browse_a_channel(
        team_id: Annotated[
            str,
            Field(
                min_length=1,
                description="The team the channel is in, as reported by teams_list_my_teams.",
            ),
        ],
        channel_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The channel to read, as reported by teams_list_channels or "
                    "teams_search_messages; always pass it with `team_id`."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_POSTS,
                description=(
                    f"How many posts one page holds, each with its replies, at most {MAX_POSTS}."
                ),
            ),
        ] = 20,
        include_window_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Whether to populate `more_posts_in_channel` and `posts_cut_to_limit`."
                )
            ),
        ] = False,
        page_token: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The `next_page_token` of the previous call. Omit it to read the first page."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> ChannelPosts:
        return await teams_browse_channel(
            client,
            team_id=team_id,
            channel_id=channel_id,
            limit=limit,
            include_window_completeness=include_window_completeness,
            page_token=page_token,
        )
