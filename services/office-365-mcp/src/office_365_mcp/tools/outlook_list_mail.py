from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
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
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    READ_ONLY,
    graph_client_for_caller,
    graph_mailbox,
)
from office_365_mcp.shared.window import closes_at, opens_at, runs_backwards

TOOL_NAME = "outlook_list_mail"

STEP_FOLDER = "mail_folder"
STEP_MESSAGES = "folder_messages"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read", "Mail.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"folder": "inbox"}

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this folder, so this tool cannot list any message in it. If "
    + "the caller used `folder_ref`, the handle is well formed. The folder was most likely "
    + "deleted, moved, or copied. Outlook can give a moved or copied folder a new id. So call "
    + "outlook_browse_folders again and take the `uri` it reports now. If the caller used "
    + "`folder`, this mailbox has no folder by that well-known name. `archive` and `clutter` in "
    + "particular are absent from a mailbox that never had them. `outlook_browse_folders` lists "
    + "what this mailbox actually has. Retrying with the same argument will fail identically."
)

MAX_RESULTS = 50

DEFAULT_FOLDER: WellKnownFolder = "inbox"

_FOLDER_FIELDS: tuple[str, ...] = ("displayName", "totalItemCount", "unreadItemCount")

_NEWEST_FIRST = "receivedDateTime desc"

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_FolderQuery = MailFolderItemRequestBuilder.MailFolderItemRequestBuilderGetQueryParameters
_MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = (
    "Lists the newest messages of one mail folder, newest received first, in the signed-in "
    "user's own mailbox or, with `mailbox`, a shared or delegated one."
)

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
    folder_name: str | None = Field(
        description="The folder's display name, or null if Graph did not report one."
    )
    total_items: int | None = Field(
        description=(
            "How many items of every kind the folder holds, or null if Graph did not report it."
        )
    )
    unread_items: int | None = Field(
        description="How many of `total_items` are unread, or null if Graph did not report it."
    )
    messages: list[MailSummary] = Field(
        description=(
            "The rows for this call, one per message; pass a row's `uri` to outlook_read_mail "
            "for the full message."
        )
    )
    capped: bool = Field(
        description=(
            "True if more of the folder or date window remains beyond what this call returned."
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
    mailbox: str | None = None,
) -> FolderMessages:
    assert 1 <= limit <= MAX_RESULTS, f"limit must be within 1..{MAX_RESULTS}, got {limit}"
    _refuse_a_backwards_window(received_after, received_before)
    sender = _one_address(from_address)
    address = _folder_address(folder, folder_ref)
    reached = graph_mailbox(client, mailbox)

    with graph_errors(TOOL_NAME):
        with graph_step(STEP_FOLDER):
            found = await reached.mail_folders.by_mail_folder_id(address).get(
                request_configuration=RequestConfiguration[_FolderQuery](
                    query_parameters=_FolderQuery(select=list(_FOLDER_FIELDS))
                )
            )
        assert found is not None, "Graph answered a mail folder read with no folder"
        headers = _headers()
        with graph_step(STEP_MESSAGES):
            first_page = await reached.mail_folders.by_mail_folder_id(address).messages.get(
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
    if runs_backwards(received_after, received_before):
        raise ToolError(_WINDOW_RUNS_BACKWARDS)


def _query_filter(
    received_after: date | datetime | None,
    received_before: date | datetime | None,
    *,
    unread_only: bool,
    sender: str | None,
) -> str | None:
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
    terms: list[str] = []
    if received_after is not None:
        terms.append(f"receivedDateTime ge {_wire(opens_at(received_after))}")
    if received_before is not None:
        terms.append(f"receivedDateTime {_closing_term(received_before)}")
    if not terms:
        return None
    return " and ".join(terms)


def _closing_term(received_before: date | datetime) -> str:
    if isinstance(received_before, datetime):
        return f"le {_wire(closes_at(received_before))}"
    return f"lt {_wire(opens_at(received_before + timedelta(days=1)))}"


def _wire(instant: datetime) -> str:
    if instant.microsecond:
        return f"{instant:%Y-%m-%dT%H:%M:%S.%f}Z"
    return f"{instant:%Y-%m-%dT%H:%M:%SZ}"


def _keeps(*, unread_only: bool, sender: str | None) -> Callable[[Message], bool] | None:
    checks: list[Callable[[Message], bool]] = []
    if unread_only:
        checks.append(_is_unread)
    if sender is not None:
        checks.append(_sent_by(sender))
    if not checks:
        return None
    return lambda message: all(check(message) for check in checks)


def _is_unread(message: Message) -> bool:
    return message.is_read is False


def _sent_by(sender: str) -> Callable[[Message], bool]:
    wanted = sender.casefold()

    def sent_by(message: Message) -> bool:
        recorded = message.from_.email_address if message.from_ is not None else None
        return recorded is not None and (recorded.address or "").casefold() == wanted

    return sent_by


def _one_address(from_address: str | None) -> str | None:
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
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
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
                    "Which well-known folder to list (`inbox`, `sentitems`, `drafts`, "
                    "`archive`, `deleteditems`, `junkemail`, or `clutter`); alternative to "
                    "`folder_ref`."
                )
            ),
        ] = DEFAULT_FOLDER,
        folder_ref: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder to list, as the `uri` handle from an outlook_browse_folders "
                    "result; alternative to `folder`."
                ),
            ),
        ] = None,
        unread_only: Annotated[
            bool,
            Field(description="Keeps only messages that are unread."),
        ] = False,
        received_after: Annotated[
            date | datetime | None,
            Field(description="Only messages received at or after this date or moment (UTC)."),
        ] = None,
        received_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only messages received at or before this date or moment (UTC), inclusive."
                )
            ),
        ] = None,
        from_address: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only messages from this sender, as one SMTP address, never a display name."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=f"How many messages to return, at most {MAX_RESULTS}.",
            ),
        ] = 25,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
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
            mailbox=mailbox,
        )
