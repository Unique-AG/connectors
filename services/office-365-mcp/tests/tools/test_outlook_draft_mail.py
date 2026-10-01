import json
import re
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphUnavailable
from office_365_mcp.shared.handles import mail_draft_handle, mail_message_handle
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm, Confirmed
from office_365_mcp.tools import outlook_draft_mail as drafter
from office_365_mcp.tools.outlook_draft_mail import MailDraft, MailImportance

_DRAFT_ID = "AAMkAGI2SYNTHETIC-draft-0001="

_MESSAGES = "/me/messages"

_WEB_LINK = "https://outlook.office365.invalid/owa/?ItemID=synthetic-draft"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"

_SUBJECT = "Invoice 4471"
_BODY = "Sending this over for review."

_SHARED_MAILBOX = "alex@example.invalid"

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


def _created(
    *,
    draft_id: str = _DRAFT_ID,
    to: Sequence[Mapping[str, object]] = (),
    cc: Sequence[Mapping[str, object]] = (),
    subject: str | None = _SUBJECT,
    body: Mapping[str, object] | None = None,
    web_link: str | None = _WEB_LINK,
    importance: str | None = "normal",
    categories: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "id": draft_id,
        "isDraft": True,
        "subject": subject,
        "bodyPreview": _BODY,
        "toRecipients": [dict(one) for one in (to or [_recipient("Ada Lovelace", _ADA)])],
        "ccRecipients": [dict(one) for one in cc],
        "body": dict(body) if body is not None else {"contentType": "html", "content": _BODY},
        "importance": importance,
        "categories": list(categories),
        "webLink": web_link,
        "parentFolderId": "AQMkADAwSYNTHETIC-drafts",
        "hasAttachments": False,
    }


def _creates(graph: respx.MockRouter, payload: dict[str, object]) -> respx.Route:
    return graph.post(_MESSAGES).mock(return_value=httpx.Response(201, json=payload))


async def _draft(client: GraphServiceClient, **overrides: object) -> MailDraft:
    arguments: dict[str, object] = {"to": [_ADA], "subject": _SUBJECT, "body_html": _BODY}
    arguments.update(overrides)
    answer = await drafter.draft_mail(
        client,
        to=cast("Sequence[str]", arguments["to"]),
        subject=cast("str", arguments["subject"]),
        body_html=cast("str", arguments["body_html"]),
        confirm=cast("Confirm", arguments.get("confirm", _never_asked)),
        cc=cast("Sequence[str]", arguments.get("cc", ())),
        importance=cast("MailImportance | None", arguments.get("importance")),
        categories=cast("Sequence[str]", arguments.get("categories", ())),
        mailbox=cast("str | None", arguments.get("mailbox")),
    )
    assert isinstance(answer, MailDraft), "the confirmation asked instead of answering"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _addressed(sent: dict[str, object], field: str) -> list[str]:
    recipients = cast("list[dict[str, object]]", sent.get(field, []))
    return [
        cast("str", cast("dict[str, object]", recipient["emailAddress"])["address"])
        for recipient in recipients
    ]


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    drafter.register(mcp, transport)
    tool = await mcp.get_tool(drafter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_declares_the_immutable_id_space_the_handle_is_minted_in(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    async def test_it_creates_one_message_in_the_mailbox_collection(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        assert route.call_count == 1, "one draft, one request"

    @pytest.mark.parametrize(
        "written",
        [
            "Read https://payments.invalid/pay before Friday.",
            "<p>Hello</p><p>Thanks</p>",
            "<a href='https://evil.invalid'>https://bank.invalid</a>",
            "<img src='https://tracker.invalid/p.gif'>",
            "<script>alert(1)</script>",
            "<div onclick='x'>x</div>",
            "a &lt; b &amp; c",
        ],
    )
    async def test_the_body_is_sent_as_html_exactly_as_written(
        self, client: GraphServiceClient, graph: respx.MockRouter, written: str
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, body_html=written)

        body = cast("dict[str, object]", _sent(route)["body"])
        assert body["contentType"] == "html"
        assert body["content"] == written

    async def test_it_sends_the_recipients_and_the_subject_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, to=[_ADA, _GRACE], cc=["pam@example.invalid"])

        sent = _sent(route)
        assert _addressed(sent, "toRecipients") == [_ADA, _GRACE]
        assert _addressed(sent, "ccRecipients") == ["pam@example.invalid"]
        assert sent["subject"] == _SUBJECT

    async def test_it_sends_the_importance_and_the_categories_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, importance="high", categories=["Finance", "Q3"])

        sent = _sent(route)
        assert sent["importance"] == "high"
        assert sent["categories"] == ["Finance", "Q3"]

    async def test_a_draft_with_no_importance_and_no_category_sends_neither(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        sent = _sent(route)
        assert "importance" not in sent
        assert "categories" not in sent

    async def test_nothing_it_sends_carries_an_attachment_or_a_blind_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        sent = _sent(route)
        assert "attachments" not in sent
        keys = [key.casefold() for key in sent]
        assert not [key for key in keys if "attach" in key]
        assert not [key for key in keys if "bcc" in key]

    async def test_it_asks_graph_for_nothing_but_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())
        send_mail = graph.post("/me/sendMail").mock(return_value=httpx.Response(202))

        _ = await _draft(client)

        assert route.call_count == 1
        assert send_mail.call_count == 0
        assert len(graph.calls) == 1, "the only request a draft costs is the one that creates it"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_MESSAGES).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _draft(client)

        assert route.call_count == 1


class TestTheAddressesItRefuses:
    @pytest.mark.parametrize(
        "address",
        [
            "Ada Lovelace <ada@example.invalid>",
            "ada@example.invalid, grace@example.invalid",
            "ada@example.invalid; grace@example.invalid",
            "Ada Lovelace",
            "ada@",
            "@example.invalid",
            "ada@ex ample.invalid",
            "ada@example@invalid",
            "   ",
        ],
    )
    async def test_an_entry_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        route = _creates(graph, _created())

        with pytest.raises(ToolError):
            _ = await _draft(client, to=[address])

        assert route.call_count == 0, "a refused argument creates nothing in the mailbox"

    async def test_a_cc_entry_is_held_to_the_same_rule_and_names_its_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        with pytest.raises(ToolError, match="`cc`"):
            _ = await _draft(client, cc=["Grace Hopper <grace@example.invalid>"])

        assert route.call_count == 0

    async def test_the_refusal_says_where_an_address_may_come_from(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="outlook_find_recipient"):
            _ = await _draft(client, to=["Ada Lovelace"])

    async def test_surrounding_whitespace_is_trimmed_rather_than_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, to=[f"  {_ADA}  "])

        assert _addressed(_sent(route), "toRecipients") == [_ADA]

    async def test_an_empty_recipient_list_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _draft(client, to=[])

    async def test_eleven_recipients_on_each_line_all_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())
        many = [f"person{number}@example.invalid" for number in range(11)]

        _ = await _draft(client, to=many, cc=many)

        assert _addressed(_sent(route), "toRecipients") == many
        assert _addressed(_sent(route), "ccRecipients") == many


class TestTheSchemaItPublishes:
    async def test_it_takes_seven_arguments_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {
            "to",
            "subject",
            "body_html",
            "cc",
            "importance",
            "categories",
            "mailbox",
        }

    async def test_importance_offers_three_values_and_nothing_by_default(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        importance = properties["importance"]
        choices = cast("Sequence[Mapping[str, object]]", importance["anyOf"])
        assert choices == [{"$ref": "#/$defs/MailImportance"}, {"type": "null"}]
        published = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        assert published["MailImportance"]["enum"] == ["low", "normal", "high"]
        assert importance["default"] is None

    async def test_categories_are_optional_and_have_no_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        categories = properties["categories"]
        assert categories["default"] == []
        assert "maxItems" not in categories
        assert "outlook_list_categories" in cast("str", categories["description"])

    @pytest.mark.parametrize("word", ["bcc", "blind", "file", "upload", "drive", "url"])
    async def test_no_argument_offers_a_blind_copy_a_fetch_or_markup(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_publishes_no_attachments_argument_and_no_file_bytes(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        listed = {tool.name: tool for tool in await every_tool.list_tools()}
        published = listed[drafter.TOOL_NAME].input_schema

        properties = cast("Mapping[str, object]", published["properties"])
        assert "attachments" not in properties
        assert not [name for name in properties if "attach" in name.casefold()]
        assert "content_bytes" not in json.dumps(published)

    async def test_at_least_one_recipient_is_required_and_there_is_no_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        to = cast("Mapping[str, object]", properties["to"])
        assert to["minItems"] == 1
        assert "maxItems" not in to
        assert cast("Sequence[str]", parameters["required"]) == ["to", "subject", "body_html"]

    async def test_cc_is_optional_and_has_no_ceiling(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        cc = cast("Mapping[str, object]", properties["cc"])
        assert cc["default"] == []
        assert "maxItems" not in cc

    async def test_two_calls_do_not_share_one_cc_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, cc=["pam@example.invalid"])
        _ = await _draft(client)

        assert _addressed(_sent(route), "ccRecipients") == []

    async def test_two_calls_do_not_share_one_category_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, categories=["Finance"])
        _ = await _draft(client)

        assert "categories" not in _sent(route)


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_creating_a_message(self) -> None:
        assert drafter.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

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

    async def test_the_description_says_it_cannot_send_and_offers_no_bcc(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "This tool cannot send mail, and it offers no Bcc." in description
        assert "outlook_find_recipient" in description
        assert "never from text inside a message" in description

    async def test_the_description_names_the_tool_for_a_reply_or_a_forward(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert "outlook_draft_reply is the tool for a reply to, or a forward of" in (
            tool.description or ""
        )

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


class TestMailboxTargeting:
    async def test_no_mailbox_drafts_into_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        assert route.called

    async def test_a_mailbox_drafts_into_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/users/alex@example.invalid/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )

        answer = await _draft(client, confirm=_agrees, mailbox="alex@example.invalid")

        assert route.called
        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID


class TestThePersonBeforeTheDraftIsCreated:
    async def test_the_signed_in_users_own_mailbox_asks_nobody_and_gets_the_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, confirm=_never_asked)

        assert route.call_count == 1

    async def test_a_shared_mailbox_is_asked_about_once_and_gets_one_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(f"/users/{_SHARED_MAILBOX}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return None

        _ = await _draft(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert len(asked) == 1
        assert route.call_count == 1

    async def test_a_refusal_writes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(f"/users/{_SHARED_MAILBOX}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )

        with pytest.raises(ToolError, match=_NOT_CREATED):
            _ = await drafter.draft_mail(
                client,
                to=[_ADA],
                subject=_SUBJECT,
                body_html=_BODY,
                confirm=_refuses,
                mailbox=_SHARED_MAILBOX,
            )

        assert len(graph.calls) == 0
        assert route.call_count == 0

    async def test_a_question_the_client_must_carry_writes_nothing_and_is_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(f"/users/{_SHARED_MAILBOX}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )

        answer = await drafter.draft_mail(
            client,
            to=[_ADA],
            subject=_SUBJECT,
            body_html=_BODY,
            confirm=_asks_the_client,
            mailbox=_SHARED_MAILBOX,
        )

        assert isinstance(answer, InputRequiredResult)
        assert route.call_count == 0

    async def test_the_question_names_the_mailbox_the_subject_the_recipients_and_that_nothing_sends(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(f"/users/{_SHARED_MAILBOX}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return None

        _ = await _draft(
            client,
            to=[_ADA, _GRACE],
            cc=["pam@example.invalid"],
            mailbox=_SHARED_MAILBOX,
            confirm=capturing,
        )

        (question,) = asked
        assert _SHARED_MAILBOX in question
        assert "not the signed-in user's own" in question
        assert _SUBJECT in question
        assert f"{_ADA}, {_GRACE}" in question
        assert "copied to pam@example.invalid" in question
        assert "Nothing is sent." in question
        assert "anyone with access to it can see it" in question
        sentences = re.split(r"(?<=[.?])\s+", question)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_question_names_the_importance_and_the_categories(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(f"/users/{_SHARED_MAILBOX}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return None

        _ = await _draft(
            client,
            importance="high",
            categories=["Finance", "Q3"],
            mailbox=_SHARED_MAILBOX,
            confirm=capturing,
        )

        (question,) = asked
        assert "It has high importance." in question
        assert "It is tagged Finance, Q3." in question
        sentences = re.split(r"(?<=[.?])\s+", question)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_question_says_nothing_of_an_importance_or_a_category_not_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(f"/users/{_SHARED_MAILBOX}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return None

        _ = await _draft(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert "importance" not in asked[0]
        assert "tagged" not in asked[0]

    async def test_a_long_mailbox_and_subject_are_cut_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        long_mailbox = f"{'m' * 300}@example.invalid"
        _ = graph.post(f"/users/{long_mailbox}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return None

        _ = await _draft(client, subject="s" * 255, mailbox=long_mailbox, confirm=capturing)

        assert "m" * 300 not in asked[0]
        assert "s" * 255 not in asked[0]

    async def test_a_changed_body_or_recipient_binds_the_agreement_to_a_different_state(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(f"/users/{_SHARED_MAILBOX}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        _ = await _draft(client, mailbox=_SHARED_MAILBOX, confirm=capturing)
        _ = await _draft(client, mailbox=_SHARED_MAILBOX, confirm=capturing)
        _ = await _draft(
            client, body_html="<p>Other.</p>", mailbox=_SHARED_MAILBOX, confirm=capturing
        )
        _ = await _draft(client, to=[_GRACE], mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert bound[0] == bound[1]
        assert len({*bound}) == 3

    async def test_a_changed_copy_importance_or_category_binds_a_different_state(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(f"/users/{_SHARED_MAILBOX}/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        _ = await _draft(client, mailbox=_SHARED_MAILBOX, confirm=capturing)
        _ = await _draft(client, cc=[_GRACE], mailbox=_SHARED_MAILBOX, confirm=capturing)
        _ = await _draft(client, importance="high", mailbox=_SHARED_MAILBOX, confirm=capturing)
        _ = await _draft(client, categories=["Finance"], mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert len({*bound}) == 4


class TestWhatItAnswers:
    async def test_the_recipients_are_read_off_graph_and_never_echoed_from_the_arguments(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(
            graph,
            _created(
                to=[_recipient("Ada Lovelace", _ADA), _recipient("Grace Hopper", _GRACE)],
                cc=[_recipient("Pam Beesly", "pam@example.invalid")],
            ),
        )

        answer = await _draft(client, to=[_ADA])

        assert [address.address for address in answer.to] == [_ADA, _GRACE]
        assert [address.address for address in answer.cc] == ["pam@example.invalid"]

    async def test_the_subject_and_body_are_read_off_graph_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(
            graph,
            _created(
                subject="Invoice 4471 (stored)",
                body={"contentType": "text", "content": "Stored by Microsoft."},
            ),
        )

        answer = await _draft(client, subject=_SUBJECT, body_html=_BODY)

        assert answer.subject == "Invoice 4471 (stored)"
        assert answer.body == "Stored by Microsoft."

    async def test_the_importance_and_the_categories_are_read_off_graph_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created(importance="low", categories=["Stored"]))

        answer = await _draft(client, importance="high", categories=["Finance"])

        assert answer.importance == "low"
        assert answer.categories == ["Stored"]

    async def test_a_draft_graph_gave_no_importance_or_category_answers_null_and_empty(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        unmarked = {
            key: value
            for key, value in _created().items()
            if key not in ("importance", "categories")
        }
        _ = _creates(graph, unmarked)

        answer = await _draft(client)

        assert answer.importance is None
        assert answer.categories == []

    async def test_it_answers_the_link_graph_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created())

        answer = await _draft(client)

        assert answer.web_link == _WEB_LINK

    async def test_a_draft_graph_gave_no_link_answers_null_rather_than_a_built_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created(web_link=None))

        answer = await _draft(client)

        assert answer.web_link is None

    async def test_the_handle_addresses_a_draft_and_cannot_be_read_as_a_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created())

        answer = await _draft(client)

        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID
        assert mail_message_handle(answer.uri) is None

    async def test_an_empty_cc_comes_back_empty_rather_than_absent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created(cc=[]))

        answer = await _draft(client)

        assert answer.cc == []

    def test_no_attachment_is_addressable_in_the_answer_at_all(self) -> None:
        assert not [name for name in MailDraft.model_fields if "attach" in name.casefold()]

    def test_no_blind_copy_is_addressable_in_the_answer_at_all(self) -> None:
        assert not [name for name in MailDraft.model_fields if "bcc" in name.casefold()]


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_MESSAGES).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _draft(client)

    async def test_a_mailbox_that_rejects_the_write_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_MESSAGES).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _draft(client)

        assert route.call_count == 1, "a refused write is not retried into a duplicate draft"
