import functools
import json
from collections.abc import Callable, Mapping, Sequence
from typing import cast

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, InputRequiredResult, TextContent
from mcp.types import ElicitResult as CarriedAnswer
from respx import MockRouter

from tests.conftest import RecordedSleeps
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.tools.scenarios.support import Person, call, response, serve

SETTINGS = "/me/mailboxSettings"
OVERRIDES = "/me/inferenceClassification/overrides"

MONDAY = "2026-11-02T00:00:00"
SATURDAY = "2026-11-07T00:00:00"
TUESDAY = "2026-11-03T18:00:00"
MIAS_ZONE = "W. Europe Standard Time"

TURN_ON = {
    "status": "scheduled",
    "start": MONDAY,
    "end": SATURDAY,
    "time_zone": MIAS_ZONE,
    "internal_message": "<p>I am away until Monday.</p>",
    "external_message": "<p>I am away until Monday.</p>",
    "external_audience": "all",
}

KEEP_MESSAGES = {key: value for key, value in TURN_ON.items() if "message" not in key}

SIGN_IN_AGAIN = "Ask the user to sign in to this connector again"
ASK_AN_ADMINISTRATOR = "Ask a Microsoft 365 administrator"
RETRY_ONCE = "Retry once"
STOP_AND_REPORT = "stop and report it"


def _fault(status: int, body: str, **headers: str) -> httpx.Response:
    return response({"status": status, "body": body, "headers": headers})


def _expired() -> httpx.Response:
    return _fault(401, "error.InvalidAuthenticationToken.json")


def _refused() -> httpx.Response:
    return _fault(403, "error.accessDenied.json")


def _busy() -> httpx.Response:
    return _fault(429, "error.TooManyRequests.json", **{"Retry-After": "30"})


def _failure(kind: str) -> httpx.Response | Exception:
    match kind:
        case "fails-on-its-side":
            return _fault(500, "error.generalException.json")
        case "no-answer-in-time":
            return httpx.ReadTimeout("no answer in time")
        case _:
            return response(
                {
                    "status": 200,
                    "headers": {"Content-Type": "text/html"},
                    "body": "page.notData.html",
                }
            )


THREE_FAILURES = ["fails-on-its-side", "no-answer-in-time", "unreadable-answer"]


def _reply(**stored: object) -> dict[str, object]:
    return {
        "status": "disabled",
        "externalAudience": "all",
        "internalReplyMessage": "<p>Back soon.</p>",
        "externalReplyMessage": "<p>Back soon.</p>",
        "scheduledStartDateTime": {"dateTime": "2026-10-01T00:00:00.0000000", "timeZone": "UTC"},
        "scheduledEndDateTime": {"dateTime": "2026-10-02T00:00:00.0000000", "timeZone": "UTC"},
    } | stored


class Mailbox:
    def __init__(self, graph: MockRouter, person: Person | None = None, **stored: object) -> None:
        self.reply: dict[str, object] = _reply(**stored)
        self.sent: list[Mapping[str, object]] = []
        self.asked_at_write: list[int] = []
        self.write_failures: list[httpx.Response | Exception] = []
        self.person: Person | None = person
        _ = graph.get(SETTINGS).mock(side_effect=self._read)
        _ = graph.patch(SETTINGS).mock(side_effect=self._write)

    def _read(self, request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, json={"automaticRepliesSetting": self.reply})

    def _write(self, request: httpx.Request) -> httpx.Response:
        self.asked_at_write.append(len(self.person.asked) if self.person else 0)
        if self.write_failures:
            failure = self.write_failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        body = cast("Mapping[str, Mapping[str, object]]", json.loads(request.content))
        self.sent.append(body["automaticRepliesSetting"])
        self.reply = dict(body["automaticRepliesSetting"])
        return self._read(request)


def _section(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value[name])


async def _stored_reply() -> Mapping[str, object]:
    return _section(
        await call("outlook_get_mailbox_settings", include="replies"), "automatic_reply"
    )


async def _turn_on(person: Person | None = None) -> Mapping[str, object]:
    return await call(
        "outlook_set_automatic_reply",
        person=person,
        status="scheduled",
        start=MONDAY,
        end=SATURDAY,
        time_zone=MIAS_ZONE,
        internal_message="<p>I am away until Monday.</p>",
        external_message="<p>I am away until Monday.</p>",
        external_audience="all",
    )


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


class TestAReplyAlwaysHasAnEnd:
    async def test_it_stores_the_reply_from_monday_to_saturday_in_the_zone_of_mia(
        self, graph: MockRouter
    ) -> None:
        _ = Mailbox(graph)

        _ = await _turn_on()

        stored = await _stored_reply()
        assert stored["status"] == "scheduled"
        assert stored["scheduled_start"] == {"date_time": MONDAY, "time_zone": MIAS_ZONE}
        assert stored["scheduled_end"] == {"date_time": SATURDAY, "time_zone": MIAS_ZONE}

    async def test_it_stores_the_message_for_senders_inside_and_outside_the_organization(
        self, graph: MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_set_automatic_reply-both-messages")
        inside = "seed-v1 case-outlook_set_automatic_reply-both-messages: away, inside."
        outside = "seed-v1 case-outlook_set_automatic_reply-both-messages: away, outside."

        _ = await call(
            "outlook_set_automatic_reply",
            status="scheduled",
            start=MONDAY,
            end=TUESDAY,
            time_zone="UTC",
            internal_message=inside,
            external_message=outside,
            external_audience="none",
        )

        sent = cast(
            "Mapping[str, Mapping[str, object]]",
            json.loads(routes[("PATCH", SETTINGS)].calls.last.request.content),
        )
        stored = await _stored_reply()
        assert sent["automaticRepliesSetting"]["internalReplyMessage"] == inside
        assert sent["automaticRepliesSetting"]["externalReplyMessage"] == outside
        assert stored["internal_reply_message"] == inside
        assert stored["external_reply_message"] == outside
        assert stored["external_audience"] == "none"

    async def test_it_refuses_a_reply_with_no_end_and_leaves_the_reply_off(
        self, graph: MockRouter
    ) -> None:
        mailbox = Mailbox(graph)

        with pytest.raises(ToolError, match="no end date"):
            _ = await call("outlook_set_automatic_reply", status="scheduled", start=MONDAY)

        assert mailbox.sent == []
        assert mailbox.reply["status"] == "disabled"
        assert graph.calls.call_count == 0

    async def test_it_turns_the_reply_off_without_asking_mia(self, graph: MockRouter) -> None:
        routes = serve(graph, "rec-tool-outlook_set_automatic_reply-disabled")
        person = Person()

        turned_off = await call("outlook_set_automatic_reply", person=person, status="disabled")

        assert [key for key, route in routes.items() if not route.called] == []
        sent = cast(
            "Mapping[str, Mapping[str, object]]",
            json.loads(routes[("PATCH", SETTINGS)].calls.last.request.content),
        )
        assert sent["automaticRepliesSetting"]["status"] == "disabled"
        assert turned_off["status"] == "disabled"
        assert person.asked == []


class TestTheStateOfTheReplyIsRead:
    async def test_it_reads_the_state_of_the_reply_from_the_mailbox(
        self, graph: MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_get_mailbox_settings-replies")

        stored = await _stored_reply()

        assert [key for key, route in routes.items() if not route.called] == []
        assert stored["status"] == "disabled"
        assert stored["scheduled_end"] == {
            "date_time": "2026-10-30T15:00:00.0000000",
            "time_zone": "UTC",
        }

    async def test_it_gives_the_end_and_the_message_of_a_reply_that_is_on(
        self, graph: MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_set_automatic_reply-scheduled")
        away = "seed-v1 case-outlook_set_automatic_reply-scheduled: I am away today."
        _ = await call(
            "outlook_set_automatic_reply",
            status="scheduled",
            start=MONDAY,
            end=TUESDAY,
            time_zone="UTC",
            internal_message=away,
            external_audience="none",
        )

        stored = await _stored_reply()

        assert stored["status"] == "scheduled"
        assert _section(stored, "scheduled_end")["date_time"] == "2026-11-03T18:00:00.0000000"
        assert stored["internal_reply_message"] == away


class TestAReplyStartsOnlyAfterMiaAgrees:
    async def test_it_asks_mia_before_it_writes_the_reply(self, graph: MockRouter) -> None:
        person = Person()
        mailbox = Mailbox(graph, person)

        _ = await _turn_on(person)

        assert len(person.asked) == 1
        assert "Turn on the automatic reply" in person.asked[0]
        assert mailbox.asked_at_write == [1]

    async def test_it_leaves_the_reply_off_when_mia_declines(self, graph: MockRouter) -> None:
        person = Person(approval="no")
        mailbox = Mailbox(graph, person)

        with pytest.raises(ToolError, match="The automatic reply was not changed"):
            _ = await _turn_on(person)

        assert len(person.asked) == 1
        assert mailbox.sent == []
        assert mailbox.reply["status"] == "disabled"

    async def test_it_leaves_the_reply_off_when_the_question_gets_no_usable_answer(
        self, graph: MockRouter
    ) -> None:
        person = Person(approval="unanswered")
        mailbox = Mailbox(graph, person)

        with pytest.raises(ToolError) as refused:
            _ = await _turn_on(person)

        assert "received no answer" in str(refused.value)
        assert "make the same request again" in str(refused.value)
        assert mailbox.sent == []

    async def test_it_leaves_the_reply_off_when_the_client_cannot_ask(
        self, graph: MockRouter
    ) -> None:
        mailbox = Mailbox(graph)

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            async with Client(FastMCPTransport(_server()), mode="legacy") as client:
                with pytest.raises(ToolError) as refused:
                    _ = await client.call_tool("outlook_set_automatic_reply", TURN_ON)

        assert "cannot ask a person" in str(refused.value)
        assert "Microsoft 365 app" in str(refused.value)
        assert mailbox.sent == []

    async def test_it_rejects_an_approval_that_was_given_for_another_reply(
        self, graph: MockRouter
    ) -> None:
        mailbox = Mailbox(graph)

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            async with Client(FastMCPTransport(_server())) as client:
                first = await _asked(client, KEEP_MESSAGES)
                with pytest.raises(MCPError, match="Invalid or expired requestState"):
                    _ = await _agreed(client, KEEP_MESSAGES | {"end": "2026-11-14T00:00:00"}, first)

        assert mailbox.sent == []
        assert mailbox.reply["status"] == "disabled"

    async def test_it_turns_nothing_on_when_the_stored_reply_changed_after_mia_was_asked(
        self, graph: MockRouter
    ) -> None:
        mailbox = Mailbox(graph)

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            async with Client(FastMCPTransport(_server())) as client:
                first = await _asked(client, KEEP_MESSAGES)
                mailbox.reply["internalReplyMessage"] = "<p>Changed after Mia was asked.</p>"
                second = await _agreed(client, KEEP_MESSAGES, first)

        assert isinstance(second, CallToolResult)
        assert second.is_error
        text = " ".join(block.text for block in second.content if isinstance(block, TextContent))
        assert "different request" in text
        assert mailbox.sent == []
        assert mailbox.reply["status"] == "disabled"


async def _asked(
    client: Client[FastMCPTransport], arguments: Mapping[str, object]
) -> InputRequiredResult:
    first = await client.session.call_tool(
        "outlook_set_automatic_reply", dict(arguments), allow_input_required=True
    )
    assert isinstance(first, InputRequiredResult)
    return first


async def _agreed(
    client: Client[FastMCPTransport], arguments: Mapping[str, object], first: InputRequiredResult
) -> CallToolResult | InputRequiredResult:
    (key,) = first.input_requests or {}
    answered = await client.session.call_tool(
        "outlook_set_automatic_reply",
        dict(arguments),
        input_responses={key: CarriedAnswer(action="accept", content={"value": "turn on"})},
        request_state=first.request_state,
        allow_input_required=True,
    )
    assert isinstance(answered, CallToolResult | InputRequiredResult)
    return answered


class TestAStateThatCannotBeReadIsNeverReportedAsOff:
    @pytest.mark.parametrize(
        ("fault", "told"),
        [
            pytest.param(_expired, SIGN_IN_AGAIN, id="sign-in-expired"),
            pytest.param(_busy, "left alone for 30 seconds", id="busy-at-every-try"),
        ],
    )
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_tells_why_the_state_cannot_be_read(
        self, graph: MockRouter, fault: Callable[[], httpx.Response], told: str
    ) -> None:
        _ = graph.get(SETTINGS).mock(return_value=fault())

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_get_mailbox_settings", include="replies")

        assert told in str(refused.value)

    async def test_it_explains_an_account_with_no_mailbox(self, graph: MockRouter) -> None:
        _ = graph.get(SETTINGS).mock(return_value=_fault(404, "error.ErrorItemNotFound.json"))

        with pytest.raises(ToolError, match="this account has no Exchange Online mailbox"):
            _ = await call("outlook_get_mailbox_settings", include="replies")

    async def test_it_waits_out_one_busy_answer_inside_the_same_call(
        self, graph: MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        _ = Mailbox(graph, status="scheduled")
        _ = graph.get(SETTINGS).mock(
            side_effect=[
                _busy(),
                httpx.Response(200, json={"automaticRepliesSetting": _reply(status="scheduled")}),
            ]
        )

        stored = await _stored_reply()

        assert stored["status"] == "scheduled"
        assert retry_sleeps.delays == [30]

    @pytest.mark.parametrize("failure", THREE_FAILURES)
    async def test_it_reads_the_state_at_the_second_try_after_one_failure(
        self, graph: MockRouter, failure: str
    ) -> None:
        _ = graph.get(SETTINGS).mock(
            side_effect=[
                _failure(failure),
                httpx.Response(200, json={"automaticRepliesSetting": _reply(status="scheduled")}),
            ]
        )

        with pytest.raises(ToolError, match=RETRY_ONCE):
            _ = await _stored_reply()
        stored = await _stored_reply()

        assert stored["status"] == "scheduled"

    async def test_it_reports_a_reading_that_fails_twice_and_never_says_off(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(SETTINGS).mock(side_effect=[_failure("fails-on-its-side")] * 2)

        with pytest.raises(ToolError) as first:
            _ = await _stored_reply()
        with pytest.raises(ToolError) as second:
            _ = await _stored_reply()

        assert STOP_AND_REPORT in str(first.value)
        assert STOP_AND_REPORT in str(second.value)
        assert "disabled" not in str(second.value)

    async def test_it_names_the_permission_that_no_administrator_gave(
        self, graph: MockRouter
    ) -> None:
        async def never_consented(_self: AzureProvider, *, user_assertion: str) -> object:
            raise RuntimeError(f"AADSTS65001: no consent for {len(user_assertion)} characters")

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            patch.setattr(AzureProvider, "get_obo_credential", never_consented)
            async with Client(FastMCPTransport(_server()), mode="legacy") as client:
                with pytest.raises(ToolError) as refused:
                    _ = await client.call_tool(
                        "outlook_get_mailbox_settings", {"include": "replies"}
                    )

        message = str(refused.value)
        assert "MailboxSettings.Read" in message
        assert "administrator" in message
        assert "sign in to this connector again" in message
        assert graph.calls.call_count == 0


class TestAReplyThatMicrosoftWillNotStoreIsNotTurnedOn:
    async def test_it_gives_the_reason_when_microsoft_refuses_the_dates(
        self, graph: MockRouter
    ) -> None:
        person = Person()
        _ = graph.get(SETTINGS).mock(
            return_value=httpx.Response(200, json={"automaticRepliesSetting": _reply()})
        )
        _ = graph.patch(SETTINGS).mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": {
                        "code": "ErrorInvalidSchedule",
                        "message": "The end is before the start.",
                    }
                },
            )
        )

        with pytest.raises(ToolError) as refused:
            _ = await _turn_on(person)

        assert "The end is before the start." in str(refused.value)
        assert "will fail the same way" in str(refused.value)
        assert len(person.asked) == 1

    async def test_it_says_when_the_reply_can_be_stored_after_a_busy_answer(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(SETTINGS).mock(
            return_value=httpx.Response(200, json={"automaticRepliesSetting": _reply()})
        )
        _ = graph.patch(SETTINGS).mock(return_value=_busy())

        with pytest.raises(ToolError, match="left alone for 30 seconds"):
            _ = await _turn_on()

    @pytest.mark.parametrize(
        ("fault", "told"),
        [
            pytest.param(_expired, SIGN_IN_AGAIN, id="sign-in-expired"),
            pytest.param(_refused, ASK_AN_ADMINISTRATOR, id="access-refused"),
        ],
    )
    async def test_it_asks_nobody_when_the_stored_reply_cannot_be_read_first(
        self, graph: MockRouter, fault: Callable[[], httpx.Response], told: str
    ) -> None:
        person = Person()
        mailbox = Mailbox(graph, person)
        _ = graph.get(SETTINGS).mock(return_value=fault())

        with pytest.raises(ToolError) as refused:
            _ = await _turn_on(person)

        assert told in str(refused.value)
        assert person.asked == []
        assert mailbox.sent == []

    @pytest.mark.parametrize("failure", THREE_FAILURES)
    async def test_it_asks_again_and_stores_the_reply_at_the_second_try(
        self, graph: MockRouter, failure: str
    ) -> None:
        person = Person()
        mailbox = Mailbox(graph, person)
        mailbox.write_failures.append(_failure(failure))

        with pytest.raises(ToolError, match=RETRY_ONCE):
            _ = await _turn_on(person)
        _ = await _turn_on(person)

        stored = await _stored_reply()
        assert stored["scheduled_start"] == {"date_time": MONDAY, "time_zone": MIAS_ZONE}
        assert stored["scheduled_end"] == {"date_time": SATURDAY, "time_zone": MIAS_ZONE}
        assert len(person.asked) == 2

    async def test_it_reports_a_reply_that_fails_to_store_twice_and_never_says_on(
        self, graph: MockRouter
    ) -> None:
        person = Person()
        mailbox = Mailbox(graph, person)
        mailbox.write_failures.extend([_failure("fails-on-its-side")] * 2)

        with pytest.raises(ToolError) as first:
            _ = await _turn_on(person)
        with pytest.raises(ToolError) as second:
            _ = await _turn_on(person)

        assert STOP_AND_REPORT in str(first.value)
        assert STOP_AND_REPORT in str(second.value)
        assert mailbox.reply["status"] == "disabled"


class TestASenderHasAFixedTab:
    async def test_it_lists_a_sender_in_the_tab_it_was_fixed_to(self, graph: MockRouter) -> None:
        routes = serve(graph, "rec-tool-outlook_list_focused_overrides-set")

        fixed = await call(
            "outlook_set_focused_override", sender="anna@example.test", classify_as="focused"
        )
        listed = await call("outlook_list_focused_overrides")

        assert [key for key, route in routes.items() if not route.called and key[0] != "GET"] == []
        assert fixed["classify_as"] == "focused"
        assert [(row["sender_address"], row["classify_as"]) for row in _rows(listed)] == [
            ("anna@example.test", "focused")
        ]

    async def test_it_moves_a_sender_that_has_a_fixed_tab_to_the_new_tab(
        self, graph: MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_set_focused_override-update")

        _ = await call(
            "outlook_set_focused_override", sender="anna@example.test", classify_as="focused"
        )
        moved = await call(
            "outlook_set_focused_override", sender="anna@example.test", classify_as="other"
        )

        assert moved["classify_as"] == "other"
        assert moved["sender_address"] == "anna@example.test"
        assert routes[("POST", OVERRIDES)].call_count == 1
        assert [route.called for key, route in routes.items() if key[0] == "PATCH"] == [True]

    async def test_it_lists_every_fixed_sender_with_its_tab(self, graph: MockRouter) -> None:
        _ = serve(graph, "rec-tool-outlook_list_focused_overrides-two")
        _ = await call(
            "outlook_set_focused_override", sender="tom@example.test", classify_as="focused"
        )
        _ = await call(
            "outlook_set_focused_override", sender="anna@example.test", classify_as="other"
        )

        listed = await call("outlook_list_focused_overrides")

        assert [(row["sender_address"], row["classify_as"]) for row in _rows(listed)] == [
            ("anna@example.test", "other"),
            ("tom@example.test", "focused"),
        ]

    async def test_it_refuses_a_name_where_an_address_is_needed_and_stores_nothing(
        self, graph: MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="ask the user for the address"):
            _ = await call(
                "outlook_set_focused_override", sender="Ada Keller", classify_as="focused"
            )

        assert graph.calls.call_count == 0

    async def test_it_finds_nobody_for_a_name_that_no_mail_and_no_directory_holds(
        self, graph: MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_find_recipient-anna")

        found = await call("outlook_find_recipient", query="Anna Meier")

        assert [key for key, route in routes.items() if not route.called] == []
        assert found["outcome"] == "no_match"
        assert found["candidates"] == []


def _override(address: str, name: str, tab: str) -> dict[str, object]:
    return {
        "id": f"id-{address}",
        "classifyAs": tab,
        "senderEmailAddress": {"address": address, "name": name},
    }


def _rows(listed: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    return cast("Sequence[Mapping[str, object]]", listed["overrides"])


class TestATabThatCannotBeReadOrStoredIsNeverReportedAsEmpty:
    @pytest.mark.parametrize(
        ("fault", "told"),
        [
            pytest.param(_expired, SIGN_IN_AGAIN, id="sign-in-expired"),
            pytest.param(_busy, "left alone for 30 seconds", id="busy-at-every-try"),
        ],
    )
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_tells_why_the_senders_cannot_be_read(
        self, graph: MockRouter, fault: Callable[[], httpx.Response], told: str
    ) -> None:
        _ = graph.get(OVERRIDES).mock(return_value=fault())

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_list_focused_overrides")

        assert told in str(refused.value)

    @pytest.mark.parametrize(
        ("fault", "told"),
        [
            pytest.param(_expired, SIGN_IN_AGAIN, id="sign-in-expired"),
            pytest.param(_refused, "Mail.ReadWrite", id="access-refused"),
            pytest.param(_busy, "left alone for 30 seconds", id="busy-at-every-try"),
        ],
    )
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_tells_why_the_tab_cannot_be_stored(
        self, graph: MockRouter, fault: Callable[[], httpx.Response], told: str
    ) -> None:
        _ = graph.get(OVERRIDES).mock(return_value=httpx.Response(200, json={"value": []}))
        stored = graph.post(OVERRIDES).mock(return_value=fault())

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_set_focused_override", sender="ada@acme.example", classify_as="focused"
            )

        assert told in str(refused.value)
        assert stored.called

    @pytest.mark.parametrize("failure", ["fails-on-its-side", "no-answer-in-time"])
    async def test_it_stores_the_tab_once_at_the_second_try(
        self, graph: MockRouter, failure: str
    ) -> None:
        _ = graph.get(OVERRIDES).mock(return_value=httpx.Response(200, json={"value": []}))
        _ = graph.post(OVERRIDES).mock(
            side_effect=[
                _failure(failure),
                httpx.Response(201, json=_override("ada@acme.example", "Ada Keller", "focused")),
            ]
        )

        with pytest.raises(ToolError, match=RETRY_ONCE):
            _ = await call(
                "outlook_set_focused_override", sender="ada@acme.example", classify_as="focused"
            )
        stored = await call(
            "outlook_set_focused_override", sender="ada@acme.example", classify_as="focused"
        )

        assert stored["sender_address"] == "ada@acme.example"
        assert stored["classify_as"] == "focused"

    async def test_it_reports_a_tab_that_fails_to_store_twice_and_never_says_set(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(OVERRIDES).mock(return_value=httpx.Response(200, json={"value": []}))
        _ = graph.post(OVERRIDES).mock(side_effect=[_failure("fails-on-its-side")] * 2)

        with pytest.raises(ToolError) as first:
            _ = await call(
                "outlook_set_focused_override", sender="ada@acme.example", classify_as="focused"
            )
        with pytest.raises(ToolError) as second:
            _ = await call(
                "outlook_set_focused_override", sender="ada@acme.example", classify_as="focused"
            )

        assert STOP_AND_REPORT in str(first.value)
        assert STOP_AND_REPORT in str(second.value)


class TestTheReplyMiaSeesIsTheReplyThatOutlookHolds:
    async def test_it_reads_a_reply_with_no_end_that_goes_to_contacts_only(
        self, graph: MockRouter
    ) -> None:
        _ = Mailbox(
            graph,
            status="alwaysEnabled",
            externalAudience="contactsOnly",
            scheduledStartDateTime=None,
            scheduledEndDateTime=None,
        )

        stored = await _stored_reply()

        assert (stored["status"], stored["external_audience"]) == ("alwaysEnabled", "contactsOnly")
        assert (stored["scheduled_start"], stored["scheduled_end"]) == (None, None)

    async def test_it_reads_a_reply_setting_with_no_state_and_no_audience(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(SETTINGS).mock(
            return_value=httpx.Response(200, json={"automaticRepliesSetting": {}})
        )

        stored = await _stored_reply()

        assert (stored["status"], stored["external_audience"]) == (None, None)

    async def test_it_reads_a_mailbox_that_holds_no_reply_as_a_reply_with_no_state(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(SETTINGS).mock(return_value=httpx.Response(200, json={}))

        stored = await _stored_reply()

        assert (stored["status"], stored["external_audience"]) == (None, None)

    @pytest.mark.parametrize(
        ("answer", "state"),
        [
            ({}, (None, None)),
            ({"automaticRepliesSetting": {}}, (None, None)),
            (
                {
                    "automaticRepliesSetting": {
                        "status": "alwaysEnabled",
                        "externalAudience": "contactsOnly",
                    }
                },
                ("alwaysEnabled", "contactsOnly"),
            ),
        ],
        ids=["no-setting", "empty-setting", "runs-for-contacts-only"],
    )
    async def test_it_reports_the_state_that_microsoft_stored_after_a_change(
        self, graph: MockRouter, answer: dict[str, object], state: tuple[object, object]
    ) -> None:
        _ = graph.get(SETTINGS).mock(return_value=httpx.Response(200, json={}))
        _ = graph.patch(SETTINGS).mock(return_value=httpx.Response(200, json=answer))

        stored = await call("outlook_set_automatic_reply", status="disabled")

        assert (stored["status"], stored["external_audience"]) == state

    async def test_it_names_the_contacts_who_get_the_reply_in_the_question(
        self, graph: MockRouter
    ) -> None:
        person = Person()
        _ = Mailbox(graph, person)

        _ = await call(
            "outlook_set_automatic_reply",
            person=person,
            status="scheduled",
            start=MONDAY,
            end=SATURDAY,
            time_zone=MIAS_ZONE,
            internal_message="<p>I am away.</p>",
            external_audience="contactsOnly",
        )

        assert "Contacts outside the organization get" in person.asked[0]

    async def test_it_reads_the_time_zone_the_hours_the_language_and_the_archive_folder(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(SETTINGS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "timeZone": "W. Europe Standard Time",
                    "archiveFolder": "ARCHIVE1",
                    "language": {"locale": "de-CH", "displayName": "German (Switzerland)"},
                    "workingHours": {
                        "daysOfWeek": ["monday", "tuesday"],
                        "startTime": "08:00:00.0000000",
                        "endTime": "17:00:00.0000000",
                        "timeZone": {"name": "W. Europe Standard Time"},
                    },
                },
            )
        )

        stored = await call("outlook_get_mailbox_settings", include="preferences")

        assert stored["time_zone"] == "W. Europe Standard Time"
        assert stored["language"] == {"locale": "de-CH", "display_name": "German (Switzerland)"}
        assert stored["archive_folder_uri"] == "outlook:///folders/ARCHIVE1"
        assert stored["automatic_reply"] is None

    async def test_it_reads_a_mailbox_that_holds_no_language_as_no_language(
        self, graph: MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_get_mailbox_settings-preferences")

        stored = await call("outlook_get_mailbox_settings", include="preferences")

        assert [key for key, route in routes.items() if not route.called] == []
        assert stored["time_zone"] == "W. Europe Standard Time"
        assert (stored["language"], stored["archive_folder_uri"]) == (None, None)
        assert _section(stored, "working_hours")["days"] == [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
        ]

    async def test_it_lists_the_category_names_of_the_mailbox(self, graph: MockRouter) -> None:
        routes = serve(graph, "rec-tool-outlook_get_mailbox_settings-categories")

        stored = await call("outlook_get_mailbox_settings", include="categories")

        assert [key for key, route in routes.items() if not route.called] == []
        assert stored["categories"] == [f"synthetic text {number:02d}" for number in range(1, 7)]
        assert stored["categories_capped"] is False
        assert stored["rules"] is None


class TestASenderWithNoStoredTabIsListedWithNoTab:
    async def test_it_gives_the_address_and_no_tab(self, graph: MockRouter) -> None:
        stored = _override("anna@example.test", "Anna Meier", "other")
        del stored["classifyAs"]
        _ = graph.get(OVERRIDES).mock(return_value=httpx.Response(200, json={"value": [stored]}))

        listed = await call("outlook_list_focused_overrides")

        assert [(row["sender_address"], row["classify_as"]) for row in _rows(listed)] == [
            ("anna@example.test", None)
        ]
