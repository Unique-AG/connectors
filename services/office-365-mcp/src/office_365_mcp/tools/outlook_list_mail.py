"""`outlook_list_mail` — the newest messages of one folder, in receipt order.

Every property in `$orderby` must also appear in `$filter`, in the same order, and before any
unordered one, or Graph answers 400 `InefficientFilter`
(https://learn.microsoft.com/en-us/graph/api/user-list-messages): so the `receivedDateTime` bounds
open the `$filter`, and `isRead` and `from` only ever follow one. An unsupported combination can
also fail *silently* (https://learn.microsoft.com/en-us/graph/query-parameters), so `_keeps`
re-checks those two on every row. `Prefer: IdType="ImmutableId"` because the ids listed here
become handles, and a `RestId` one 404s once Outlook files the message. `$skip` inside an
`@odata.nextLink` counts items the service enumerated rather than items returned, so the link is
followed whole and never parsed.
"""

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
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
from office_365_mcp.shared.mail import (
    ONE_ADDRESS,
    SUMMARY_FIELDS,
    MailSummary,
    WellKnownFolder,
)
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import closes_at, opens_at, runs_backwards

TOOL_NAME = "outlook_list_mail"

STEP_FOLDER = "mail_folder"
STEP_MESSAGES = "folder_messages"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"folder": "inbox"}

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this folder, so this tool cannot list any message in it. If "
    + "the caller used `folder_ref`, the handle is well formed. The folder was most likely "
    + "deleted, moved, or copied. Outlook can give a moved or copied folder a new id. So call "
    + "outlook_browse_folders again and take the `uri` it reports now. If the caller used "
    + "`folder`, this mailbox has no folder by that well-known name: `archive` and `clutter` in "
    + "particular are absent from mailboxes that never had them, and outlook_browse_folders "
    + "lists what this mailbox actually has. Retrying with the same argument will fail "
    + "identically."
)

MAX_RESULTS = 50

DEFAULT_FOLDER: WellKnownFolder = "inbox"

# The schema constraint and the `_BOTH_FOLDERS` refusal must name the same pair.
FOLDER_ARGUMENTS: tuple[str, str] = ("folder", "folder_ref")

_FOLDER_FIELDS: tuple[str, ...] = ("displayName", "totalItemCount", "unreadItemCount")

_NEWEST_FIRST = "receivedDateTime desc"

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_FolderQuery = MailFolderItemRequestBuilder.MailFolderItemRequestBuilderGetQueryParameters
_MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List the newest messages of ONE mail folder in the signed-in user's mailbox, newest received \
first. This is the exhaustive, ordered half of mail reading: it walks the folder itself, so "the \
last ten mails", "what arrived since Monday" and "what is still unread" belong here. \
outlook_search_mail is the other half: index-backed, in Microsoft's own order, which is not \
receipt order. It takes the same two date bounds, so a window is not what decides between them — \
use it for "find the mail where…", and this one for anything about recency, for a window with \
nothing to search for, and when unsent drafts matter, which its index does not reach. \
`received_after` and `received_before` bound receipt date at either end, and both of those days \
are covered whole, so "the mail from March" and "what came in on Tuesday" are each one call. Bound \
a past window at BOTH ends: rows come newest first, so `received_after` alone spends `limit` on \
everything newer than the window before reaching it. Name a well-known folder with `folder` \
(`inbox`, `sentitems`, `drafts`, `archive`, `deleteditems`, `junkemail`, `clutter`), or any other \
folder with `folder_ref`, the `uri` of an outlook_browse_folders result. Pass one or the other, \
never both. This tool lists only mail filed directly in that folder, never its subfolders. Rows \
carry metadata and a short preview. Pass a row's `uri` to outlook_read_mail for what the message \
says. The folder's own item and unread counts come back beside the rows. These counts show whether \
"that is all of them" or "that is the first slice". \
"""

_BOTH_FOLDERS = (
    "outlook_list_mail lists one folder, so `folder` and `folder_ref` are alternatives, not a "
    + "pair. `folder` names a well-known folder, such as `inbox`. `folder_ref` addresses any "
    + "folder, by the handle outlook_browse_folders reported for it. Pass whichever one names "
    + "the folder the question is about. Omit the other entirely."
)

_WINDOW_RUNS_BACKWARDS = (
    "outlook_list_mail read nothing, because `received_before` falls before `received_after` and "
    + "no folder holds a window that runs backwards. Both arguments are dates and both days are "
    + "covered whole, so one date in both lists that single day. Put the earlier date in "
    + "`received_after` and the later one in `received_before`, then call again. Retrying with the "
    + "same two dates will fail identically."
)

_NOT_ONE_ADDRESS = (
    "outlook_list_mail matches `from_address` against the sender's SMTP address, so it takes one "
    + "address and nothing else: `bob@vance.example`, not `Bob Vance` and not "
    + "`Bob Vance <bob@vance.example>`. A name here matches no message, and Microsoft 365 answers "
    + 'that with an empty page rather than an error, which reads as "no mail from Bob". Call '
    + "outlook_find_recipient to turn a name into an address, then pass that. For mail merely "
    + "mentioning somebody, or to search on a display name, use outlook_search_mail instead."
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
            "The folder's name as Outlook shows it, for example `Inbox`. It comes from the "
            + "mailbox, so it is in the mailbox's own language, whichever name or handle the "
            + "caller asked for. Null when Graph recorded none."
        )
    )
    total_items: int | None = Field(
        description=(
            "How many items the folder holds, read off the folder itself rather than counted "
            + "here. This is the count Microsoft recommends over counting a folder's messages. "
            + "Microsoft warns that counting messages directly can incur significant latency. It "
            + "counts items of every type, so it bounds the messages in this folder rather than "
            + "counting them. It also excludes the subfolders this tool does not list either. "
            + "Null when Graph did not say."
        )
    )
    unread_items: int | None = Field(
        description=(
            "How many of `total_items` are unread, on the same terms: items of every type, so an "
            + "upper bound rather than a count. This is what makes the length of `messages` mean "
            + "something. Twenty-five unread rows against an `unread_items` of 70 says roughly 45 "
            + "more unread messages exist that this call did not reach. Three rows with `capped` "
            + "false says those three are all there are. Null when Graph did not say."
        )
    )
    messages: list[MailSummary] = Field(
        description=(
            "The messages, newest received first — Exchange's own order on `received_at`, not an "
            + "index's ranking and not the order they were sent. This tool lists only mail filed "
            + "directly in this folder. A subfolder's mail stays in that subfolder, and a listing "
            + "of that subfolder reaches it. Each row's `uri` survives even after the mailbox "
            + "files the message elsewhere, so a reader can read it later."
        )
    )
    capped: bool = Field(
        description=(
            "True when this call stopped with more of the folder still on offer. Either `limit` "
            + "filled up, or the internal scan limit ran out while `unread_only` discarded read "
            + "messages. A higher `limit`, or a narrower window, returns more. Narrow it at the "
            + "NEWEST end: rows arrive newest first, so `received_before` is what drops mail this "
            + "answer already spent `limit` on, where raising `received_after` only drops the rows "
            + "that were never reached. False means the folder, or the window the two bounds "
            + "opened, ran out on its own. So what came back is all of it, however few rows that "
            + "is. Read it against `unread_items` and `total_items`, which say how much was there "
            + "to begin with."
        )
    )


async def list_mail(
    client: GraphServiceClient,
    *,
    folder: WellKnownFolder = DEFAULT_FOLDER,
    folder_ref: str | None = None,
    unread_only: bool = False,
    received_after: date | datetime | None = None,
    received_before: date | datetime | None = None,
    from_address: str | None = None,
    limit: int,
) -> FolderMessages:
    """The newest `limit` messages of one folder, and that folder's own counts."""
    assert 1 <= limit <= MAX_RESULTS, f"limit must be within 1..{MAX_RESULTS}, got {limit}"
    _refuse_a_backwards_window(received_after, received_before)
    sender = _one_address(from_address)
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
                        filter=_query_filter(
                            received_after, received_before, unread_only=unread_only, sender=sender
                        ),
                    ),
                    headers=headers,
                )
            )
            assert first_page is not None, "Graph answered a message listing with no collection"
            collected = await collect_pages(
                first_page,
                client,
                limit=limit,
                matches=_keeps(unread_only=unread_only, sender=sender),
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

    FastMCP fills the `folder` default in before the body runs, so an explicit `folder="inbox"`
    beside a `folder_ref` is caught by the schema constraint rather than here.
    """
    if folder_ref is None:
        return folder
    if folder != DEFAULT_FOLDER:
        raise ToolError(_BOTH_FOLDERS)
    handle = mail_folder_handle(folder_ref)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    return handle.folder_id


def _refuse_a_backwards_window(
    received_after: date | datetime | None, received_before: date | datetime | None
) -> None:
    """Refuse a backwards window here: Graph answers one with an empty page, indistinguishable
    from "no mail in that window". `runs_backwards` compares the bounds as instants, because
    Python refuses to compare a `date` with a `datetime`."""
    if runs_backwards(received_after, received_before):
        raise ToolError(_WINDOW_RUNS_BACKWARDS)


def _query_filter(
    received_after: date | datetime | None,
    received_before: date | datetime | None,
    *,
    unread_only: bool,
    sender: str | None,
) -> str | None:
    """The `$filter` this tool sends, or None when it would send none.

    The `receivedDateTime` bounds are ordered and must come first; `isRead` and
    `from/emailAddress/address` are unordered and go on only when a date term did, because alone
    beside `$orderby=receivedDateTime` they are an `InefficientFilter` 400. Reordering these lines
    composes that 400 out of arguments that are individually fine.
    """
    dated = _received_within(received_after, received_before)
    if dated is None:
        return None
    terms = [dated]
    if unread_only:
        terms.append("isRead eq false")
    if sender is not None:
        terms.append(f"from/emailAddress/address eq '{odata_literal(sender)}'")
    return " and ".join(terms)


def _received_within(
    received_after: date | datetime | None, received_before: date | datetime | None
) -> str | None:
    """The ordered half of the `$filter`, or None when the caller bounded neither end.

    Microsoft publishes this two-sided `receivedDateTime` range against this collection and rules
    that a DateTimeOffset literal is not quoted
    (https://learn.microsoft.com/en-us/graph/filter-query-parameter).
    """
    terms: list[str] = []
    if received_after is not None:
        terms.append(f"receivedDateTime ge {_wire(opens_at(received_after))}")
    if received_before is not None:
        terms.append(f"receivedDateTime {_closing_term(received_before)}")
    if not terms:
        return None
    return " and ".join(terms)


def _closing_term(received_before: date | datetime) -> str:
    """Either spelling covers the whole of the value the caller named."""
    if isinstance(received_before, datetime):
        return f"le {_wire(closes_at(received_before))}"
    return f"lt {_wire(opens_at(received_before + timedelta(days=1)))}"


def _wire(instant: datetime) -> str:
    """An instant as the ISO-8601 UTC literal Graph documents, keeping whatever precision it has.

    Truncating to whole seconds moves the bound silently in both directions, and a row lost at the
    boundary leaves a well-formed answer with `capped` false and nothing saying it was dropped.
    """
    if instant.microsecond:
        return f"{instant:%Y-%m-%dT%H:%M:%S.%f}Z"
    return f"{instant:%Y-%m-%dT%H:%M:%SZ}"


def _keeps(*, unread_only: bool, sender: str | None) -> Callable[[Message], bool] | None:
    """What every returned row must satisfy, or None when the caller asked for no narrowing.

    This runs whether or not `_query_filter` sent the matching term, because Graph can drop an
    unsupported one silently. Both properties are in `SUMMARY_FIELDS`, so it costs nothing.
    """
    checks: list[Callable[[Message], bool]] = []
    if unread_only:
        checks.append(_is_unread)
    if sender is not None:
        checks.append(_sent_by(sender))
    if not checks:
        return None
    return lambda message: all(check(message) for check in checks)


def _is_unread(message: Message) -> bool:
    """`isRead` false, and not merely absent: a message Graph said nothing about is not unread."""
    return message.is_read is False


def _sent_by(sender: str) -> Callable[[Message], bool]:
    """Whether the message came from this address, compared case-insensitively as SMTP is: the
    casing on a message is the sender's server's, not the caller's."""
    wanted = sender.casefold()

    def sent_by(message: Message) -> bool:
        recorded = message.from_.email_address if message.from_ is not None else None
        return recorded is not None and (recorded.address or "").casefold() == wanted

    return sent_by


def _one_address(from_address: str | None) -> str | None:
    """The argument as one SMTP address, or a refusal: a display name reaches Graph as an address
    matching nothing, and `eq` answers that with an empty page rather than an error."""
    if from_address is None:
        return None
    candidate = from_address.strip()
    if ONE_ADDRESS.match(candidate) is None:
        raise ToolError(_NOT_ONE_ADDRESS)
    return candidate


def _summary(message: Message) -> MailSummary:
    assert message.id is not None, "Graph returned a message with no id"
    return MailSummary.from_message(message, message_id=message.id)


def _headers() -> HeadersCollection:
    """Built per request: kiota's `RequestConfiguration.headers` defaults to one collection shared
    process-wide, and `collect_pages`' `PageIterator` otherwise starts from an empty one."""
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
                    + "so `inbox` reaches the Inbox of a mailbox in any language. Use `folder_ref` "
                    + "instead for every other folder, including every folder the user made. This "
                    + "tool does not accept a folder's own name here. When the call includes "
                    + "`folder_ref`, omit this entirely."
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
                    "Keep only the messages Microsoft reports as unread. Every returned row is "
                    + "checked here, so no read message reaches the answer. Whether Exchange also "
                    + "does the discarding depends on the dates: with a date bound it can, and a "
                    + "folder of thousands still fills `limit`; without one, this call reads the "
                    + "newest mail and discards as it goes, so a folder holding few unread among "
                    + "many can exhaust its internal scan first. `capped` says when that "
                    + "happened. Compare what comes back with `unread_items`, for how much this "
                    + "call reached."
                )
            ),
        ] = False,
        received_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only messages received on or after this point, inclusive. Two shapes: a "
                    + "date, `2026-03-04`, which opens at the first instant of that whole UTC "
                    + "day; or a moment, `2026-03-04T09:00:00Z`, which opens at the second it "
                    + "names. A moment carrying no zone is read as UTC, so a user's early morning "
                    + "or late evening can fall on the neighbouring UTC day either way. Alone, it "
                    + 'leaves the window open at the newest end, which is what "since Monday" '
                    + "asks for. For a window that has already closed, pair it with "
                    + "`received_before`."
                )
            ),
        ] = None,
        received_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only messages received on or before this point, inclusive, in the same two "
                    + "shapes `received_after` takes. A date closes at the END of that UTC day, "
                    + "so the whole of it is inside the bound and the same date in both bounds "
                    + "lists that one day; a moment closes at the second it names. Pass it for "
                    + 'any window that has already closed — "the mail from March", "what came in '
                    + 'last week", "everything older than five days" — because the rows arrive '
                    + "newest first: `received_after` alone reaches such a window only after "
                    + "spending `limit` on everything newer than it, and reports that as `capped` "
                    + "rather than as an error."
                )
            ),
        ] = None,
        from_address: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only messages from this sender, by SMTP address — one address, never a "
                    + "display name and never a list. `bob@vance.example` works; `Bob Vance` is "
                    + 'refused, because it would match nothing and read as "no mail from Bob". '
                    + "Call outlook_find_recipient to turn a name into an address. Matching is "
                    + "case-insensitive, as SMTP addresses are. Pair it with a date bound when "
                    + "the question has one: with a date, Microsoft 365 does the discarding, so a "
                    + "quiet sender is found in a busy folder; without one, this call reads the "
                    + "newest mail and discards as it goes, so it can stop early and say `capped`. "
                    + "For the sender's name, mail merely mentioning them, or mail they only "
                    + "received, use outlook_search_mail."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=(
                    f"How many messages to return, at most {MAX_RESULTS}. They are the newest "
                    + "that many of the folder, or of the window the two date bounds open. Paging "
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
            received_before=received_before,
            from_address=from_address,
            limit=limit,
        )

    _one_folder_at_a_time(mcp.add_tool(outlook_list_mail))


def _one_folder_at_a_time(tool: Tool) -> None:
    """Say "one of these two, not both" in the schema, which a Python signature cannot express.

    FastMCP validates arguments against the signature rather than this schema, so the runtime
    refusal stays.
    """
    tool.parameters["not"] = {"required": list(FOLDER_ARGUMENTS)}
