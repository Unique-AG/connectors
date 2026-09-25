import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from typing import Annotated, Self
from uuid import UUID

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.entity_type import EntityType
from msgraph.generated.models.search_hit import SearchHit
from msgraph.generated.models.search_hits_container import SearchHitsContainer
from msgraph.generated.models.search_query import SearchQuery
from msgraph.generated.models.search_request import SearchRequest
from msgraph.generated.search.query.query_post_request_body import QueryPostRequestBody
from msgraph.generated.search.query.query_post_response import QueryPostResponse
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step
from office_365_mcp.shared.handles import (
    CHANNEL_PERMISSION,
    CHAT_PERMISSION,
    MessageHandle,
    message_handle,
)
from office_365_mcp.shared.kql import flag, free_text, quoted
from office_365_mcp.shared.messages import MessageReaction, MessageSender, TeamsMessage
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import as_utc

TOOL_NAME = "teams_search_messages"

STEP_SEARCH = "search_query"
STEP_CHAT_MESSAGE = "chat_message"
STEP_CHANNEL_MESSAGE = "channel_message"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "release"}

MAX_RESULTS = 50

_HYDRATION_CONCURRENCY = 3

_DESCRIPTION = (
    "Searches every Teams message the signed-in user can see, by keyword, sender, mention, "
    "date, attachment, or read state."
)


class MessageHit(BaseModel):
    uri: str | None = Field(
        description=(
            "A handle for this message; pass it to teams_read_message. Null when the hit "
            "cannot be addressed."
        )
    )
    message_id: str = Field(
        description="Graph's message id, unique only within its chat or channel."
    )
    chat_id: str | None = Field(
        description="The chat this message is in, or null for a channel message."
    )
    team_id: str | None = Field(
        description="The team a channel message belongs to, or null for a chat message."
    )
    channel_id: str | None = Field(
        description="The channel a channel message was posted in, or null for a chat message."
    )
    subject: str | None = Field(description="The message subject, usually null.")
    summary: str | None = Field(
        description="Microsoft's snippet of the matching text, not the full message."
    )
    sender: MessageSender = Field(description="Who sent the message.")
    created_at: datetime | None = Field(description="When the message was sent.")
    last_modified_at: datetime | None = Field(description="When the message was last modified.")
    importance: str | None = Field(description="`normal`, `high`, or `urgent`.")
    web_url: str | None = Field(
        description="A link to open the message in Teams; null for chat messages."
    )
    text: str | None = Field(
        description=(
            "The message as plain text; null unless `include_body` was set and hydration succeeded."
        )
    )
    reactions: list[MessageReaction] = Field(
        description=(
            "Reactions on the message; empty unless `include_body` was set and Graph answered."
        )
    )

    @classmethod
    def from_hit(cls, hit: SearchHit) -> Self | None:
        resource = hit.resource
        if not isinstance(resource, ChatMessage) or resource.id is None:
            return None
        sender = MessageSender.from_identity(resource.from_)
        if sender is None:
            return None
        channel = resource.channel_identity
        team_id = channel.team_id if channel is not None else None
        channel_id = channel.channel_id if channel is not None else None
        return cls(
            uri=_hit_uri(
                message_id=resource.id,
                chat_id=resource.chat_id,
                team_id=team_id,
                channel_id=channel_id,
            ),
            message_id=resource.id,
            chat_id=resource.chat_id,
            team_id=team_id,
            channel_id=channel_id,
            subject=resource.subject,
            summary=hit.summary,
            sender=sender,
            created_at=resource.created_date_time,
            last_modified_at=resource.last_modified_date_time,
            importance=resource.importance,
            web_url=resource.web_url,
            text=None,
            reactions=[],
        )


class MessageSearchResults(BaseModel):
    messages: list[MessageHit] = Field(description="The matched messages on this page.")
    next_offset: int | None = Field(
        description="The offset for the next page, or null when there is no next page."
    )


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    query: str | None = None
    sender: str | None = None
    recipient: str | None = None
    mentions: UUID | None = None
    sent_after: date | datetime | None = None
    sent_before: date | datetime | None = None
    has_attachment: bool | None = None
    is_read: bool | None = None
    mentions_me: bool | None = None

    @property
    def is_empty(self) -> bool:
        return not _query_string(self)


CRITERIA: tuple[str, ...] = tuple(field.name for field in fields(SearchCriteria))

_NO_CRITERIA = (
    "teams_search_messages needs at least one of "
    + ", ".join(CRITERIA)
    + ". A search with none of them returns an arbitrary sample of every message the user "
    + "can see, not an answer. Add the keywords, person, or date range the question is about."
)


def _query_string(criteria: SearchCriteria) -> str:
    terms: list[str] = []
    if criteria.query:
        rendered = free_text(criteria.query)
        if rendered:
            terms.append(rendered)
    if criteria.sender:
        terms.append(f"from:{quoted(criteria.sender)}")
    if criteria.recipient:
        terms.append(f"to:{quoted(criteria.recipient)}")
    if criteria.mentions is not None:
        terms.append(f"mentions:{criteria.mentions.hex}")
    if criteria.sent_after is not None:
        terms.append(f"sent>={_kql_moment(criteria.sent_after)}")
    if criteria.sent_before is not None:
        terms.append(f"sent<={_kql_moment(criteria.sent_before)}")
    if criteria.has_attachment is not None:
        terms.append(f"hasAttachment:{flag(criteria.has_attachment)}")
    if criteria.is_read is not None:
        terms.append(f"IsRead:{flag(criteria.is_read)}")
    if criteria.mentions_me is not None:
        terms.append(f"IsMentioned:{flag(criteria.mentions_me)}")
    return " ".join(terms)


def _kql_moment(bound: date | datetime) -> str:
    if isinstance(bound, datetime):
        return f"{as_utc(bound).astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"
    return bound.isoformat()


async def teams_search_messages(
    client: GraphServiceClient,
    *,
    criteria: SearchCriteria,
    offset: int,
    size: int,
    include_body: bool = False,
) -> MessageSearchResults:
    query = _query_string(criteria)
    assert query, (
        "teams_search_messages needs at least one criterion. The tool refuses an empty set."
    )
    assert 1 <= size <= MAX_RESULTS, f"size must be within 1..{MAX_RESULTS}, got {size}"
    assert offset >= 0, f"offset must not be negative, got {offset}"

    body = QueryPostRequestBody(
        requests=[
            SearchRequest(
                entity_types=[EntityType.ChatMessage],
                query=SearchQuery(query_string=query),
                from_=offset,
                size=size,
            )
        ]
    )
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_SEARCH):
            response = await client.search.query.post(body)

        assert response is not None, "Graph answered POST /search/query with no response"
        container = _hits_container(response)
        hits = (container.hits or []) if container is not None else []
        more_to_come = bool(container.more_results_available) if container else False

        messages = [
            message for message in (MessageHit.from_hit(hit) for hit in hits) if message is not None
        ]
        if include_body:
            messages = await _hydrated(client, messages)

    return MessageSearchResults(
        messages=messages,
        next_offset=offset + len(hits) if more_to_come and hits else None,
    )


async def _hydrated(client: GraphServiceClient, hits: list[MessageHit]) -> list[MessageHit]:
    semaphore = asyncio.Semaphore(_HYDRATION_CONCURRENCY)

    async def hydrated_hit(hit: MessageHit) -> MessageHit:
        handle = message_handle(hit.uri) if hit.uri is not None else None
        if handle is None:
            return hit
        async with semaphore:
            try:
                message = await _fetch(client, handle)
            except GraphFailure:
                return hit
        assert message is not None, "Graph answered a message read with no message"
        full = TeamsMessage.from_message(message, handle=handle)
        return hit.model_copy(update={"text": full.text, "reactions": full.reactions})

    return list(await asyncio.gather(*(hydrated_hit(hit) for hit in hits)))


async def _fetch(client: GraphServiceClient, handle: MessageHandle) -> ChatMessage | None:
    if handle.chat_id is not None:
        with graph_step(STEP_CHAT_MESSAGE):
            return await (
                client.chats.by_chat_id(handle.chat_id)
                .messages.by_chat_message_id(handle.message_id)
                .get()
            )
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a hit's handle addresses either a chat or a team channel"
    )
    with graph_step(STEP_CHANNEL_MESSAGE):
        return await (
            client.teams.by_team_id(handle.team_id)
            .channels.by_channel_id(handle.channel_id)
            .messages.by_chat_message_id(handle.message_id)
            .get()
        )


def _hits_container(response: QueryPostResponse) -> SearchHitsContainer | None:
    for search_response in response.value or []:
        for container in search_response.hits_containers or []:
            return container
    return None


def _hit_uri(
    *, message_id: str, chat_id: str | None, team_id: str | None, channel_id: str | None
) -> str | None:
    if team_id is not None and channel_id is not None:
        return MessageHandle(message_id=message_id, team_id=team_id, channel_id=channel_id).uri
    if chat_id is not None:
        return MessageHandle(message_id=message_id, chat_id=chat_id).uri
    return None


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Search Teams Messages",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def search_teams_messages(
        query: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Keywords to find; quote a phrase for exact adjacency.",
            ),
        ] = None,
        sender: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Only messages from this person, by name, alias, or email.",
            ),
        ] = None,
        recipient: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Only messages addressed to this person, in a one-to-one chat.",
            ),
        ] = None,
        mentions: Annotated[
            UUID | None,
            Field(description="Only messages that @-mention this user, by Entra object id."),
        ] = None,
        sent_after: Annotated[
            date | datetime | None,
            Field(description="Only messages sent at or after this point."),
        ] = None,
        sent_before: Annotated[
            date | datetime | None,
            Field(description="Only messages sent at or before this point."),
        ] = None,
        has_attachment: Annotated[
            bool | None,
            Field(description="Filter by whether the message has an attachment."),
        ] = None,
        is_read: Annotated[
            bool | None,
            Field(description="Filter by whether the message was read."),
        ] = None,
        mentions_me: Annotated[
            bool | None,
            Field(description="Filter by whether the message @-mentions the user."),
        ] = None,
        offset: Annotated[
            int,
            Field(ge=0, description="How many results to skip."),
        ] = 0,
        size: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=f"Results per page, at most {MAX_RESULTS}.",
            ),
        ] = 25,
        include_body: Annotated[
            bool,
            Field(description="Also fetch each hit's full text and reactions."),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> MessageSearchResults:
        criteria = SearchCriteria(
            query=query,
            sender=sender,
            recipient=recipient,
            mentions=mentions,
            sent_after=sent_after,
            sent_before=sent_before,
            has_attachment=has_attachment,
            is_read=is_read,
            mentions_me=mentions_me,
        )
        if criteria.is_empty:
            raise ToolError(_NO_CRITERIA)
        return await teams_search_messages(
            client,
            criteria=criteria,
            offset=offset,
            size=size,
            include_body=include_body,
        )
