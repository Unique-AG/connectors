"""Every response body here is synthesised. None came from a real mailbox."""

from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared import identity
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.tools.outlook_read_mail import MAX_BODY_CHARACTERS, MailMessage, read_mail
from office_365_mcp.tools.outlook_search_mail import SearchCriteria, search_mail

from .conftest import ME

_IMMUTABLE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_REST_ID = "AAMkAGI2SYNTHETIC-rest-0001="

# The SDK re-encodes the id for the URL, so this is what the decoded handle comes back as.
_PATH = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"

_HANDLE = MailMessageHandle(_IMMUTABLE_ID)

_QUOTED_THREAD = "Sent on Friday, Ada wrote: the invoice never arrived."


def _body(content: str, *, content_type: str = "text") -> dict[str, object]:
    return {"contentType": content_type, "content": content}


def _payload(
    *,
    body: dict[str, object] | None = None,
    unique_body: dict[str, object] | None = None,
    cc: Sequence[Mapping[str, object]] = (),
    sent_at: str | None = "2026-03-04T09:12:44Z",
) -> dict[str, object]:
    return {
        "id": _IMMUTABLE_ID,
        "subject": "Invoice 4471",
        "bodyPreview": "Sent on Friday, Ada wrote: the invoice never arrived.",
        "from": {"emailAddress": {"name": "Bob Vance", "address": "bob@vance.invalid"}},
        "toRecipients": [{"emailAddress": {"name": "Ada", "address": "ada@contoso.invalid"}}],
        "ccRecipients": [dict(recipient) for recipient in cc],
        "receivedDateTime": "2026-03-04T09:15:00Z",
        "sentDateTime": sent_at,
        "isRead": False,
        "hasAttachments": True,
        "parentFolderId": "AQMkADAwSYNTHETIC-folder",
        "webLink": "https://outlook.office365.invalid/owa/?ItemID=synthetic",
        "body": body,
        "uniqueBody": unique_body,
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object]) -> respx.Route:
    return graph.get(_PATH).mock(return_value=httpx.Response(200, json=payload))


class TestWhatItAsksGraphFor:
    async def test_it_selects_both_bodies_beside_the_shared_summary_fields(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph returns neither `uniqueBody` nor `body` on a projection that does not name them."""
        route = _reads(graph, _payload(body=_body("hello")))

        _ = await read_mail(client, handle=_HANDLE)

        selected = route.calls.last.request.url.params["$select"]
        assert "uniqueBody" in selected
        assert "body" in selected
        assert "ccRecipients" in selected
        assert "sentDateTime" in selected
        assert "bodyPreview" in selected, "the summary fields every mail tool agrees on"

    async def test_it_never_selects_the_routing_headers(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Not asking is the whole of the control: there is no filter downstream of `$select`."""
        route = _reads(graph, _payload(body=_body("hello")))

        _ = await read_mail(client, handle=_HANDLE)

        assert "internetMessageHeaders" not in route.calls.last.request.url.params["$select"]

    async def test_it_prefers_a_text_body_and_declares_the_immutable_id_space(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Without the id-space preference Graph reads the path id as a `RestId` and 404s the
        immutable id the handle carries."""
        route = _reads(graph, _payload(body=_body("hello")))

        _ = await read_mail(client, handle=_HANDLE)

        preferences = route.calls.last.request.headers["prefer"]
        assert 'outlook.body-content-type="text"' in preferences
        assert 'IdType="ImmutableId"' in preferences

    async def test_it_never_asks_graph_to_stop_sanitising_the_html(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reads(graph, _payload(body=_body("hello")))

        _ = await read_mail(client, handle=_HANDLE)

        assert "allow-unsafe-html" not in route.calls.last.request.headers["prefer"]

    async def test_the_preferences_are_not_added_to_every_other_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """kiota's `RequestConfiguration.headers` defaults to one `HeadersCollection` shared by
        every configuration in the process, so a header added to the default leaks everywhere.

        `shared/identity.py`'s `GET /me` is the witness because it passes a `RequestConfiguration`
        of its own; a call passing none would keep passing while the leak came back.
        """
        _ = _reads(graph, _payload(body=_body("hello")))
        profile = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))

        _ = await read_mail(client, handle=_HANDLE)
        _ = await identity.signed_in_user(client)

        assert "prefer" not in profile.calls.last.request.headers

    async def test_it_reads_the_message_the_handle_names_in_one_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reads(graph, _payload(body=_body("hello")))

        _ = await read_mail(client, handle=_HANDLE)

        assert route.call_count == 1, "one message, one request"


class TestWhichBodyItReturns:
    async def test_the_unique_body_is_preferred_and_reported_as_the_new_part(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            _payload(
                body=_body(f"Paid it this morning.\n\n{_QUOTED_THREAD}"),
                unique_body=_body("Paid it this morning."),
            ),
        )

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body == "Paid it this morning."
        assert answer.body_is_the_new_part is True

    async def test_a_message_with_no_unique_body_falls_back_to_the_whole_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        whole = f"Paid it this morning.\n\n{_QUOTED_THREAD}"
        _ = _reads(graph, _payload(body=_body(whole)))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body == whole
        assert answer.body_is_the_new_part is False

    async def test_an_empty_unique_body_falls_back_rather_than_answering_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph returns an empty `uniqueBody` for a message that only forwards or only quotes, and
        answering with it would hide every word Outlook shows the user."""
        _ = _reads(graph, _payload(body=_body(_QUOTED_THREAD), unique_body=_body("   ")))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body == _QUOTED_THREAD
        assert answer.body_is_the_new_part is False

    async def test_a_message_with_neither_body_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload())

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body is None
        assert answer.body_characters == 0
        assert answer.body_truncated is False
        assert answer.body_is_the_new_part is False


class TestWhetherGraphConvertedTheBody:
    async def test_a_body_graph_reported_as_text_is_labelled_plain_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("Paid it this morning.", content_type="text")))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body_is_plain_text is True

    async def test_a_body_graph_left_as_html_is_not_labelled_plain_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The documented preference and the documented behaviour of this operation disagree, so
        the response decides and the request never does."""
        _ = _reads(graph, _payload(body=_body("<p>Paid it.</p>", content_type="html")))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body_is_plain_text is False

    async def test_the_markup_reaches_the_caller_exactly_as_graph_sent_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """No stripper of our own: one would turn a script block into sentences that read as prose
        the sender wrote."""
        markup = '<div><script>alert("pay me")</script><p>Paid it.</p></div>'
        _ = _reads(graph, _payload(body=_body(markup, content_type="html")))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body == markup

    async def test_the_body_that_was_used_is_the_one_whose_type_is_reported(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A converted `body` says nothing about an unconverted `uniqueBody`, and `uniqueBody` is
        what the answer carries."""
        _ = _reads(
            graph,
            _payload(
                body=_body("Paid it this morning.", content_type="text"),
                unique_body=_body("<p>Paid it.</p>", content_type="html"),
            ),
        )

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body == "<p>Paid it.</p>"
        assert answer.body_is_plain_text is False


class TestTheCapOnTheBody:
    async def test_a_body_over_the_cap_keeps_the_head_and_says_it_was_cut(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        content = "A" * MAX_BODY_CHARACTERS + "TAIL"
        _ = _reads(graph, _payload(body=_body(content)))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body == "A" * MAX_BODY_CHARACTERS
        assert answer.body_truncated is True

    async def test_it_reports_the_length_the_message_had_before_truncation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        content = "A" * (MAX_BODY_CHARACTERS + 4)
        _ = _reads(graph, _payload(body=_body(content)))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body_characters == MAX_BODY_CHARACTERS + 4

    async def test_a_body_exactly_at_the_cap_is_whole(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        content = "A" * MAX_BODY_CHARACTERS
        _ = _reads(graph, _payload(body=_body(content)))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.body == content
        assert answer.body_truncated is False
        assert answer.body_characters == MAX_BODY_CHARACTERS


class TestWhatItAnswers:
    async def test_it_carries_the_handle_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("hello")))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.uri == _HANDLE.uri

    async def test_it_reports_cc_and_the_time_the_sender_sent_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            _payload(
                body=_body("hello"),
                cc=[{"emailAddress": {"name": "Pam", "address": "pam@contoso.invalid"}}],
            ),
        )

        answer = await read_mail(client, handle=_HANDLE)

        assert [address.address for address in answer.cc] == ["pam@contoso.invalid"]
        assert answer.sent_at is not None
        assert answer.sent_at.startswith("2026-03-04T09:12:44")

    async def test_it_still_reports_everything_a_hit_already_carried(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("hello")))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.subject == "Invoice 4471"
        assert answer.sender is not None
        assert answer.sender.address == "bob@vance.invalid"
        assert [address.address for address in answer.to] == ["ada@contoso.invalid"]
        assert answer.received_at is not None
        assert answer.is_read is False
        assert answer.folder_id == "AQMkADAwSYNTHETIC-folder"
        assert answer.web_link == "https://outlook.office365.invalid/owa/?ItemID=synthetic"

    async def test_an_attachment_is_a_boolean_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("hello")))

        answer = await read_mail(client, handle=_HANDLE)

        assert answer.has_attachments is True
        assert not [name for name in MailMessage.model_fields if "attachment" in name.lower()][1:]

    def test_no_routing_header_is_addressable_in_the_answer_at_all(self) -> None:
        assert not [name for name in MailMessage.model_fields if "header" in name.lower()]


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "uri",
        [
            "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D",
            "outlook:///folders/AQMkADAwSYNTHETIC-folder",
            "outlook:///rules/SYNTHETIC-rule-0001",
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "AAMkAGI2SYNTHETIC-immutable-0001=",
            "https://outlook.office365.invalid/owa/?ItemID=synthetic",
            "Invoice 4471",
        ],
    )
    def test_a_uri_that_is_not_a_mail_message_handle_never_becomes_one(self, uri: str) -> None:
        """What the tool refuses on before it reaches Graph. A folder, a draft and a rule are
        addressable under the same scheme and none of them is a message."""
        assert mail_message_handle(uri) is None


class TestTheFailuresItPassesOn:
    async def test_a_message_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph answers 'deleted', 'never existed' and 'you may not see it' identically."""
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await read_mail(client, handle=_HANDLE)

    async def test_a_refused_read_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await read_mail(client, handle=_HANDLE)


class TestTheRoundTripFromASearchResult:
    async def test_a_hit_from_search_is_read_by_its_own_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Whatever `outlook_search_mail` puts in `uri`, this reader resolves with no part of it
        reassembled by hand. Which strings are handles at all is `shared/handles.py`'s question.
        """
        _ = graph.get("/me/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": _REST_ID,
                            "subject": "Invoice 4471",
                            "bodyPreview": "Sent on Friday, Ada wrote:",
                            "from": {
                                "emailAddress": {"name": "Bob", "address": "bob@vance.invalid"}
                            },
                            "toRecipients": [],
                            "receivedDateTime": "2026-03-04T09:15:00Z",
                            "isRead": False,
                            "hasAttachments": True,
                            "parentFolderId": "AQMkADAwSYNTHETIC-folder",
                            "webLink": "https://outlook.office365.invalid/owa/?ItemID=synthetic",
                        }
                    ]
                },
            )
        )
        _ = graph.post("/me/translateExchangeIds").mock(
            return_value=httpx.Response(
                200, json={"value": [{"sourceId": _REST_ID, "targetId": _IMMUTABLE_ID}]}
            )
        )
        route = _reads(graph, _payload(unique_body=_body("Paid it this morning.")))

        found = await search_mail(client, SearchCriteria(query="invoice"), limit=25)
        handle = mail_message_handle(found.messages[0].uri)
        assert handle is not None, "search produced a handle outlook_read_mail rejects"
        answer = await read_mail(client, handle=handle)

        assert route.called
        assert answer.uri == found.messages[0].uri
        assert answer.body == "Paid it this morning.", (
            "the point of the round trip: a hit has a preview, and this is where the text is"
        )
