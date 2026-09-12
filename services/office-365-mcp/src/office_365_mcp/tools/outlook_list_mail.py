"""`outlook_list_mail` — the newest messages of one folder, in receipt order, exhaustively.

Where `outlook_search_mail` asks Microsoft's index a question and takes back whatever order the
index answers in, this walks one folder's own message collection. This means newest received
first, every message in it, and a bound Exchange evaluates, rather than an index. That is the
reason both tools exist. "Find the mail about the invoice" is a search. "what came in today",
"the last ten", and "what is still unread" are this.

**The ordering construction is the whole of the query, not a detail of it.** Microsoft publishes
three rules for combining `$orderby` with `$filter` on a message collection
(https://learn.microsoft.com/en-us/graph/api/user-list-messages). First, every property in
`$orderby` must also appear in `$filter`. Second, the two must name them in the same order.
Third, the ordered properties must come before any property that is not ordered. Graph answers a
violation with `InefficientFilter`, a 400 that reads like a bad argument and is really a query
the tool composed. So:

* `$orderby=receivedDateTime desc`, always and unconditionally. Receipt order is what this tool
  promises, and a promise kept only for some arguments is worse than no promise.
* `$filter` opens with the bounds on `receivedDateTime` that `received_after` and
  `received_before` ask for. Microsoft publishes that two-sided range against this very
  collection — `~/me/mailFolders/inbox/messages?$filter=ReceivedDateTime ge 2017-04-01 and
  receivedDateTime lt 2017-05-01`
  (https://learn.microsoft.com/en-us/graph/filter-query-parameter) — so the shape is documented,
  and no literal is quoted, because that page also rules that DateTimeOffset values are not.
* `isRead` and `from/emailAddress/address` may follow, and only ever follow. They are unordered,
  which the third rule permits so long as every ordered property precedes them — and forbids
  outright if `$filter` names no ordered property at all, which is the first rule. So they go on
  when a date bound did, and are left off when none did. `_query_filter` is the one place that
  decides this, and the tests pin the sequence, because a refactor that reorders those lines
  composes an `InefficientFilter` out of arguments that are each individually fine.

An ordered property first in `$filter`, the same one property in `$orderby`, and any unordered
term strictly after it. So no combination of these arguments can break a rule.
`InefficientFilter` is impossible by construction, not merely untriggered by the cases somebody
thought to try.

**The unordered terms are an optimization and never the filter.** `unread_only` and
`from_address` are re-checked on every row by `_keeps`, whether or not their term reached the
wire. Microsoft documents that an unsupported query parameter or combination can fail *silently*
(https://learn.microsoft.com/en-us/graph/query-parameters), and a dropped `isRead eq false` would
otherwise put read mail into an answer that asked for unread — a confident wrong answer, where
re-checking degrades instead to the honest partial one `capped` already describes. Both
properties are already in `SUMMARY_FIELDS`, so the check costs nothing. What the `$filter` term
buys is Exchange doing the discarding, so a scan looking for four messages from one person does
not run out against a folder of thousands.

**One step of that is an inference, and it is the second rule.** Rules one and three hold by
quotation: the only ordered property is in `$filter` whenever anything else is, and every
unordered term is placed after it, which is what the third rule asks for in as many words. Rule
two is about the *order* two properties appear in, and Microsoft
publishes no example where one property appears twice in `$filter` beside an `$orderby` — so
reading a repeated property as one property is this file's reading of the rule, not Microsoft's
words. Two things carry it. The documented two-sided range above is the same construction minus
the `$orderby`, and Microsoft's own `$orderby`-plus-`$filter` example on the query-parameters
page (`$filter=Subject eq 'welcome' and importance eq 'normal'&$orderby=subject,importance,
receivedDateTime desc`) orders a property `$filter` never names, which breaks rule one as
written. So the service enforces something looser than the published text, and every direction
that looseness runs is a direction this construction is already inside.

**`received_before` exists because receipt order runs the wrong way for a past window.** The
answer starts at the newest message and `limit` bounds it, so `received_after` alone reaches a
window only by reading everything newer than it first. "The mail from March", asked in September,
spends the whole of `limit` on the summer and reports `capped` — a slice of the wrong months that
names no error. Closing the window at the newest end moves the read to the days that were asked
about.

**Both bounds take a date or a moment, and `shared/window.py` says which instant either means.**
That module is the one place the whole surface agrees on it — the five tools that take a window
reach three unrelated Graph surfaces and must not disagree about what a caller's bound MEANS. The
rule is that the value named is inside the window, so a bare date is a whole UTC day at either
end. Only the spelling is this file's: a date closes with `lt` at the start of the following day,
which is the shape of Microsoft's own April-2017 example and needs no precision chosen, while a
named moment closes with `le` at itself, being exact already. A `le` on a date's own last instant
would have to pick a precision and would drop whatever arrived after it.

**Two Graph calls, and this tool reads the folder first.** `totalItemCount` and `unreadItemCount`
sit on the folder object, where Microsoft recommends reading them over counting a folder's
messages with `$count` and `$filter`. They are what make a short answer legible. Twenty-five
messages back against an `unreadItemCount` of seventy is a slice. Three back with `capped` false
is the lot. They count items of every type, so they bound the messages in a folder rather than
counting them.

**`Prefer: IdType="ImmutableId"` on the message listing.** The ids it mints become handles. A
handle built from a `RestId` dies the moment Outlook files the message. Inbox rules and retention
can file a message with no warning. After that, `outlook_read_mail` answers a 404 that a model
reads as "deleted". `outlook_read_mail` sends the same header on the way in, so the two agree
about which id space a handle is spelled in. The header travels on a collection built per
request. This tool hands the same collection to `collect_pages`: kiota's
`RequestConfiguration.headers` default is one object shared process-wide, and `PageIterator`
starts from an empty one. So a preference set only once leaks onto every other Graph call, and
still fails to reach page two.

**This tool never reads `$skip` out of an `@odata.nextLink`.** Microsoft documents that its value
counts every item the service enumerated to build that page, not the items handed back. So it can
exceed the page size on page one. A caller that treats it as "how far I got" skips messages. This
tool follows the link whole, and never parses it.
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

# The default call, and the one that reaches Graph without a handle from a previous response.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"folder": "inbox"}

# The default 404 advice says to check that the id came from a tool response, verbatim. That
# advice does not fit either way in here. A folder handle is this connector's own. A well-known
# name is a name, not an id.
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

# The two ways in, spelled once: the schema constraint and the refusal below must name the same
# pair. A rename that reached only one of them leaves a client refused by a rule the schema does
# not publish.
FOLDER_ARGUMENTS: tuple[str, str] = ("folder", "folder_ref")

# Everything the answer reads off the folder, and nothing else. No `id`: the argument that
# reached this call already addresses the folder. Reading the id back only invites a second,
# hand-spelled handle.
_FOLDER_FIELDS: tuple[str, ...] = ("displayName", "totalItemCount", "unreadItemCount")

# Unconditional, and the only `$orderby` this tool has. See the module docstring.
_NEWEST_FIRST = "receivedDateTime desc"

# The first instant of a day, in UTC. Both bounds are built from it: `received_after` opens at the
# start of its own day, and `received_before` closes at the start of the following one.
_START_OF_DAY = "T00:00:00Z"

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

    A `folder` left at its default is indistinguishable here from one a caller spelled out.
    FastMCP fills a default in before the body runs. So this function catches every explicit
    `folder` beside a `folder_ref`. The schema's own constraint catches the pair a client sent as
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


def _refuse_a_backwards_window(
    received_after: date | datetime | None, received_before: date | datetime | None
) -> None:
    """A window that runs backwards matches nothing, and Graph answers it with an empty page.

    So the refusal happens here. Left to Graph, "no mail in that window" and "those two bounds are
    the wrong way round" are the same answer, and only one of them is worth reporting to anybody.

    `runs_backwards` compares the two as instants, which is the only way to order them once one
    can be a date and the other a moment — Python refuses that comparison outright.
    """
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

    Two kinds of term live here and the difference is the whole design. The `receivedDateTime`
    bounds are the property `$orderby` takes, so they are ordered. `isRead` and
    `from/emailAddress/address` are not, and Microsoft's third rule puts every ordered property in
    `$filter` before any unordered one. So the date terms are built first and the rest appended
    after, and the tests assert that sequence over every combination of these arguments: a
    refactor that reorders these lines composes an `InefficientFilter` out of arguments that are
    individually fine.

    The unordered terms go on ONLY when a date term did. Alone beside `$orderby=receivedDateTime`
    they break the first rule — the ordered property would not appear in `$filter` at all — and
    that request is a published 400. This is why they are an optimization and never the filter:
    `_keeps` re-checks both of them on the rows regardless, so the answer is the same whether the
    term went on the wire, was honoured, or was silently dropped. What the term buys is Exchange
    doing the discarding, so a scan looking for four messages from one person does not run out
    against a folder of thousands.
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

    Two terms at most and both of them on `receivedDateTime`, the very property `$orderby` takes.
    Microsoft publishes this exact two-sided range against this exact collection; see the module
    docstring.

    `shared/window.py` owns what a bound MEANS — the value a caller names is inside the window —
    and this function owns only how OData spells it, which is the half that cannot be shared: a
    date closes with `lt` at the start of the following day, and a moment closes with `le` at
    itself. Both are the same promise. `lt` on the next day is Microsoft's own convention for a
    date window and needs no precision chosen; `le` on a named second is exact already.

    No literal is quoted, because Microsoft rules that a DateTimeOffset in a `$filter` is not.
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
    """`lt` the day after a date, `le` a named moment. See `_received_within`."""
    if isinstance(received_before, datetime):
        return f"le {_wire(closes_at(received_before))}"
    return f"lt {_wire(opens_at(received_before + timedelta(days=1)))}"


def _wire(instant: datetime) -> str:
    """An instant as the ISO-8601 UTC literal Graph documents, keeping whatever precision it has.

    TRAP, and it is silent in BOTH directions. Truncating to whole seconds moves the bound the
    caller named. On the lower bound it moves it earlier, so mail the caller excluded is let in.
    On the upper bound it moves it earlier too, so mail the caller included is shut out — and a
    row lost at the boundary is invisible: the answer is well formed, `capped` is false, and
    nothing says a message was dropped. Graph states `receivedDateTime` in ISO 8601 and its own
    sample timestamps carry seven fractional digits, so the precision is Graph's to keep, not
    this function's to round.

    A bare date resolves to midnight and renders unchanged, so a date-bounded query still sends
    the same bytes it always did.
    """
    if instant.microsecond:
        return f"{instant:%Y-%m-%dT%H:%M:%S.%f}Z"
    return f"{instant:%Y-%m-%dT%H:%M:%SZ}"


def _keeps(*, unread_only: bool, sender: str | None) -> Callable[[Message], bool] | None:
    """What every returned row must satisfy, or None when the caller asked for no narrowing.

    This runs always, never only when `_query_filter` left a term off. Microsoft documents that an
    unsupported query parameter or combination can fail *silently*, and a dropped `isRead eq false`
    would otherwise put read mail in an answer that asked for unread — a confident wrong answer,
    where this instead degrades to the honest partial one `capped` already describes. Both
    properties are in `SUMMARY_FIELDS`, so the check costs nothing on the wire.
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
    """`isRead` false, and not merely absent: a message Graph said nothing about is not evidence
    of an unread one. `unread_only` is a claim about the rows it keeps."""
    return message.is_read is False


def _sent_by(sender: str) -> Callable[[Message], bool]:
    """Whether the message came from this address, compared case-insensitively.

    An SMTP address is case-insensitive, and the casing on a message is whatever the sender's own
    server wrote, not the casing the caller filtered with. Comparing exactly would drop a row
    Exchange itself considers a match. A message Graph recorded no sender for is not a match: like
    `_is_unread`, this is a claim about the rows kept, not a benefit of the doubt.
    """
    wanted = sender.casefold()

    def sent_by(message: Message) -> bool:
        recorded = message.from_.email_address if message.from_ is not None else None
        return recorded is not None and (recorded.address or "").casefold() == wanted

    return sent_by


def _one_address(from_address: str | None) -> str | None:
    """The argument as one SMTP address, or a refusal.

    A display name reaches Graph as an address that matches nothing, and `eq` answers that with an
    empty page rather than an error — "no mail from Bob" for a caller who spelled Bob's name.
    """
    if from_address is None:
        return None
    candidate = from_address.strip()
    if ONE_ADDRESS.match(candidate) is None:
        raise ToolError(_NOT_ONE_ADDRESS)
    return candidate


def _summary(message: Message) -> MailSummary:
    """The listing's own id becomes the handle, which the `Prefer` header makes an immutable one —
    no exchange to make, unlike a `$search` hit."""
    assert message.id is not None, "Graph returned a message with no id"
    return MailSummary.from_message(message, message_id=message.id)


def _headers() -> HeadersCollection:
    """Built per request: kiota's `RequestConfiguration.headers` defaults to one collection
    shared by every configuration in the process. So a preference added to it leaks onto every
    Graph call. This tool hands the same collection to `collect_pages`, whose `PageIterator`
    otherwise starts from an empty one and fetches page two in the other id space."""
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

    The runtime refusal stays. FastMCP validates arguments against the signature, not against
    this schema. So a client that ignores the constraint still receives the refusal at runtime.
    """
    tool.parameters["not"] = {"required": list(FOLDER_ARGUMENTS)}
