"""`outlook_list_mail` — the newest messages of one folder, in receipt order, exhaustively.

Where `outlook_search_mail` asks Microsoft's index a question and takes back whatever order the
index answers in, this walks one folder's own message collection: newest received first, every
message in it, and a bound Exchange evaluates rather than an index. That is the reason both tools
exist. "Find the mail about the invoice" is a search; "what came in today", "the last ten" and
"what is still unread" are this.

**The ordering construction is the whole of the query, not a detail of it.** Microsoft publishes
three rules for combining `$orderby` with `$filter` on a message collection
(https://learn.microsoft.com/en-us/graph/api/user-list-messages): every property in `$orderby` must
also appear in `$filter`, the two must name them in the same order, and the ordered properties must
come before any property that is not ordered. A violation is answered with `InefficientFilter`, a
400 that reads like a bad argument and is really a query the tool composed. So:

* `$orderby=receivedDateTime desc`, always and unconditionally. Receipt order is what this tool
  promises, and a promise kept only for some arguments is worse than no promise.
* `$filter=receivedDateTime ge {received_after}`, only when a date was given, and
  `receivedDateTime` is the only property that ever reaches `$filter`.
* `unread_only` is applied here, through `collect_pages`'s `matches` predicate, and never in
  `$filter`. `isRead` there, unordered, beside an `$orderby` on `receivedDateTime`, is precisely
  the third rule broken.

One property in `$orderby`, that same one property in `$filter`, and nothing else in either: no
combination of these arguments can break a rule, so `InefficientFilter` is impossible by
construction rather than merely untriggered by the cases somebody thought to try.

**Two Graph calls, and the folder is read first.** `totalItemCount` and `unreadItemCount` sit on
the folder object, where Microsoft recommends reading them over counting a folder's messages with
`$count` and `$filter`. They are what make a short answer legible: twenty-five messages back
against an `unreadItemCount` of seventy is a slice, three back with `capped` false is the lot. They
count items of every type, so they bound the messages in a folder rather than counting them.

**`Prefer: IdType="ImmutableId"` on the message listing.** The ids it mints become handles, and a
handle built from a `RestId` dies the moment Outlook files the message — which inbox rules and
retention do unprompted — after which `outlook_read_mail` answers a 404 that a model reads as
"deleted". `outlook_read_mail` sends the same header on the way in, so the two agree about which id
space a handle is spelled in. The header travels on a collection built per request, and the same
collection is handed to `collect_pages`: kiota's `RequestConfiguration.headers` default is one
object shared process-wide, and `PageIterator` starts from an empty one, so a preference set once
would leak onto every other Graph call and still not reach page two.

**`$skip` is never read out of an `@odata.nextLink`.** Microsoft documents its value as counting
every item the service enumerated to build that page, not the items handed back, so it can exceed
the page size on page one; a caller treating it as "how far I have got" skips messages. The link is
followed whole and never parsed.
"""

from collections.abc import Mapping
from datetime import date
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.tools import tool as tool_metadata
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.mail_folders.item.mail_folder_item_request_builder import (
    MailFolderItemRequestBuilder,
)
from msgraph.generated.users.item.mail_folders.item.messages.messages_request_builder import (
    MessagesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import mail_folder_handle
from office_365_mcp.shared.mail import SUMMARY_FIELDS, MailSummary, WellKnownFolder
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_mail"

STEP_FOLDER = "mail_folder"
STEP_MESSAGES = "folder_messages"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read",)

# The default call, and the one that reaches Graph without a handle from a previous response.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"folder": "inbox"}

# The default 404 advice, to check the id was copied from a tool response verbatim, is wrong for
# both ways in here: a folder handle is this connector's own, and a well-known name is a name rather
# than an id.
GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this folder, so no message in it could be listed. If "
    + "`folder_ref` was used, the handle is well formed and the folder was most likely deleted, "
    + "moved or copied — Outlook may give it a new id — so call outlook_browse_folders again and "
    + "take the `uri` it reports now. If `folder` was used, this mailbox has no folder by that "
    + "well-known name: `archive` and `clutter` in particular are absent from mailboxes that were "
    + "never given them, and outlook_browse_folders lists what this mailbox actually has. "
    + "Retrying with the same argument will fail identically."
)

MAX_RESULTS = 50

DEFAULT_FOLDER: WellKnownFolder = "inbox"

# The two ways in, spelled once: the schema constraint and the refusal below must name the same
# pair, and a rename that reached only one of them would leave a client refused by a rule the
# schema does not publish.
FOLDER_ARGUMENTS: tuple[str, str] = ("folder", "folder_ref")

# Everything the answer reads off the folder, and nothing else. No `id`: the folder is addressed by
# the argument that reached it, so reading its id back would only invite spelling a second handle.
_FOLDER_FIELDS: tuple[str, ...] = ("displayName", "totalItemCount", "unreadItemCount")

# Unconditional, and the only `$orderby` this tool has. See the module docstring.
_NEWEST_FIRST = "receivedDateTime desc"

# The first instant of the day asked for, in UTC, so that day is inside the bound.
_START_OF_DAY = "T00:00:00Z"

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_FolderQuery = MailFolderItemRequestBuilder.MailFolderItemRequestBuilderGetQueryParameters
_MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List the newest messages of ONE mail folder in the signed-in user's mailbox, newest received \
first. This is the exhaustive, ordered half of mail reading: it walks the folder itself, so "the \
last ten mails", "what arrived since Monday" and "what is still unread" belong here. \
outlook_search_mail is the other half — index-backed, in Microsoft's own order, which is not \
receipt order and cannot be bounded by date — so use it for "find the mail where…" and this for \
anything about recency. Name a well-known folder with `folder` (`inbox`, `sentitems`, `drafts`, \
`archive`, `deleteditems`, `junkemail`, `clutter`), or any other folder with `folder_ref`, the \
`uri` of an outlook_browse_folders result; pass one or the other, never both. Only mail filed \
directly in that folder is listed, never its subfolders. Rows carry metadata and a short preview — \
pass a row's `uri` to outlook_read_mail for what the message says. The folder's own item and \
unread counts come back beside the rows, which is how "that is all of them" is told apart from \
"that is the first slice".\
"""

_BOTH_FOLDERS = (
    "outlook_list_mail lists one folder, so `folder` and `folder_ref` are alternatives and not a "
    + "pair: `folder` names a well-known folder such as `inbox`, `folder_ref` addresses any folder "
    + "by the handle outlook_browse_folders reported for it. Pass whichever one names the folder "
    + "the question is about and omit the other entirely."
)

_NOT_A_FOLDER_HANDLE = (
    "outlook_list_mail takes a folder handle in `folder_ref`, outlook:///folders/{id}, exactly as "
    + "outlook_browse_folders reported it in `uri`. A folder's name is not one, nor is a message "
    + "handle. For the Inbox and the other well-known folders use `folder` instead, which takes "
    + "names such as `inbox` and `sentitems`."
)


class FolderMessages(BaseModel):
    """One folder's newest mail, and the folder's own counts to read the answer's length against."""

    folder_name: str | None = Field(
        description=(
            "The folder's name as Outlook shows it, e.g. `Inbox`. It comes from the mailbox, so "
            + "it is in the mailbox's own language whichever name or handle was asked for. Null "
            + "when Graph recorded none."
        )
    )
    total_items: int | None = Field(
        description=(
            "How many items the folder holds, read off the folder itself rather than counted "
            + "here — the count Microsoft recommends over counting a folder's messages, which it "
            + "warns can incur significant latency. It counts items of every type, so it bounds "
            + "the messages in this folder rather than counting them, and it excludes the "
            + "subfolders this tool does not list either. Null when Graph did not say."
        )
    )
    unread_items: int | None = Field(
        description=(
            "How many of `total_items` are unread, on the same terms: items of every type, so an "
            + "upper bound rather than a count. This is what makes the length of `messages` mean "
            + "something. Twenty-five unread rows against an `unread_items` of 70 says roughly 45 "
            + "more unread messages exist that this call did not reach; three rows with `capped` "
            + "false says those three are all there are. Null when Graph did not say."
        )
    )
    messages: list[MailSummary] = Field(
        description=(
            "The messages, newest received first — Exchange's own order on `received_at`, not an "
            + "index's ranking and not the order they were sent. Only mail filed directly in this "
            + "folder; a subfolder's mail is in that subfolder and is reached by listing it. Each "
            + "row's `uri` survives the message being filed elsewhere, so it can be read later."
        )
    )
    capped: bool = Field(
        description=(
            "True when this call stopped with more of the folder still on offer: `limit` filled "
            + "up, or the internal scan limit was reached while `unread_only` was discarding read "
            + "messages. Raising `limit` or narrowing with `received_after` returns more. False "
            + "means the folder, or the window `received_after` opened, ran out on its own, so "
            + "what came back is all of it however few rows that is. Read it against "
            + "`unread_items` and `total_items`, which say how much was there to begin with."
        )
    )


async def list_mail(
    client: GraphServiceClient,
    *,
    folder: WellKnownFolder = DEFAULT_FOLDER,
    folder_ref: str | None = None,
    unread_only: bool = False,
    received_after: date | None = None,
    limit: int,
) -> FolderMessages:
    """The newest `limit` messages of one folder, and that folder's own counts."""
    assert 1 <= limit <= MAX_RESULTS, f"limit must be within 1..{MAX_RESULTS}, got {limit}"
    address = _folder_address(folder, folder_ref)

    with graph_errors(TOOL_NAME):
        with graph_step(STEP_FOLDER):
            found = await client.me.mail_folders.by_mail_folder_id(address).get(
                request_configuration=RequestConfiguration[_FolderQuery](
                    query_parameters=_FolderQuery(select=list(_FOLDER_FIELDS))
                )
            )
        assert found is not None, "Graph answered a mail folder read with no folder"
        headers = _headers()
        with graph_step(STEP_MESSAGES):
            first_page = await client.me.mail_folders.by_mail_folder_id(address).messages.get(
                request_configuration=RequestConfiguration[_MessagesQuery](
                    query_parameters=_MessagesQuery(
                        select=list(SUMMARY_FIELDS),
                        top=limit,
                        orderby=[_NEWEST_FIRST],
                        filter=_received_from(received_after),
                    ),
                    headers=headers,
                )
            )
            assert first_page is not None, "Graph answered a message listing with no collection"
            collected = await collect_pages(
                first_page,
                client,
                limit=limit,
                matches=_is_unread if unread_only else None,
                headers=headers,
            )

    return FolderMessages(
        folder_name=found.display_name,
        total_items=found.total_item_count,
        unread_items=found.unread_item_count,
        messages=[_summary(message) for message in collected.items],
        capped=collected.capped,
    )


def _folder_address(folder: WellKnownFolder, folder_ref: str | None) -> str:
    """The single path segment that addresses the folder: a well-known name, or a handle's id.

    A `folder` left at its default is indistinguishable here from one a caller spelled out, because
    FastMCP fills a default in before the body runs — so this catches every explicit `folder`
    beside a `folder_ref`, and the schema's own constraint catches the pair a client sent as
    `folder="inbox", folder_ref=…`.
    """
    if folder_ref is None:
        return folder
    if folder != DEFAULT_FOLDER:
        raise ToolError(_BOTH_FOLDERS)
    handle = mail_folder_handle(folder_ref)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    return handle.folder_id


def _received_from(received_after: date | None) -> str | None:
    """The only `$filter` this tool can produce, or None when no date was given.

    Formatted rather than `isoformat()`d so a `datetime` that reached here would still render the
    day it falls on: the bound this argument promises is a day in UTC, not an instant.
    """
    if received_after is None:
        return None
    return f"receivedDateTime ge {received_after:%Y-%m-%d}{_START_OF_DAY}"


def _is_unread(message: Message) -> bool:
    """`isRead` false, and not merely absent: a message Graph said nothing about is not evidence of
    an unread one, and `unread_only` is a claim about the rows it keeps."""
    return message.is_read is False


def _summary(message: Message) -> MailSummary:
    """The listing's own id becomes the handle, which the `Prefer` header makes an immutable one —
    no exchange to make, unlike a `$search` hit."""
    assert message.id is not None, "Graph returned a message with no id"
    return MailSummary.from_message(message, message_id=message.id)


def _headers() -> HeadersCollection:
    """Built per request: kiota's `RequestConfiguration.headers` defaults to one collection shared
    by every configuration in the process, so a preference added to it leaks onto every Graph call.
    The same collection is handed to `collect_pages`, whose `PageIterator` otherwise starts from an
    empty one and fetches page two in the other id space."""
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @tool_metadata(
        name=TOOL_NAME,
        title="List Mail in a Folder",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_mail(
        folder: Annotated[
            WellKnownFolder,
            Field(
                description=(
                    "Which well-known folder to list, by Microsoft's own locale-independent name, "
                    + "so `inbox` reaches the Inbox of a mailbox in any language. Every other "
                    + "folder, including every folder the user made, is reached with `folder_ref` "
                    + "instead — a folder's own name is not accepted here. Omit this entirely "
                    + "when passing `folder_ref`."
                )
            ),
        ] = DEFAULT_FOLDER,
        folder_ref: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder to list, as the `uri` of an outlook_browse_folders result: "
                    + "outlook:///folders/{id}. Use it for anything the well-known names do not "
                    + "cover. Alternative to `folder`, never a companion to it. A folder name, a "
                    + "well-known name and a message handle are none of them folder handles."
                ),
            ),
        ] = None,
        unread_only: Annotated[
            bool,
            Field(
                description=(
                    "Keep only the messages Microsoft reports as unread. Applied to the messages "
                    + "this call read rather than by Exchange, deliberately: read state cannot be "
                    + "filtered on alongside receipt order without Microsoft refusing the query. "
                    + "So a folder holding few unread messages among many can exhaust this call's "
                    + "internal scan before it fills `limit`, and `capped` says when it did. "
                    + "Compare what comes back with `unread_items` for how much was reached."
                )
            ),
        ] = False,
        received_after: Annotated[
            date | None,
            Field(
                description=(
                    "Only messages received on or after this date, as YYYY-MM-DD, e.g. "
                    + "2026-03-04. The bound is the first instant of that day in UTC and the day "
                    + "itself is included, so a user's early morning or late evening can fall on "
                    + "the neighbouring UTC day. There is no upper bound and none is needed: the "
                    + "answer starts at the newest, so a window is read from the top."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=(
                    f"How many messages to return, at most {MAX_RESULTS}. They are the newest "
                    + "that many of the folder, or of the window `received_after` opens. Paging "
                    + "happens inside the call, so this is the whole answer rather than a first "
                    + "page: raise it rather than calling again with the same arguments."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> FolderMessages:
        return await list_mail(
            client,
            folder=folder,
            folder_ref=folder_ref,
            unread_only=unread_only,
            received_after=received_after,
            limit=limit,
        )

    _one_folder_at_a_time(mcp.add_tool(outlook_list_mail))


def _one_folder_at_a_time(tool: Tool) -> None:
    """Say "one of these two, not both" in the schema, which a Python signature cannot.

    The runtime refusal stays: FastMCP validates arguments against the signature rather than
    against this schema, so a client that ignores the constraint still has to be told.
    """
    tool.parameters["not"] = {"required": list(FOLDER_ARGUMENTS)}
