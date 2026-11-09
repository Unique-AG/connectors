import base64
from collections.abc import Iterator
from datetime import date
from typing import cast

import httpx
import pytest
import respx
from fastmcp.client.client import CallToolResult
from fastmcp.exceptions import ToolError
from mcp.types import BlobResourceContents, EmbeddedResource, TextContent, TextResourceContents
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.conftest import RecordedSleeps
from tests.graph_fixtures import recorded_json, response, serve
from tests.tools.conftest import GRAPH_V1
from tests.tools.scenarios.mail_support import (
    advice_for,
    answer_of,
    answers,
    every_time,
    folder_listing,
    invoke,
    mail_message,
    methods_asked,
    paths_asked,
    refusal_of,
    search_of,
    serve_as,
    tool_description,
)
from tests.tools.scenarios.support import call

_INBOX = "/me/mailFolders/inbox"
_TEN_MEBIBYTES = 10 * 1024 * 1024


_NEVER_ENDING_PAGE: dict[str, object] = {
    "value": [],
    "@odata.nextLink": f"{GRAPH_V1}/me/mailFolders/inbox/messages?$skip=5",
}


def _column(found: object, name: str) -> list[str]:
    return [cast("str", row[0]) for row in _rows(found, name)]


def _rows(found: object, *columns: str) -> list[tuple[object, ...]]:
    messages = cast("list[dict[str, object]]", cast("dict[str, object]", found)["messages"])
    return [tuple(message[column] for column in columns) for message in messages]


def _a_person(name: str, address: str) -> dict[str, object]:
    return {
        "id": address,
        "displayName": name,
        "scoredEmailAddresses": [{"address": address, "relevanceScore": 9}],
        "personType": {"class": "Person", "subclass": "OrganizationUser"},
    }


def _attachment(kind: str, *, size: int | None) -> dict[str, object]:
    body: dict[str, object] = {
        "@odata.type": f"#microsoft.graph.{kind}",
        "id": "ATT1",
        "name": "Draft v2.pdf",
        "contentType": "application/pdf",
        "isInline": False,
    }
    if size is not None:
        body["size"] = size
    return body


async def _first_attachment(subject: str, limit: int) -> str:
    found = await call("outlook_search_mail", subject=subject, limit=limit)
    listed = await call("outlook_list_attachments", uri=_rows(found, "uri")[0][0])
    return cast("list[dict[str, str]]", listed["attachments"])[0]["uri"]


def _attachment_uri(message_id: str = "MSG1") -> str:
    return f"outlook:///messages/{message_id}/attachments/ATT1"


@pytest.fixture
def recorded_spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.shutdown()


class TestTheAssistantFindsAMessageFromWhatMiaRemembers:
    async def test_it_finds_a_message_by_sender_subject_and_attachment_together(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        found = await call(
            "outlook_search_mail",
            sender="Anna Meier",
            subject="Q3 budget review",
            has_attachments=True,
            limit=5,
        )

        assert _rows(found, "subject", "has_attachments") == [("RE: Q3 budget review", True)]
        asked = search_of(graph)
        assert 'from:"Anna Meier"' in asked
        assert 'subject:"Q3 budget review"' in asked

    async def test_it_narrows_a_search_to_a_time_window(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call(
            "outlook_search_mail",
            sender="Anna Meier",
            received_after=date(2026, 3, 1).isoformat(),
            received_before=date(2026, 3, 31).isoformat(),
            limit=5,
        )

        asked = search_of(graph)
        assert "received>=2026-03-01T00:00:00Z" in asked
        assert "received<2026-04-01T00:00:00Z" in asked

    async def test_it_lists_only_the_flagged_messages(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-flagged")

        found = await call("outlook_list_mail", flagged=True, limit=5)

        assert {
            flag["status"]
            for flag in cast(
                "list[dict[str, str]]",
                [message["flag"] for message in cast("list[dict[str, object]]", found["messages"])],
            )
        } == {"flagged"}
        assert len(cast("list[object]", found["messages"])) == 3

    @pytest.mark.parametrize(("limit", "more_may_exist"), [(5, True), (25, False)])
    async def test_a_result_that_fills_the_limit_says_that_more_messages_may_match(
        self, graph: respx.MockRouter, limit: int, more_may_exist: bool
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        found = await call("outlook_search_mail", query="Q3 budget review", limit=limit)

        assert len(cast("list[object]", found["messages"])) == 5
        assert found["more_may_exist"] is more_may_exist

    async def test_it_finds_mail_that_mia_sent_to_one_person_about_a_topic(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call("outlook_search_mail", to="Tom", query="offer", limit=5)

        asked = search_of(graph)
        assert "to:Tom" in asked
        assert "offer" in asked
        assert "participants:" not in asked

    async def test_it_gives_the_unread_count_of_the_folder_and_the_newest_unread_messages(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")

        found = await call("outlook_list_mail", unread_only=True, limit=3)

        assert found["unread_items"] == 23
        received = _column(found, "received_at")
        assert len(received) == 3
        assert received == sorted(received, reverse=True)
        assert {row[0] for row in _rows(found, "is_read")} == {False}

    async def test_it_shows_the_latest_message_of_the_person_that_the_name_finds(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(
            return_value=httpx.Response(200, json={"id": "me", "mail": "mia@example.test"})
        )
        _ = graph.get("/me/people").mock(
            return_value=httpx.Response(
                200, json={"value": [_a_person("Anna Meier", "anna@example.test")]}
            )
        )
        found = await call("outlook_find_recipient", query="Anna", limit=5)
        address = cast("list[dict[str, str]]", found["candidates"])[0]["address"]
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")

        latest = await call("outlook_list_mail", from_address=address, limit=1)

        assert _rows(latest, "subject") == [("Roadmap check",)]
        assert address == "anna@example.test"

    async def test_it_lists_the_junk_folder_and_reads_nothing_of_the_inbox(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-junk")

        found = await call("outlook_list_mail", folder="junkemail", limit=25)

        assert found["folder_name"] == "Junk Email"
        assert _rows(found, "subject") == [
            ("Cheap licences",),
            ("Free upgrade",),
            ("Prize offer",),
        ]
        assert [path for path in paths_asked(graph) if "inbox" in path] == []

    async def test_it_lists_mail_with_attachments_newest_first_and_skips_the_rest(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-flagged")

        found = await call("outlook_list_mail", has_attachments=True, limit=5)

        assert {row for row in _rows(found, "has_attachments")} == {(True,)}
        received = _column(found, "received_at")
        assert len(received) == 3
        assert received == sorted(received, reverse=True)

    async def test_a_search_with_a_filter_alone_is_refused_before_microsoft_is_asked(
        self, graph: respx.MockRouter
    ) -> None:
        advice = await advice_for("outlook_search_mail", has_attachments=True)

        assert "outlook_list_mail" in advice
        assert "needs at least one of" in advice
        assert graph.calls.call_count == 0

    @pytest.mark.parametrize("tool", ["outlook_search_mail", "outlook_list_mail"])
    async def test_a_window_given_back_to_front_is_refused_and_the_fix_is_named(
        self, graph: respx.MockRouter, tool: str
    ) -> None:
        extra = {"sender": "Anna"} if tool == "outlook_search_mail" else {"limit": 25}

        advice = await advice_for(
            tool, received_after="2026-03-20", received_before="2026-03-10", **extra
        )

        assert "Put the earlier" in advice
        assert "`received_after`" in advice
        assert graph.calls.call_count == 0

    async def test_the_window_in_the_right_order_is_searched_whole(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call(
            "outlook_search_mail",
            sender="Anna",
            received_after="2026-03-10",
            received_before="2026-03-20",
            limit=5,
        )

        asked = search_of(graph)
        assert "received>=2026-03-10T00:00:00Z" in asked
        assert "received<2026-03-21T00:00:00Z" in asked

    async def test_a_name_that_fits_two_people_is_put_to_the_user_and_no_mail_is_read(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(
            return_value=httpx.Response(200, json={"id": "me", "mail": "mia@example.test"})
        )
        _ = graph.get("/me/people").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _a_person("Anna Meier", "anna.meier@example.test"),
                        _a_person("Anna Weber", "anna.weber@example.test"),
                    ]
                },
            )
        )

        found = await call("outlook_find_recipient", query="Anna", limit=5)

        assert found["ambiguous"] is True
        assert [
            row["display_name"] for row in cast("list[dict[str, str]]", found["candidates"])
        ] == [
            "Anna Meier",
            "Anna Weber",
        ]
        assert [path for path in paths_asked(graph) if "messages" in path] == []

    async def test_a_folder_that_the_mailbox_lacks_is_explained_with_the_way_to_list_folders(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/mailFolders/archive").mock(
            side_effect=answers({"status": 404, "body": "error.ErrorItemNotFound.json"})
        )

        advice = await advice_for("outlook_list_mail", folder="archive", unread_only=True, limit=25)

        assert "this mailbox has no folder by that well-known name" in advice
        assert "outlook_browse_folders" in advice

    async def test_a_message_beyond_a_capped_listing_is_found_by_a_search(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        newest = await call("outlook_list_mail", limit=3)
        found = await call("outlook_search_mail", sender="Anna Meier", query="budget", limit=5)

        assert newest["capped"] is True
        assert ("Q3 budget review",) not in _rows(newest, "subject")
        assert ("Q3 budget review",) in _rows(found, "subject")
        assert "outlook_search_mail" in await tool_description("outlook_list_mail")

    async def test_the_matches_keep_the_order_of_the_index_and_each_holds_its_receipt_time(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_search_mail-budget")
        search = answer_of("rec-tool-outlook_search_mail-budget", "GET", "/me/messages")
        values = cast("list[object]", search["value"])
        _ = routes[("GET", "/me/messages")].mock(
            return_value=httpx.Response(200, json=search | {"value": values[::-1]})
        )

        found = await call("outlook_search_mail", sender="Anna Meier", query="budget", limit=5)

        received = _column(found, "received_at")
        assert received == sorted(received)


class TestAFolderThatMiaNames:
    async def test_it_lists_the_folder_by_the_handle_that_the_folder_list_reported(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_browse_folders-top")
        folders = await call("outlook_browse_folders", limit=50)
        projects = next(
            row
            for row in cast("list[dict[str, str]]", folders["folders"])
            if row["display_name"] == "seed-v1 Projects"
        )
        folder_id = projects["uri"].removeprefix("outlook:///folders/").replace("%3D", "=")
        _ = folder_listing(
            graph,
            f"/me/mailFolders/{folder_id}",
            *[mail_message(f"P{n}=", f"Project {n}", is_read=False) for n in range(4)],
            display_name=projects["display_name"],
        )

        found = await call(
            "outlook_list_mail", folder_ref=projects["uri"], unread_only=True, limit=25
        )

        assert found["folder_name"] == "seed-v1 Projects"
        assert len(cast("list[object]", found["messages"])) == 4
        assert [path for path in paths_asked(graph) if "/inbox" in path] == []

    async def test_a_folder_name_is_refused_in_place_of_a_folder_handle(
        self, graph: respx.MockRouter
    ) -> None:
        advice = await advice_for("outlook_list_mail", folder_ref="Projects", limit=25)

        assert "outlook_browse_folders" in advice
        assert "`folder_ref`" in advice
        assert graph.calls.call_count == 0

    async def test_a_handle_that_microsoft_no_longer_knows_leads_to_a_new_folder_list(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/mailFolders/OLDID=").mock(
            side_effect=answers({"status": 404, "body": "error.ErrorItemNotFound.json"})
        )
        stale = await advice_for(
            "outlook_list_mail", folder_ref="outlook:///folders/OLDID%3D", limit=25
        )
        _ = folder_listing(
            graph,
            "/me/mailFolders/NEWID=",
            mail_message("P1=", "Project plan"),
            display_name="Projects",
        )

        found = await call(
            "outlook_list_mail",
            folder_ref="outlook:///folders/NEWID%3D",
            unread_only=True,
            limit=25,
        )

        assert "call outlook_browse_folders again" in stale
        assert _rows(found, "subject") == [("Project plan",)]


class TestMailThatMiaSentToHerself:
    async def test_it_lists_the_messages_whose_sender_is_the_address_that_get_me_gave(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-get_me-profile")
        me = await call("get_me")
        routes = serve(graph, "rec-tool-outlook_list_mail-from-mia")

        found = await call(
            "outlook_list_mail",
            from_address=cast("str", me["email"]),
            received_after="2020-01-01",
            limit=5,
        )

        asked = routes[("GET", f"{_INBOX}/messages")].calls.last.request.url.params["$filter"]
        assert f"from/emailAddress/address eq '{me['email']}'" in asked
        assert _rows(found, "subject") == [("Note to self: call the printer",)]


def _described_then_downloaded(content: bytes) -> list[httpx.Response]:
    listed = _attachment("fileAttachment", size=len(content))
    return [
        httpx.Response(200, json=listed),
        httpx.Response(200, json=listed | {"contentBytes": base64.b64encode(content).decode()}),
    ]


class TestAMessageAndItsAttachments:
    async def test_it_reads_a_message_in_full_and_names_its_attachments_with_their_size(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")
        found = await call("outlook_search_mail", query="Q3 budget review", limit=5)
        with_file = next(
            message
            for message in cast("list[dict[str, object]]", found["messages"])
            if message["has_attachments"]
        )
        _ = serve(graph, "rec-tool-outlook_read_mail-with-attachment")

        message = await call("outlook_read_mail", uri=with_file["uri"])

        assert message["body"]
        attachments = cast("list[dict[str, object]]", message["attachments"])
        assert [(one["name"], one["kind"], one["size"]) for one in attachments] == [
            ("q3-numbers.csv", "file", 244)
        ]

    async def test_it_gives_an_excel_workbook_as_a_file_and_never_as_text(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_read_attachment-xlsx")
        uri = await _first_attachment("Budget workbook", 1)

        answer = await invoke("outlook_read_attachment", uri=uri)

        file = _the_file(answer)
        workbook = base64.b64decode(file.blob)
        assert file.mime_type == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert (workbook[:4], len(workbook)) == (b"PK\x03\x04", 2454)
        assert [block for block in answer.content if isinstance(block, TextContent)] == []

    async def test_it_gives_a_pdf_as_the_file_that_microsoft_sent(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_read_attachment-pdf")
        uri = await _first_attachment("Invoice Alpine Print", 3)

        answer = await invoke("outlook_read_attachment", uri=uri)

        file = _the_file(answer)
        document = base64.b64decode(file.blob)
        assert file.mime_type == "application/pdf"
        assert (document[:5], len(document)) == (b"%PDF-", 882)

    async def test_it_reads_an_attachment_of_exactly_ten_mebibytes(
        self, graph: respx.MockRouter
    ) -> None:
        content = b"x" * _TEN_MEBIBYTES
        _ = graph.get("/me/messages/MSG1/attachments/ATT1").mock(
            side_effect=_described_then_downloaded(content)
        )

        answer = await invoke("outlook_read_attachment", uri=_attachment_uri())

        assert len(base64.b64decode(_the_file(answer).blob)) == _TEN_MEBIBYTES

    @pytest.mark.parametrize(
        "size", [12 * 1024 * 1024, _TEN_MEBIBYTES + 1], ids=["12-MB", "one-byte-over"]
    )
    async def test_an_attachment_above_the_cap_is_refused_and_never_downloaded(
        self, graph: respx.MockRouter, size: int
    ) -> None:
        route = graph.get("/me/messages/MSG1/attachments/ATT1").mock(
            return_value=httpx.Response(200, json=_attachment("fileAttachment", size=size))
        )

        advice = await advice_for("outlook_read_attachment", uri=_attachment_uri())

        assert "open the message in Outlook" in advice
        assert "never sends part of a file" in advice
        assert route.call_count == 1

    @pytest.mark.parametrize(
        ("body", "next_step"),
        [
            (_attachment("itemAttachment", size=900), "open the attached item in Outlook"),
            (
                _attachment("referenceAttachment", size=0),
                "open the link from the message in Outlook",
            ),
            (_attachment("fileAttachment", size=None), "open the message in Outlook instead"),
        ],
        ids=["attached-message", "cloud-link", "size-not-reported"],
    )
    async def test_an_attachment_that_cannot_be_read_here_is_left_to_outlook(
        self, graph: respx.MockRouter, body: dict[str, object], next_step: str
    ) -> None:
        _ = graph.get("/me/messages/MSG1/attachments/ATT1").mock(
            return_value=httpx.Response(200, json=body)
        )

        advice = await advice_for("outlook_read_attachment", uri=_attachment_uri())

        assert next_step in advice

    async def test_an_attachment_that_arrives_with_no_content_is_asked_for_again_later(
        self, graph: respx.MockRouter
    ) -> None:
        listed = _attachment("fileAttachment", size=1024 * 1024)
        _ = graph.get("/me/messages/MSG1/attachments/ATT1").mock(
            side_effect=[httpx.Response(200, json=listed), httpx.Response(200, json=listed)]
        )

        advice = await advice_for("outlook_read_attachment", uri=_attachment_uri())

        assert "Ask for this attachment again later" in advice
        assert "open the message in Outlook" in advice

    async def test_an_instruction_inside_a_message_is_given_as_text_and_causes_no_write(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_read_mail-injection")
        stored = answer_of("rec-tool-outlook_read_mail-injection", "GET", "/me/messages/")

        message = await call("outlook_read_mail", uri=f"outlook:///messages/{stored['id']}")

        assert (
            cast("str", message["body"]).strip()
            == (cast("dict[str, str]", stored["body"])["content"])
        )
        assert methods_asked(graph) == {"GET"}
        assert "untrusted data" in await tool_description("outlook_read_mail")


def _the_file(answer: CallToolResult) -> BlobResourceContents:
    (block,) = answer.content
    assert isinstance(block, EmbeddedResource)
    assert isinstance(block.resource, BlobResourceContents)
    return block.resource


class TestAConversationFromFirstMessageToLast:
    async def test_it_gives_the_whole_conversation_with_a_short_preview_of_each_message(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_read_thread-relaunch")
        listing = await call("outlook_list_mail", category="Website", limit=1)

        thread = await call("outlook_read_thread", uri=_rows(listing, "uri")[0][0])

        assert thread["complete"] is True
        assert thread["message_count"] == len(cast("list[object]", thread["messages"]))
        received = _column(thread, "received_at")
        assert received == sorted(received)
        assert max(len(cast("str", row[0])) for row in _rows(thread, "preview")) <= 255

    async def test_it_gives_the_last_message_in_full_when_its_preview_cuts_the_decision_off(
        self, graph: respx.MockRouter
    ) -> None:
        decision = "We decided: the launch is on 14 June."
        full_text = f"{'Long discussion. ' * 60}{decision}"
        thread = [
            mail_message(
                f"T{n}=",
                "Launch",
                received_at=f"2026-06-0{n}T09:00:00Z",
                conversation_id="CONV1",
            )
            | {"bodyPreview": full_text[:255]}
            for n in (4, 2, 5, 1, 3)
        ]
        _ = graph.get("/me/messages/T3=").mock(
            return_value=httpx.Response(200, json={"id": "T3=", "conversationId": "CONV1"})
        )
        _ = graph.get("/me/messages").mock(return_value=httpx.Response(200, json={"value": thread}))
        _ = graph.get("/me/messages/T5=").mock(
            return_value=httpx.Response(
                200, json=thread[2] | {"body": {"contentType": "text", "content": full_text}}
            )
        )
        _ = graph.get("/me/messages/T5=/attachments").mock(
            return_value=httpx.Response(200, json={"value": []})
        )

        found = await call("outlook_read_thread", uri="outlook:///messages/T3%3D")
        last = _rows(found, "uri")[-1][0]
        message = await call("outlook_read_mail", uri=last)

        assert _column(found, "received_at") == sorted(_column(found, "received_at"))
        assert decision not in cast("str", _rows(found, "preview")[-1][0])
        assert decision in cast("str", message["body"])

    async def test_a_thread_answer_that_holds_other_conversations_is_refused(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_read_thread-relaunch")
        listing = await call("outlook_list_mail", category="Website", limit=1)
        thread = answer_of("rec-tool-outlook_read_thread-relaunch", "GET", "/me/messages", nth=1)
        stranger = dict(cast("list[dict[str, object]]", thread["value"])[0]) | {
            "conversationId": "ANOTHER-CONVERSATION"
        }
        _ = routes[("GET", "/me/messages")].mock(
            return_value=httpx.Response(200, json={"value": [stranger]})
        )

        with pytest.raises(ToolError, match="from other conversations"):
            _ = await call("outlook_read_thread", uri=_rows(listing, "uri")[0][0])


class TestASharedMailbox:
    async def test_it_lists_the_unread_mail_of_the_shared_mailbox_and_not_the_own_mailbox(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve_as(graph, "rec-tool-outlook_list_mail-inbox", "support@example.com")

        found = await call(
            "outlook_list_mail", mailbox="support@example.com", unread_only=True, limit=3
        )

        assert len(cast("list[object]", found["messages"])) == 3
        assert set(paths_asked(graph)) == {
            "/v1.0/users/support@example.com/mailFolders/inbox",
            "/v1.0/users/support@example.com/mailFolders/inbox/messages",
        }

    async def test_a_refused_mailbox_is_explained_as_a_missing_access_of_the_user(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/users/finance/mailFolders/inbox").mock(
            side_effect=answers({"status": 403, "body": "error.accessDenied.json"})
        )

        advice = await advice_for(
            "outlook_list_mail", mailbox="finance", unread_only=True, limit=25
        )

        assert "can lack access to the mailbox" in advice
        assert "Mail.Read.Shared" not in advice
        assert "administrator" not in advice


class TestMiaIsToldWhatHappenedWhenMicrosoftCannotDoWhatSheAsked:
    async def test_one_busy_answer_is_waited_out_and_the_search_shows_its_result(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_search_mail-budget")
        recorded = response(
            {
                "status": 200,
                "response_json": recorded_json("rec-tool-outlook_search_mail-budget.01"),
            }
        )
        _ = routes[("GET", "/me/messages")].mock(
            side_effect=[
                response(
                    {
                        "status": 429,
                        "response_headers": {"Retry-After": "30"},
                        "body": "error.TooManyRequests.json",
                    }
                ),
                recorded,
            ]
        )

        found = await call("outlook_search_mail", sender="Anna Meier", limit=5)

        assert len(cast("list[object]", found["messages"])) == 5
        assert retry_sleeps.delays == [30.0]

    @pytest.mark.parametrize(
        ("tool", "arguments", "path", "text"),
        [
            (
                "outlook_read_mail",
                {"uri": "outlook:///messages/GONE1%3D"},
                "/me/messages/GONE1=",
                "Report that this tool failed to read the message, never that it was never sent",
            ),
            (
                "outlook_read_attachment",
                {"uri": "outlook:///messages/GONE1%3D/attachments/ATT1"},
                "/me/messages/GONE1=/attachments/ATT1",
                "List the attachments again with outlook_list_attachments",
            ),
            (
                "outlook_read_thread",
                {"uri": "outlook:///messages/GONE1%3D"},
                "/me/messages/GONE1=",
                "Search for the message again rather than reusing a handle",
            ),
        ],
        ids=["message", "attachment", "conversation"],
    )
    async def test_an_item_that_microsoft_cannot_find_is_never_reported_as_deleted(
        self,
        graph: respx.MockRouter,
        tool: str,
        arguments: dict[str, str],
        path: str,
        text: str,
    ) -> None:
        _ = graph.get(path).mock(
            side_effect=answers({"status": 404, "body": "error.ErrorItemNotFound.json"})
        )

        advice = await advice_for(tool, **arguments)

        assert text in advice

    async def test_a_list_that_never_ends_is_reported_and_not_as_an_empty_mailbox(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/mailFolders/inbox").mock(
            return_value=httpx.Response(200, json={"displayName": "Inbox"})
        )
        _ = graph.get("/me/mailFolders/inbox/messages").mock(
            side_effect=every_time(_NEVER_ENDING_PAGE)
        )

        advice = await advice_for("outlook_list_mail", unread_only=True, limit=25)

        assert "would not finish sending this list" in advice
        assert "Retry once if the list matters" in advice

    async def test_a_missing_permission_is_explained_to_the_administrator_and_the_user(
        self,
    ) -> None:
        def no_token(patch: pytest.MonkeyPatch) -> None:
            async def refused(*_args: object, **_kwargs: object) -> object:
                raise PermissionError("AADSTS65001 the administrator did not consent")

            patch.setattr(
                "fastmcp.server.auth.providers.azure.AzureProvider.get_obo_credential", refused
            )

        advice = await refusal_of("outlook_search_mail", {"sender": "Anna"}, patches=[no_token])

        assert "Mail.Read, User.Read and Mail.Read.Shared" in advice
        assert "have the user sign in to this connector again" in advice
        assert "retrying will not help" in advice


def _file_answer(content: bytes, **fields: object) -> list[httpx.Response]:
    listed = _attachment("fileAttachment", size=len(content)) | fields
    listed = {key: value for key, value in listed.items() if value is not None}
    return [
        httpx.Response(200, json=listed),
        httpx.Response(200, json=listed | {"contentBytes": base64.b64encode(content).decode()}),
    ]


class TestAnAttachmentIsGivenAsMicrosoftDescribesIt:
    @pytest.mark.parametrize(
        ("content_type", "content", "given_as"),
        [
            (None, b"hello", "application/octet-stream"),
            ("pdf", b"%PDF-1.7", "application/octet-stream"),
            ("text/plain; charset=utf-8", "Grüsse".encode(), "text/plain"),
            ("text/plain", b"\xff\xfe\x00 not text", "application/octet-stream"),
        ],
        ids=["no-type", "type-without-slash", "text-that-reads", "text-that-does-not-read"],
    )
    async def test_it_gives_the_type_that_fits_the_bytes(
        self, graph: respx.MockRouter, content_type: str | None, content: bytes, given_as: str
    ) -> None:
        _ = graph.get("/me/messages/MSG1/attachments/ATT1").mock(
            side_effect=_file_answer(content, contentType=content_type)
        )

        answer = await invoke("outlook_read_attachment", uri=_attachment_uri())

        (block,) = answer.content
        assert isinstance(block, EmbeddedResource)
        resource = block.resource
        assert resource.mime_type == given_as
        given = (
            resource.text.encode()
            if isinstance(resource, TextResourceContents)
            else base64.b64decode(resource.blob)
        )
        assert given == content

    async def test_an_attachment_that_is_larger_than_it_was_announced_is_refused(
        self, graph: respx.MockRouter
    ) -> None:
        listed = _attachment("fileAttachment", size=100)
        content = b"x" * (_TEN_MEBIBYTES + 1)
        _ = graph.get("/me/messages/MSG1/attachments/ATT1").mock(
            side_effect=[
                httpx.Response(200, json=listed),
                httpx.Response(
                    200, json=listed | {"contentBytes": base64.b64encode(content).decode()}
                ),
            ]
        )

        advice = await advice_for("outlook_read_attachment", uri=_attachment_uri())

        assert "never sends part of a file" in advice

    async def test_an_attachment_of_a_kind_that_nobody_knows_is_listed_as_unknown(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/messages/MSG1/attachments").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "@odata.type": "#microsoft.graph.someNewAttachment",
                            "id": "ATT1",
                            "name": "Mystery",
                            "size": 12,
                        }
                    ]
                },
            )
        )

        listed = await call("outlook_list_attachments", uri="outlook:///messages/MSG1")

        (row,) = cast("list[dict[str, object]]", listed["attachments"])
        assert (row["name"], row["kind"]) == ("Mystery", "unknown")

    async def test_a_message_with_no_follow_up_flag_is_listed_with_no_flag(
        self, graph: respx.MockRouter
    ) -> None:
        bare = mail_message("MSG1", "No flag here")
        del bare["flag"]
        _ = folder_listing(graph, _INBOX, bare, display_name="Inbox")

        listed = await call("outlook_list_mail", limit=5)

        assert _rows(listed, "flag")[0][0] is None


def _filter_asked(router: respx.MockRouter) -> str:
    (asked,) = [
        request.url.params["$filter"]
        for request, _answer in cast("list[tuple[httpx.Request, object]]", router.calls)
        if "$filter" in request.url.params
    ]
    return asked


class TestMailOfOneImportanceIsListedOrFound:
    @pytest.mark.parametrize(
        ("importance", "limit", "subjects"),
        [
            ("high", 2, [("RE: Q3 budget review",), ("Laptop rollout: your new device",)]),
            ("normal", 1, [("Roadmap check",)]),
        ],
    )
    async def test_a_listing_keeps_only_the_messages_of_that_importance(
        self, graph: respx.MockRouter, importance: str, limit: int, subjects: list[tuple[str]]
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")

        found = await call("outlook_list_mail", importance=importance, limit=limit)

        assert _rows(found, "subject") == subjects

    @pytest.mark.parametrize(
        ("importance", "asked"), [("low", "low"), ("normal", "medium"), ("high", "high")]
    )
    async def test_a_search_asks_for_that_importance(
        self, graph: respx.MockRouter, importance: str, asked: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call("outlook_search_mail", query="budget", importance=importance, limit=5)

        assert search_of(graph).endswith(f" AND importance:{asked}")


class TestAValueThatDoesNotFitListsNoMail:
    @pytest.mark.parametrize(
        ("arguments", "told"),
        [
            (
                {"folder": "sentitems", "folder_ref": "outlook:///folders/FINANCE%3D"},
                "alternatives, not a pair",
            ),
            ({"from_address": "Anna Meier"}, "it takes one address and nothing else"),
        ],
        ids=["folder-named-twice", "sender-given-as-a-name"],
    )
    async def test_it_tells_the_assistant_what_to_correct_and_asks_microsoft_nothing(
        self, graph: respx.MockRouter, arguments: dict[str, object], told: str
    ) -> None:
        advice = await advice_for("outlook_list_mail", limit=5, **arguments)

        assert told in advice
        assert graph.calls.call_count == 0


class TestAMessageIsNamedByItsHandleAndByNothingElse:
    @pytest.mark.parametrize(
        "tool",
        [
            "outlook_read_mail",
            "outlook_read_thread",
            "outlook_list_attachments",
            "outlook_read_attachment",
        ],
    )
    async def test_a_subject_line_in_place_of_a_handle_reads_nothing(
        self, graph: respx.MockRouter, tool: str
    ) -> None:
        advice = await advice_for(tool, uri="Q3 budget review")

        assert "handle" in advice
        assert graph.calls.call_count == 0


class TestAWindowClosesAtTheEndOfTheDayOrAtTheMomentThatMiaNames:
    @pytest.mark.parametrize(
        ("closing", "listed", "searched"),
        [
            ("2026-03-10", "lt 2026-03-11T00:00:00Z", "received<2026-03-11T00:00:00Z"),
            ("2026-03-10T12:00:00", "le 2026-03-10T12:00:00Z", "received<=2026-03-10T12:00:00Z"),
            (
                "2026-03-10T12:00:00.500000",
                "le 2026-03-10T12:00:00.500000Z",
                "received<=2026-03-10T12:00:00.500000Z",
            ),
        ],
        ids=["a-day", "a-moment", "a-moment-with-a-fraction-of-a-second"],
    )
    async def test_a_listing_and_a_search_close_the_window_there(
        self, graph: respx.MockRouter, closing: str, listed: str, searched: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call("outlook_list_mail", received_before=closing, limit=3)
        _ = await call("outlook_search_mail", sender="Anna", received_before=closing, limit=5)

        assert _filter_asked(graph).endswith(listed)
        assert search_of(graph).endswith(searched)


class TestMailIsFoundByWhoGotItAndByTheNameOfAnAttachment:
    async def test_a_search_names_the_recipient_and_the_attachment(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call(
            "outlook_search_mail", recipient="Anna Meier", attachment_name="Draft v2.pdf", limit=5
        )

        assert search_of(graph) == 'participants:"Anna Meier" attachment:"Draft v2.pdf"'

    @pytest.mark.parametrize("domain", ["acme.com", "@acme.com", "Mail.ACME.co.uk"])
    async def test_a_domain_is_searched_in_every_address_field_because_graph_fails_on_participants(
        self, graph: respx.MockRouter, domain: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call("outlook_search_mail", recipient=domain, query="invoice", limit=5)

        group = " OR ".join(f"{field}:{domain}" for field in ("from", "to", "cc", "bcc"))
        assert search_of(graph) == f"invoice ({group})"

    async def test_a_search_records_which_arguments_it_used_and_none_of_their_values(
        self, graph: respx.MockRouter, recorded_spans: InMemorySpanExporter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call(
            "outlook_search_mail",
            recipient="acme.com",
            query="secret words",
            received_after="2026-01-01",
            flagged=False,
            has_attachments=True,
            category="Red",
            limit=5,
        )

        [recorded] = [
            span.attributes["search_mail.arguments"]
            for span in recorded_spans.get_finished_spans()
            if span.attributes and "search_mail.arguments" in span.attributes
        ]
        assert recorded == (
            "query",
            "recipient",
            "received_after",
            "flagged",
            "has_attachments",
            "category",
        )

    @pytest.mark.parametrize("person", ["anna@acme.com", "Anna", "J. Smith"])
    async def test_a_person_is_still_searched_with_participants(
        self, graph: respx.MockRouter, person: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call("outlook_search_mail", recipient=person, limit=5)

        assert search_of(graph).startswith("participants:")


class TestAPersonIsFoundByTheDomainOfTheirCompany:
    @staticmethod
    def _serve_an_empty_address_book(graph: respx.MockRouter, **changes: object) -> respx.Route:
        _ = graph.get("/me").mock(
            return_value=httpx.Response(200, json={"id": "me", "mail": "mia@example.test"})
        )
        _ = graph.get("/me/people").mock(return_value=httpx.Response(200, json={"value": []}))
        return graph.get("/me/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "m1",
                            "receivedDateTime": "2026-03-04T09:15:00Z",
                            "from": {
                                "emailAddress": {"name": "Tom Brandt", "address": "tom@acme.test"}
                            },
                            "toRecipients": [
                                {"emailAddress": {"name": "Mia", "address": "mia@example.test"}}
                            ],
                            "ccRecipients": [],
                            "bccRecipients": [],
                        }
                        | changes
                    ]
                },
            )
        )

    @pytest.mark.parametrize("domain", ["acme.test", "@acme.test", "Mail.ACME.co.uk"])
    async def test_a_domain_that_the_address_book_does_not_know_is_searched_in_every_address_field(
        self, graph: respx.MockRouter, domain: str
    ) -> None:
        messages = self._serve_an_empty_address_book(graph)

        _ = await call("outlook_find_recipient", query=domain, limit=5)

        asked = messages.calls.last.request.url.params["$search"]
        group = " OR ".join(f"{field}:{domain}" for field in ("from", "to", "cc", "bcc"))
        assert asked.removeprefix('"').removesuffix('"') == f"({group})"

    async def test_the_people_who_wrote_from_that_domain_are_the_candidates(
        self, graph: respx.MockRouter
    ) -> None:
        _ = self._serve_an_empty_address_book(graph)

        found = await call("outlook_find_recipient", query="acme.test", limit=5)

        [candidate] = cast("list[dict[str, object]]", found["candidates"])
        assert (candidate["address"], candidate["source"], candidate["external"]) == (
            "tom@acme.test",
            "mailbox",
            True,
        )

    async def test_a_person_who_was_only_on_bcc_is_a_candidate(
        self, graph: respx.MockRouter
    ) -> None:
        _ = self._serve_an_empty_address_book(
            graph,
            **{
                "from": {"emailAddress": {"name": "Mia", "address": "mia@example.test"}},
                "bccRecipients": [
                    {"emailAddress": {"name": "Anna Weiss", "address": "anna@acme.test"}}
                ],
            },
        )

        found = await call("outlook_find_recipient", query="acme.test", limit=5)

        [candidate] = cast("list[dict[str, object]]", found["candidates"])
        assert candidate["address"] == "anna@acme.test"

    async def test_a_name_that_the_address_book_does_not_know_is_still_searched_with_participants(
        self, graph: respx.MockRouter
    ) -> None:
        messages = self._serve_an_empty_address_book(graph)

        _ = await call("outlook_find_recipient", query="Tom Brandt", limit=5)

        asked = messages.calls.last.request.url.params["$search"]
        assert asked.removeprefix('"').removesuffix('"').startswith("participants:")


class TestWordsInQuotesStayTogetherAndAnOperatorWordIsOnlyAWord:
    @pytest.mark.parametrize(
        ("query", "asked"),
        [
            ('the "Q3 budget" plan', 'the "Q3 budget" plan'),
            ('the "  " plan', "the plan"),
            ("budget OR plan", 'budget "OR" plan'),
        ],
        ids=["a-quoted-phrase", "an-empty-quote", "an-operator-word"],
    )
    async def test_a_search_gives_the_words_to_microsoft_as_text(
        self, graph: respx.MockRouter, query: str, asked: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")

        _ = await call("outlook_search_mail", query=query, limit=5)

        assert search_of(graph) == asked


class TestASearchThatFindsNothingGivesAnEmptyList:
    async def test_it_gives_no_message_and_says_that_no_more_may_exist(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/messages").mock(return_value=httpx.Response(200, json={"value": []}))

        found = await call("outlook_search_mail", query="budget", limit=5)

        assert found == {"messages": [], "more_may_exist": False}
        assert [path for path in paths_asked(graph) if "translate" in path] == []


class TestAMessageWithNoTextIsReadWithNoText:
    async def test_it_gives_no_body_and_says_that_the_text_is_not_html(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/messages/MSG1").mock(
            return_value=httpx.Response(200, json=mail_message("MSG1", "Empty"))
        )
        _ = graph.get("/me/messages/MSG1/attachments").mock(
            return_value=httpx.Response(200, json={"value": []})
        )

        message = await call("outlook_read_mail", uri="outlook:///messages/MSG1")

        assert message["body"] is None
        assert (message["body_is_the_new_part"], message["body_is_plain_text"]) == (False, False)


class TestAMessageThatListsNoConversationGivesAnEmptyThread:
    @pytest.mark.parametrize(
        ("anchor", "listed"),
        [
            ({"id": "MSG1"}, None),
            ({"id": "MSG1", "conversationId": "CONV1"}, []),
        ],
        ids=["no-conversation", "no-message-in-the-conversation"],
    )
    async def test_it_gives_no_message_and_does_not_hide_that_the_thread_is_empty(
        self, graph: respx.MockRouter, anchor: dict[str, object], listed: list[object] | None
    ) -> None:
        _ = graph.get("/me/messages/MSG1").mock(return_value=httpx.Response(200, json=anchor))
        listing = graph.get("/me/messages").mock(
            return_value=httpx.Response(200, json={"value": listed or []})
        )

        thread = await call("outlook_read_thread", uri="outlook:///messages/MSG1")

        assert (thread["messages"], thread["message_count"], thread["complete"]) == ([], 0, True)
        assert listing.called is (listed is not None)
