import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.tools import Tool
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.categories import LIST_CATEGORIES_GUARD
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.shared.mail import MailImportance
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm, Confirmed
from office_365_mcp.tools import outlook_draft_reply_all as replier
from office_365_mcp.tools.outlook_draft_reply_all import MailReplyAllDraft

_MESSAGE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

_DRAFT_ID = "AAMkAGI2SYNTHETIC-reply-draft-0001="

_MESSAGE_REF = MailMessageHandle(_MESSAGE_ID).uri

_CREATE = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/createReplyAll"
_FILL = "/me/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D"

_WEB_LINK = "https://outlook.office365.invalid/owa/?ItemID=synthetic-reply-all-draft"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"
_PAM = "pam@example.invalid"
_BOB = "bob@example.invalid"
_CAROL = "carol@example.invalid"

_SUBJECT = "RE: Invoice 4471"
_BODY = "<p>Friday works for all of us.</p>"

_SEEDED = "<div>From: Ada Lovelace<br>Sent: Monday<br>Can we all meet Friday?</div>"

_REFUSED: dict[str, object] = {"error": {"code": "ErrorAccessDenied", "message": "denied"}}

_SHARED_MAILBOX = "alex@example.invalid"
_SHARED_MESSAGE = f"/users/{_SHARED_MAILBOX}/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"
_SHARED_CREATE = f"{_SHARED_MESSAGE}/createReplyAll"
_SHARED_FILL = f"/users/{_SHARED_MAILBOX}/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D"

_NOT_CREATED = "No draft was created."


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOT_CREATED


async def _never_asked(question: str, about: str) -> Confirmed:
    raise AssertionError(f"a person was asked {question!r} about {about!r}")


async def _asks_the_client(question: str, about: str) -> Confirmed:
    assert question and about
    return InputRequiredResult(input_requests={}, request_state=about)


def _recipient(name: str | None, address: str) -> dict[str, object]:
    return {"emailAddress": {"name": name, "address": address}}


def _draft(
    *,
    to: Sequence[Mapping[str, object]] = (),
    cc: Sequence[Mapping[str, object]] = (),
    subject: str | None = _SUBJECT,
    content: str | None = _SEEDED,
    importance: str | None = "normal",
    categories: Sequence[str] = (),
    web_link: str | None = _WEB_LINK,
) -> dict[str, object]:
    return {
        "id": _DRAFT_ID,
        "isDraft": True,
        "subject": subject,
        "toRecipients": [
            dict(one)
            for one in (to or [_recipient("Ada Lovelace", _ADA), _recipient("Grace", _GRACE)])
        ],
        "ccRecipients": [dict(one) for one in cc],
        "body": None if content is None else {"contentType": "html", "content": content},
        "importance": importance,
        "categories": list(categories),
        "webLink": web_link,
    }


def _creates(
    graph: respx.MockRouter, payload: dict[str, object] | None = None, path: str = _CREATE
) -> respx.Route:
    return graph.post(path).mock(
        return_value=httpx.Response(201, json=payload if payload is not None else _draft())
    )


def _fills(
    graph: respx.MockRouter, payload: dict[str, object] | None = None, path: str = _FILL
) -> respx.Route:
    return graph.patch(path).mock(
        return_value=httpx.Response(
            200, json=payload if payload is not None else _draft(content=_BODY)
        )
    )


def _original(
    *,
    subject: str | None = "Invoice 4471",
    sender: str | None = _ADA,
    reply_to: Sequence[str] = (),
    to: Sequence[str] = (_GRACE, _PAM),
    cc: Sequence[str] = (_BOB,),
) -> dict[str, object]:
    return {
        "id": _MESSAGE_ID,
        "subject": subject,
        "from": None if sender is None else _recipient("Ada Lovelace", sender),
        "replyTo": [_recipient(None, address) for address in reply_to],
        "toRecipients": [_recipient(None, address) for address in to],
        "ccRecipients": [_recipient(None, address) for address in cc],
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.get(_SHARED_MESSAGE).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _original())
    )


def _shared_writes(graph: respx.MockRouter) -> respx.Route:
    _ = _fills(graph, path=_SHARED_FILL)
    return _creates(graph, path=_SHARED_CREATE)


def _methods(graph: respx.MockRouter) -> list[str]:
    return [call.request.method for call in cast("Sequence[Call]", graph.calls)]


def _written(graph: respx.MockRouter) -> list[str]:
    return [method for method in _methods(graph) if method != "GET"]


async def _reply_all(client: GraphServiceClient, **overrides: object) -> MailReplyAllDraft:
    answer = await replier.draft_reply_all(
        client,
        message_ref=cast("str", overrides.get("message_ref", _MESSAGE_REF)),
        body_html=cast("str", overrides.get("body_html", _BODY)),
        confirm=cast("Confirm", overrides.get("confirm", _never_asked)),
        cc=cast("Sequence[str]", overrides.get("cc", ())),
        importance=cast("MailImportance | None", overrides.get("importance")),
        categories=cast("Sequence[str]", overrides.get("categories", ())),
        mailbox=cast("str | None", overrides.get("mailbox")),
    )
    assert isinstance(answer, MailReplyAllDraft), "the confirmation asked instead of answering"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _addressed(sent: Mapping[str, object], field: str) -> list[str]:
    recipients = cast("list[dict[str, object]]", sent.get(field, []))
    return [
        cast("str", cast("dict[str, object]", recipient["emailAddress"])["address"])
        for recipient in recipients
    ]


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    replier.register(mcp, transport)
    tool = await mcp.get_tool(replier.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _properties(parameters: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", parameters["properties"])


class TestWhatItSendsToGraph:
    async def test_the_draft_is_created_on_the_reply_all_route_and_then_filled(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)

        _ = await _reply_all(client)

        assert create.call_count == 1
        assert fill.call_count == 1
        assert _methods(graph) == ["POST", "PATCH"]

    async def test_the_create_carries_no_comment_and_no_recipients(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        _ = _fills(graph)

        _ = await _reply_all(client, cc=[_CAROL])

        assert not [key for key in _sent(create) if "comment" in key.casefold()]
        assert not [key for key in _sent(create) if "recipient" in key.casefold()]

    async def test_the_fill_names_only_the_body_when_nothing_else_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = _fills(graph)

        _ = await _reply_all(client)

        assert set(_sent(fill)) == {"@odata.type", "body"}

    async def test_the_body_reaches_the_draft_as_html(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = _fills(graph)

        _ = await _reply_all(client, body_html="<p>Read https://payments.invalid/pay first.</p>")

        body = cast("dict[str, object]", _sent(fill)["body"])
        assert body["contentType"] == "html"
        assert body["content"] == "<p>Read https://payments.invalid/pay first.</p>"

    async def test_an_added_cc_joins_the_cc_that_microsoft_stored_on_the_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _draft(cc=[_recipient("Bob", _BOB)]))
        fill = _fills(graph)

        _ = await _reply_all(client, cc=[_CAROL, _PAM])

        assert _addressed(_sent(fill), "ccRecipients") == [_BOB, _CAROL, _PAM]
        assert "toRecipients" not in _sent(fill)

    async def test_an_added_cc_that_is_already_on_the_draft_reaches_graph_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(
            graph,
            _draft(to=[_recipient("Ada Lovelace", _ADA)], cc=[_recipient("Grace", _GRACE)]),
        )
        fill = _fills(graph)

        _ = await _reply_all(client, cc=[_GRACE.upper(), _PAM])

        assert _addressed(_sent(fill), "ccRecipients") == [_GRACE, _PAM]

    async def test_an_added_cc_that_is_already_in_to_leaves_the_cc_untouched(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(
            graph,
            _draft(to=[_recipient("Ada Lovelace", _ADA)], cc=[_recipient("Grace", _GRACE)]),
        )
        fill = _fills(graph)

        _ = await _reply_all(client, cc=[_ADA.upper()])

        assert set(_sent(fill)) == {"@odata.type", "body"}

    async def test_the_importance_and_the_categories_reach_the_fill(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = _fills(graph)

        _ = await _reply_all(client, importance="high", categories=["Finance"])

        assert _sent(fill)["importance"] == "high"
        assert _sent(fill)["categories"] == ["Finance"]

    async def test_categories_that_differ_only_in_case_reach_graph_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = _fills(graph)

        _ = await _reply_all(client, categories=["Budget", "BUDGET"])

        assert _sent(fill)["categories"] == ["Budget"]

    async def test_neither_write_offers_an_attachment_or_a_blind_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)

        _ = await _reply_all(client, cc=[_CAROL])

        keys = [key.casefold() for key in (*_sent(create), *_sent(fill))]
        assert not [key for key in keys if "attach" in key]
        assert not [key for key in keys if "bcc" in key]

    async def test_both_writes_ask_for_immutable_ids(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)

        _ = await _reply_all(client)

        for route in (create, fill):
            assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    async def test_it_never_sends_the_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)
        send = graph.post(f"{_FILL}/send").mock(return_value=httpx.Response(202))

        _ = await _reply_all(client)

        assert send.call_count == 0

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = graph.post(_CREATE).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _reply_all(client)

        assert create.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_fill_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = graph.patch(_FILL).mock(return_value=httpx.Response(503))

        answer = await _reply_all(client)

        assert fill.call_count == 1
        assert answer.body_written is False


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "ref",
        [
            "outlook:///drafts/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            "outlook:///folders/AQMkADAwSYNTHETIC",
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "AAMkAGI2SYNTHETIC-immutable-0001=",
            "https://outlook.office365.invalid/owa/?ItemID=synthetic",
            "Invoice 4471",
        ],
    )
    async def test_a_message_ref_that_is_not_a_message_handle_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, ref: str
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="outlook:///messages"):
            _ = await _reply_all(client, message_ref=ref)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "address",
        [
            "Carol <carol@example.invalid>",
            "carol@example.invalid, pam@example.invalid",
            "Carol",
            "carol@",
            "   ",
        ],
    )
    async def test_a_cc_entry_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="in `cc`") as raised:
            _ = await _reply_all(client, cc=[address])

        assert "outlook_find_recipient" in str(raised.value)
        assert len(graph.calls) == 0

    async def test_surrounding_whitespace_is_trimmed_rather_than_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = _fills(graph)

        _ = await _reply_all(client, cc=[f"  {_CAROL}  "])

        assert _addressed(_sent(fill), "ccRecipients") == [_CAROL]

    async def test_an_address_repeated_in_cc_is_refused_whatever_its_case(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="twice in `cc`") as raised:
            _ = await _reply_all(client, cc=[_CAROL, _CAROL.upper()])

        assert _NOT_CREATED in str(raised.value)
        assert (
            "If you call this tool again with the same arguments, the call will fail the same way."
        ) in str(raised.value)
        assert len(graph.calls) == 0

    async def test_a_repeat_that_differs_only_by_padding_is_refused_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="twice in `cc`"):
            _ = await _reply_all(client, cc=[_CAROL, f"  {_CAROL}  "])

        assert len(graph.calls) == 0

    async def test_a_bad_entry_is_refused_as_a_bad_address_and_not_as_a_repeat(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="not one email address") as raised:
            _ = await _reply_all(client, cc=["Carol", "Carol"])

        assert "twice" not in str(raised.value)
        assert len(graph.calls) == 0


class TestTheSchemaItPublishes:
    async def test_it_takes_six_arguments_and_the_message_and_text_are_required(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(_properties(parameters)) == {
            "message_ref",
            "body_html",
            "cc",
            "importance",
            "categories",
            "mailbox",
        }
        assert cast("Sequence[str]", parameters["required"]) == ["message_ref", "body_html"]

    @pytest.mark.parametrize("word", ["bcc", "blind", "attach", "file", "mode"])
    async def test_no_argument_offers_a_blind_copy_a_file_or_a_mode(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert not [name for name in _properties(parameters) if word in name.casefold()]

    async def test_no_argument_replaces_the_to_list_that_microsoft_chooses(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert "to" not in _properties(parameters)

    async def test_cc_defaults_to_nobody_and_has_no_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        cc = _properties(parameters)["cc"]
        assert cc["default"] == []
        assert "maxItems" not in cc

    async def test_cc_says_an_address_already_on_the_draft_is_not_added_again(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        described = cast("str", _properties(parameters)["cc"]["description"])
        assert "An address that is already on the draft is not added again." in described
        assert 15 <= len(described.split()) <= 60

    async def test_a_category_name_cannot_be_empty(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        items = cast("Mapping[str, object]", _properties(parameters)["categories"]["items"])
        assert items["minLength"] == 1

    async def test_a_blank_category_name_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError):
            _ = await tool.run({**replier.GRAPH_CALL_EXAMPLE, "categories": [""]})

        assert len(graph.calls) == 0, "a blank category name reached Graph"

    async def test_the_category_argument_promises_the_lister_only_where_it_exists(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        described = cast("str", _properties(parameters)["categories"]["description"])
        assert LIST_CATEGORIES_GUARD in described
        assert "outlook_list_categories" not in described.replace(LIST_CATEGORIES_GUARD, "")


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_these_writes(self) -> None:
        assert replier.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")
        assert replier.CHANGE_SHOWN_BY == ("outlook_list_mail",)

    def test_the_two_writes_are_named_as_their_own_steps(self) -> None:
        assert replier.STEP_CREATE_REPLY_ALL == "create_reply_all"
        assert replier.STEP_FILL_REPLY_ALL == "fill_reply_all"

    async def test_it_announces_itself_as_a_write_that_destroys_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_who_a_reply_all_reaches_and_who_chose_them(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "A reply-all goes to everyone on the original message." in description
        assert "The sender of the original message chose that list." in description
        assert "outlook_send_draft shows every address before anything is sent." in description

    async def test_the_description_says_it_cannot_send_and_names_the_sibling(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "This tool cannot send mail, and it offers no Bcc." in description
        assert "outlook_draft_reply is the tool for a reply to the sender only" in description

    async def test_the_description_says_it_cannot_add_files_and_where_the_user_adds_one(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "It cannot add files to the draft." in description
        assert (
            "If the user asks to attach a file, tell them to add it in Outlook before they send "
            + "the draft."
        ) in description

    async def test_the_description_says_a_shared_mailbox_needs_agreement_and_the_own_one_does_not(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it changes a shared or delegated mailbox. "
            + "It changes the user's own mailbox without a question."
        ) in description
        assert "`mailbox`" in description

    def test_a_missing_message_is_never_blamed_on_a_folder_move(self) -> None:
        assert "If a message moves to another folder of this mailbox, its handle does not" in (
            replier.GRAPH_NOT_FOUND
        )
        assert "outlook_search_mail" in replier.GRAPH_NOT_FOUND


def _questions() -> tuple[list[str], Confirm]:
    asked: list[str] = []

    async def capturing(question: str, about: str) -> Confirmed:
        asked.append(question)
        assert about
        return None

    return asked, capturing


class TestThePersonBeforeTheDraftIsCreated:
    async def test_the_signed_in_users_own_mailbox_asks_nobody_and_reads_nothing_first(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)

        _ = await _reply_all(client, confirm=_never_asked)

        assert _methods(graph) == ["POST", "PATCH"]

    async def test_a_shared_mailbox_is_asked_about_once_and_gets_one_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        create = _shared_writes(graph)
        asked, capturing = _questions()

        answer = await _reply_all(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert len(asked) == 1
        assert read.call_count == 1
        assert create.call_count == 1
        assert _written(graph) == ["POST", "PATCH"]
        assert answer.body_written is True

    async def test_a_refusal_writes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)

        with pytest.raises(ToolError, match=_NOT_CREATED):
            _ = await _reply_all(client, mailbox=_SHARED_MAILBOX, confirm=_refuses)

        assert _written(graph) == []

    async def test_a_question_the_client_must_carry_writes_nothing_and_is_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)

        answer = await replier.draft_reply_all(
            client,
            message_ref=_MESSAGE_REF,
            body_html=_BODY,
            confirm=_asks_the_client,
            mailbox=_SHARED_MAILBOX,
        )

        assert isinstance(answer, InputRequiredResult)
        assert _written(graph) == []

    async def test_a_message_that_is_gone_is_a_not_found_before_any_question_or_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_SHARED_MESSAGE).mock(return_value=httpx.Response(404, json=_REFUSED))
        _ = _shared_writes(graph)

        with pytest.raises(GraphNotFound):
            _ = await _reply_all(client, mailbox=_SHARED_MAILBOX, confirm=_never_asked)

        assert _written(graph) == []

    async def test_the_read_selects_every_field_that_names_a_recipient(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        _ = _shared_writes(graph)

        _ = await _reply_all(client, mailbox=_SHARED_MAILBOX, confirm=_agrees)

        selected = set(read.calls.last.request.url.params["$select"].split(","))
        assert selected == {"subject", "from", "replyTo", "toRecipients", "ccRecipients"}

    async def test_the_question_lists_every_address_the_draft_goes_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply_all(client, cc=[_CAROL], mailbox=_SHARED_MAILBOX, confirm=capturing)

        (question,) = asked
        assert "Create a reply-all draft in the mailbox 'alex@example.invalid'?" in question
        assert "The reply-all is to the message 'Invoice 4471'." in question
        assert "That mailbox is not the signed-in user's own." in question
        assert f"The draft is addressed to {_ADA}, {_GRACE}, {_PAM}." in question
        assert f"It is copied to {_BOB}, {_CAROL}." in question
        assert "That is 5 addresses in all." in question
        assert "Nothing is sent." in question
        assert "The draft appears in that mailbox, and anyone with access to it can see it." in (
            question
        )

    async def test_a_cc_that_is_already_on_the_original_cc_is_listed_and_counted_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _original(to=[_PAM], cc=[_GRACE]))
        _ = _shared_writes(graph)
        asked: list[str] = []
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            bound.append(about)
            return None

        for cc in ([_GRACE.upper()], []):
            _ = await _reply_all(client, cc=cc, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert asked[0].count(_GRACE) == 1
        assert f"It is copied to {_GRACE}." in asked[0]
        assert "That is 3 addresses in all." in asked[0]
        assert asked[0] == asked[1]
        assert bound[0] == bound[1]

    async def test_a_cc_that_is_already_addressed_is_left_out_of_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply_all(client, cc=[_PAM.upper()], mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert f"It is copied to {_BOB}." in asked[0]
        assert "That is 4 addresses in all." in asked[0]

    async def test_the_question_names_the_reply_to_address_over_the_sender(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _original(reply_to=["invoices@example.invalid"]))
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply_all(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert f"addressed to invoices@example.invalid, {_GRACE}, {_PAM}." in asked[0]
        assert _ADA not in asked[0]

    async def test_the_question_names_the_importance_and_the_categories(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply_all(
            client,
            importance="high",
            categories=["Finance", "Urgent"],
            mailbox=_SHARED_MAILBOX,
            confirm=capturing,
        )

        assert "It has high importance." in asked[0]
        assert "It is tagged Finance, Urgent." in asked[0]

    async def test_the_question_names_categories_that_differ_only_in_case_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply_all(
            client, categories=["Budget", "BUDGET"], mailbox=_SHARED_MAILBOX, confirm=capturing
        )

        assert "It is tagged Budget." in asked[0]
        assert "BUDGET" not in asked[0]

    async def test_a_message_with_no_subject_and_nobody_on_it_is_still_described(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _original(subject=None, sender=None, to=(), cc=()))
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply_all(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert "The reply-all is to the message with no subject." in asked[0]
        assert "addressed to an address that Microsoft chooses." in asked[0]
        assert "copied to" not in asked[0]

    async def test_a_changed_body_or_cc_binds_the_agreement_to_a_different_state(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        changes: tuple[dict[str, object], ...] = (
            {},
            {},
            {"body_html": "<p>Other.</p>"},
            {"cc": [_CAROL]},
            {"importance": "low"},
        )
        for overrides in changes:
            _ = await _reply_all(client, mailbox=_SHARED_MAILBOX, confirm=capturing, **overrides)

        assert bound[0] == bound[1]
        assert len({*bound}) == 4

    async def test_categories_that_differ_only_in_case_bind_the_state_of_the_deduped_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        _ = await _reply_all(
            client, categories=["Budget"], mailbox=_SHARED_MAILBOX, confirm=capturing
        )
        _ = await _reply_all(
            client, categories=["Budget", "BUDGET"], mailbox=_SHARED_MAILBOX, confirm=capturing
        )

        assert bound[0] == bound[1]


class TestWhatItAnswers:
    async def test_it_lists_every_recipient_microsoft_stored_and_counts_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(
            graph,
            _draft(
                to=[_recipient("Ada Lovelace", _ADA), _recipient("Grace", _GRACE)],
                cc=[_recipient("Pam Beesly", _PAM), _recipient("Carol", _CAROL)],
            ),
        )

        answer = await _reply_all(client, cc=[_CAROL])

        assert [address.address for address in answer.to] == [_ADA, _GRACE]
        assert [address.address for address in answer.cc] == [_PAM, _CAROL]
        assert answer.recipient_count == 4

    async def test_the_draft_is_read_off_the_fill_and_never_echoed_from_the_arguments(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(
            graph,
            _draft(
                subject="RE: Invoice 4471 (stored)",
                content="<p>Stored text.</p>",
                importance="low",
                categories=["Stored"],
            ),
        )

        answer = await _reply_all(client, importance="high", categories=["Finance"])

        assert answer.subject == "RE: Invoice 4471 (stored)"
        assert answer.body == "<p>Stored text.</p>"
        assert answer.importance == "low"
        assert answer.categories == ["Stored"]
        assert answer.body_written is True
        assert answer.failure is None

    async def test_the_handle_is_the_message_handle_of_the_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)

        answer = await _reply_all(client)

        handle = mail_message_handle(answer.uri)
        assert handle is not None
        assert handle.message_id == _DRAFT_ID
        assert answer.web_link == _WEB_LINK

    def test_no_attachment_or_blind_copy_is_addressable_in_the_answer_at_all(self) -> None:
        fields = [name.casefold() for name in MailReplyAllDraft.model_fields]
        assert not [name for name in fields if "attach" in name]
        assert not [name for name in fields if "bcc" in name]


class TestWhenTheTextCannotBeWritten:
    async def test_a_refused_fill_answers_the_draft_it_left_behind_rather_than_raising(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _draft(cc=[_recipient("Pam Beesly", _PAM)]))
        _ = graph.patch(_FILL).mock(return_value=httpx.Response(403, json=_REFUSED))

        answer = await _reply_all(client, cc=[_CAROL], body_html="<p>Wire the payment.</p>")

        assert answer.body_written is False
        assert answer.failure is not None
        assert answer.body is None
        assert [address.address for address in answer.cc] == [_PAM]
        assert answer.recipient_count == 3
        handle = mail_message_handle(answer.uri)
        assert handle is not None
        assert handle.message_id == _DRAFT_ID


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden_and_nothing_is_filled(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = graph.post(_CREATE).mock(return_value=httpx.Response(403, json=_REFUSED))
        fill = _fills(graph)

        with pytest.raises(GraphForbidden):
            _ = await _reply_all(client)

        assert create.call_count == 1
        assert fill.call_count == 0
