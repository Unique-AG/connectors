import functools
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import cast

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from respx import MockRouter, Route

from tests.conftest import RecordedSleeps
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.tools.scenarios.mail_support import refusal_of
from tests.tools.scenarios.support import call, response, serve

CONTACTS = "/me/contacts"
LISTING = ("GET", CONTACTS)
FIRST_ROW = (
    "outlook:///contacts/EFgJBuLNOVXOAIEPKztyTj4boIPzWP-SVu0Ev3Iuzt45HvAQZg8W7ffifqZC42raTpDY"
)

TOM_ID = "AAMkSYNTHETICtom0001"
TOM = f"outlook:///contacts/{TOM_ID}"

SIGN_IN_AGAIN = "Ask the user to sign in to this connector again"
BUSY_30_SECONDS = "left alone for 30 seconds"
RETRY_ONCE = "Retry once"
STOP_AND_REPORT = "stop and report it"
NOT_FOUND = "This tool cannot tell which one it is"

THREE_FAILURES = ["fails-on-its-side", "no-answer-in-time", "unreadable-answer"]


def _fault(status: int, body: str, **headers: str) -> httpx.Response:
    return response({"status": status, "body": body, "headers": headers})


def _expired() -> httpx.Response:
    return _fault(401, "error.InvalidAuthenticationToken.json")


def _busy() -> httpx.Response:
    return _fault(429, "error.TooManyRequests.json", **{"Retry-After": "30"})


def _not_found() -> httpx.Response:
    return _fault(404, "error.ErrorItemNotFound.json")


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


def _then_recorded(route: Route, *failures: httpx.Response | Exception) -> None:
    recorded = cast("Iterator[httpx.Response]", route.side_effect)
    _ = route.mock(side_effect=[*failures, *recorded])


def _rows(listed: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    return cast("Sequence[Mapping[str, object]]", listed["contacts"])


def _row(listed: Mapping[str, object], name: str) -> Mapping[str, object]:
    return next(row for row in _rows(listed) if row["display_name"] == name)


def _sent(route: Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(route.calls.last.request.content))


def _patched(routes: dict[tuple[str, str], Route]) -> tuple[str, Route]:
    [(path, route)] = [
        (path, route) for (method, path), route in routes.items() if method == "PATCH"
    ]
    return f"outlook:///contacts/{path.rsplit('/', 1)[1]}", route


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


class Contact:
    def __init__(self, graph: MockRouter, **held: object) -> None:
        self.record: dict[str, object] = {
            "id": TOM_ID,
            "displayName": "Tom Berger",
            "givenName": "Tom",
            "surname": "Berger",
            "companyName": "Acme",
            "businessPhones": [],
            "homePhones": [],
            "emailAddresses": [],
        } | held
        self.sent: list[Mapping[str, object]] = []
        _ = graph.get(f"{CONTACTS}/{TOM_ID}").mock(side_effect=self._answer)
        _ = graph.patch(f"{CONTACTS}/{TOM_ID}").mock(side_effect=self._change)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, json=self.record)

    def _change(self, request: httpx.Request) -> httpx.Response:
        sent = cast("Mapping[str, object]", json.loads(request.content))
        self.sent.append(sent)
        self.record |= {key: value for key, value in sent.items() if key != "@odata.type"}
        return self._answer(request)


class TestTheAssistantAnswersFromMiasContacts:
    async def test_it_gives_the_telephone_number_of_a_contact_from_the_list_and_the_full_read(
        self, graph: MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_read_contact-first")

        listed = await call("outlook_list_contacts")
        read = await call("outlook_read_contact", uri=FIRST_ROW)

        assert [key for key, route in routes.items() if not route.called] == []
        asked = routes[LISTING].calls.last.request.url.params
        assert "$filter" not in asked and "businessPhones" in asked["$select"]
        assert _row(listed, "Marc Dubois")["business_phones"] == ["+41 44 555 01 02"]
        assert read["business_phones"] == ["+41 44 555 01 02"]
        assert read["uri"] == FIRST_ROW

    async def test_it_keeps_the_address_of_each_contact_with_its_own_row(
        self, graph: MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_contacts-all")

        listed = await call("outlook_list_contacts")

        asked = routes[LISTING].calls.last.request.url.params
        assert "$filter" not in asked and "emailAddresses" in asked["$select"]
        assert _row(listed, "Marc Dubois")["email_addresses"] == [
            {"name": "Anna Meier", "address": "anna@example.test"}
        ]
        assert _row(listed, "Lena Fischer")["email_addresses"] == []

    async def test_it_gives_no_telephone_number_for_a_person_who_is_only_in_the_directory(
        self, graph: MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_contacts-all")
        _ = graph.get("/me").mock(
            return_value=httpx.Response(200, json={"id": "me", "mail": "mia@acme.example"})
        )
        _ = graph.get("/me/people").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "displayName": "Tom Berger",
                            "scoredEmailAddresses": [{"address": "tom@acme.example"}],
                            "personType": {"class": "Person", "subclass": "OrganizationUser"},
                            "phones": [{"type": "business", "number": "+41 44 555 01 04"}],
                        }
                    ]
                },
            )
        )

        contacts = await call("outlook_list_contacts")
        directory = await call("outlook_find_recipient", query="Tom Berger")

        assert all(row["display_name"] != "Tom Berger" for row in _rows(contacts))
        (tom,) = cast("Sequence[Mapping[str, object]]", directory["candidates"])
        assert tom["address"] == "tom@acme.example"
        assert "+41 44 555 01 04" not in json.dumps(directory)

    async def test_it_puts_a_first_name_that_fits_two_people_to_mia_without_choosing(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get("/me").mock(
            return_value=httpx.Response(200, json={"id": "me", "mail": "mia@acme.example"})
        )
        _ = graph.get("/me/people").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _person("Anna Meier", "anna.meier@acme.example"),
                        _person("Anna Weber", "anna.weber@acme.example"),
                    ]
                },
            )
        )

        found = await call("outlook_find_recipient", query="Anna")

        assert found["ambiguous"] is True
        assert [row["address"] for row in _candidates(found)] == [
            "anna.meier@acme.example",
            "anna.weber@acme.example",
        ]


def _person(name: str, address: str) -> dict[str, object]:
    return {
        "displayName": name,
        "scoredEmailAddresses": [{"address": address}],
        "personType": {"class": "Person", "subclass": "OrganizationUser"},
    }


def _candidates(found: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    return cast("Sequence[Mapping[str, object]]", found["candidates"])


class TestAChangeKeepsWhatTheContactHolds:
    async def test_it_saves_a_new_contact_with_the_details_mia_gave(
        self, graph: MockRouter
    ) -> None:

        def echo(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=json.loads(request.content) | {"id": TOM_ID})

        created = graph.post(CONTACTS).mock(side_effect=echo)

        saved = await call(
            "outlook_create_contact",
            given_name="Tom",
            surname="Berger",
            display_name="Tom Berger",
            email_addresses=["tom@acme.example"],
            business_phones=["+41 44 555 01 03"],
            home_phones=["+41 44 555 01 04"],
            mobile_phone="+41 79 555 01 05",
            company_name="Acme",
            job_title="Buyer",
        )

        assert created.call_count == 1
        assert _sent(created) == {
            "@odata.type": "#microsoft.graph.contact",
            "givenName": "Tom",
            "surname": "Berger",
            "displayName": "Tom Berger",
            "emailAddresses": [{"address": "tom@acme.example"}],
            "businessPhones": ["+41 44 555 01 03"],
            "homePhones": ["+41 44 555 01 04"],
            "mobilePhone": "+41 79 555 01 05",
            "companyName": "Acme",
            "jobTitle": "Buyer",
        }
        assert saved["uri"] == TOM

    async def test_it_adds_a_second_telephone_number_next_to_the_first(
        self, graph: MockRouter
    ) -> None:
        tom = Contact(graph, mobilePhone="+41 79 555 01 02")

        changed = await call(
            "outlook_update_contact", uri=TOM, add_business_phones=["+41 44 555 01 03"]
        )

        assert changed["mobile_phone"] == "+41 79 555 01 02"
        assert changed["business_phones"] == ["+41 44 555 01 03"]
        assert "mobilePhone" not in tom.sent[0]

    async def test_it_keeps_the_numbers_a_contact_has_when_it_adds_one(
        self, graph: MockRouter
    ) -> None:
        contact, _ = _patched(serve(graph, "rec-tool-outlook_update_contact-add-phone"))

        changed = await call(
            "outlook_update_contact", uri=contact, add_business_phones=["+41 44 555 01 06"]
        )

        assert changed["business_phones"] == ["+41 44 555 01 03", "+41 44 555 01 06"]

    async def test_it_does_not_add_a_number_that_the_contact_already_has(
        self, graph: MockRouter
    ) -> None:
        contact, patch = _patched(serve(graph, "rec-tool-outlook_update_contact-no-duplicate"))

        changed = await call(
            "outlook_update_contact", uri=contact, add_business_phones=["+41 44 555 01 03"]
        )

        assert changed["business_phones"] == ["+41 44 555 01 03"]
        assert _sent(patch)["businessPhones"] == ["+41 44 555 01 03"]

    async def test_it_refuses_to_clear_the_company_and_leaves_the_contact_as_it_is(
        self, graph: MockRouter
    ) -> None:
        tom = Contact(graph)

        with pytest.raises(ToolError, match="company_name"):
            _ = await call("outlook_update_contact", uri=TOM, company_name="")

        assert tom.sent == []
        assert tom.record["companyName"] == "Acme"


class TestANewContactHoldsOnlyWhatMiaGives:
    async def test_it_saves_no_contact_that_has_no_detail(self, graph: MockRouter) -> None:
        with pytest.raises(ToolError, match="No contact was created"):
            _ = await call("outlook_create_contact")

        assert graph.calls.call_count == 0

    async def test_it_saves_no_contact_with_an_address_that_is_not_an_address(
        self, graph: MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_create_contact",
                given_name="Tom",
                surname="Berger",
                email_addresses=["tom at acme"],
            )

        assert "'tom at acme'" in str(refused.value)
        assert "No contact was created" in str(refused.value)
        assert graph.calls.call_count == 0


class TestAContactThatCannotBeReadIsNeverReportedAsMissing:
    @pytest.mark.parametrize(
        ("fault", "told"),
        [
            pytest.param(_expired, SIGN_IN_AGAIN, id="sign-in-expired"),
            pytest.param(_busy, BUSY_30_SECONDS, id="busy-at-every-try"),
        ],
    )
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_tells_why_the_contacts_cannot_be_read(
        self, graph: MockRouter, fault: Callable[[], httpx.Response], told: str
    ) -> None:
        _ = graph.get(CONTACTS).mock(return_value=fault())

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_list_contacts")

        assert told in str(refused.value)

    async def test_it_waits_out_one_busy_answer_inside_the_same_call(
        self, graph: MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_contacts-all")
        _then_recorded(routes[LISTING], _busy())

        listed = await call("outlook_list_contacts")

        assert _row(listed, "Lena Fischer")["business_phones"] == ["+41 44 555 01 01"]
        assert retry_sleeps.delays == [30]

    @pytest.mark.parametrize("failure", THREE_FAILURES)
    async def test_it_reads_the_contacts_at_the_second_try_after_one_failure(
        self, graph: MockRouter, failure: str
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_contacts-all")
        _then_recorded(routes[LISTING], _failure(failure))

        with pytest.raises(ToolError, match=RETRY_ONCE):
            _ = await call("outlook_list_contacts")
        listed = await call("outlook_list_contacts")

        assert _row(listed, "Lena Fischer")["business_phones"] == ["+41 44 555 01 01"]

    async def test_it_reports_a_lookup_that_fails_twice_and_never_says_missing(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(CONTACTS).mock(side_effect=[_failure("fails-on-its-side")] * 2)

        with pytest.raises(ToolError) as first:
            _ = await call("outlook_list_contacts")
        with pytest.raises(ToolError) as second:
            _ = await call("outlook_list_contacts")

        assert STOP_AND_REPORT in str(first.value)
        assert STOP_AND_REPORT in str(second.value)

    async def test_it_tells_the_assistant_to_find_the_contact_again_when_a_read_finds_none(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(f"{CONTACTS}/{TOM_ID}").mock(return_value=_not_found())

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_read_contact", uri=TOM)

        assert "Find the contact again with outlook_list_contacts" in str(refused.value)
        assert NOT_FOUND in str(refused.value)

    async def test_it_tells_the_assistant_to_find_the_contact_again_when_a_change_finds_none(
        self, graph: MockRouter
    ) -> None:
        _ = graph.get(f"{CONTACTS}/{TOM_ID}").mock(return_value=_not_found())
        changed = graph.patch(f"{CONTACTS}/{TOM_ID}").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_update_contact", uri=TOM, add_business_phones=["+41 44 555 01 03"]
            )

        assert "nothing was changed" in str(refused.value)
        assert "Find the contact again with outlook_list_contacts" in str(refused.value)
        assert NOT_FOUND in str(refused.value)
        assert not changed.called

    async def test_it_stops_a_list_that_never_ends_and_says_so(self, graph: MockRouter) -> None:
        endless: dict[str, object] = {
            "@odata.nextLink": f"https://graph.microsoft.com/v1.0{CONTACTS}?$skip=50",
            "value": [],
        }

        def another_empty_page(request: httpx.Request) -> httpx.Response:
            _ = request
            return httpx.Response(200, json=endless)

        _ = graph.get(CONTACTS).mock(side_effect=another_empty_page)

        with pytest.raises(ToolError) as first:
            _ = await call("outlook_list_contacts")
        with pytest.raises(ToolError) as second:
            _ = await call("outlook_list_contacts")

        for refused in (first, second):
            assert "would not finish sending this list" in str(refused.value)
            assert STOP_AND_REPORT in str(refused.value)

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
                    _ = await client.call_tool("outlook_list_contacts", {})

        message = str(refused.value)
        assert "Contacts.Read" in message
        assert "administrator" in message
        assert "sign in to this connector again" in message
        assert graph.calls.call_count == 0


class TestAContactThatMicrosoftWillNotSaveIsNotCreated:
    @pytest.mark.parametrize(
        ("fault", "told"),
        [
            pytest.param(_expired, SIGN_IN_AGAIN, id="sign-in-expired"),
            pytest.param(_busy, BUSY_30_SECONDS, id="busy"),
        ],
    )
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_tells_why_the_contact_was_not_saved(
        self, graph: MockRouter, fault: Callable[[], httpx.Response], told: str
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_create_contact-person")
        saving = routes[("POST", CONTACTS)].mock(return_value=fault())

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_create_contact", given_name="Nora", surname="Weber")

        assert told in str(refused.value)
        assert saving.call_count == 1

    @pytest.mark.parametrize("failure", THREE_FAILURES)
    async def test_it_checks_the_contacts_before_it_saves_again(
        self, graph: MockRouter, failure: str
    ) -> None:
        saving = graph.post(CONTACTS).mock(side_effect=[_failure(failure)])

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_create_contact", given_name="Tom", surname="Berger")

        message = str(refused.value)
        assert "does not know if Microsoft 365 made the change" in message
        assert "Do not call this tool again first" in message
        assert "outlook_list_contacts" in message
        assert saving.call_count == 1


_NOT_A_HANDLE = "Tom Berger"


class TestAChangeToTheAddressesOfAContactKeepsTheOthers:
    async def test_it_adds_an_address_next_to_the_ones_the_contact_has_and_skips_a_repeat(
        self, graph: MockRouter
    ) -> None:
        tom = Contact(
            graph,
            emailAddresses=[{"name": "Tom Berger", "address": "tom@acme.example"}],
        )

        changed = await call(
            "outlook_update_contact",
            uri=TOM,
            add_email_addresses=["TOM@acme.example", "tom.berger@home.example"],
        )

        assert tom.sent[0]["emailAddresses"] == [
            {"name": "Tom Berger", "address": "tom@acme.example"},
            {"address": "tom.berger@home.example"},
        ]
        assert [
            row["address"] for row in cast("list[dict[str, str]]", changed["email_addresses"])
        ] == [
            "tom@acme.example",
            "tom.berger@home.example",
        ]

    async def test_it_removes_an_address_whatever_its_case_and_keeps_the_others(
        self, graph: MockRouter
    ) -> None:
        tom = Contact(
            graph,
            emailAddresses=[
                {"address": "tom@acme.example"},
                {"name": "No address"},
                {"address": "tom.berger@home.example"},
            ],
        )

        _ = await call(
            "outlook_update_contact", uri=TOM, remove_email_addresses=["TOM@ACME.example"]
        )

        assert tom.sent[0]["emailAddresses"] == [
            {"name": "No address"},
            {"address": "tom.berger@home.example"},
        ]


class TestAContactValueThatDoesNotFitChangesNothing:
    @pytest.mark.parametrize(
        ("tool", "arguments", "told"),
        [
            ("outlook_list_contacts", {"address": "Tom"}, "takes one SMTP address"),
            ("outlook_read_contact", {"uri": _NOT_A_HANDLE}, "is not one"),
            ("outlook_update_contact", {"uri": _NOT_A_HANDLE, "job_title": "CTO"}, "is not one"),
            ("outlook_update_contact", {"uri": TOM}, "needs at least one field to change"),
            (
                "outlook_update_contact",
                {"uri": TOM, "add_email_addresses": ["tom at acme"]},
                "'tom at acme'",
            ),
            (
                "outlook_update_contact",
                {"uri": TOM, "add_email_addresses": ["a@acme.example", "A@acme.example"]},
                "twice",
            ),
            (
                "outlook_update_contact",
                {
                    "uri": TOM,
                    "add_email_addresses": ["a@acme.example"],
                    "remove_email_addresses": ["A@acme.example"],
                },
                "is in both `add_email_addresses` and `remove_email_addresses`",
            ),
            (
                "outlook_update_contact",
                {
                    "uri": TOM,
                    "add_home_phones": ["+41 44 555 01 03"],
                    "remove_home_phones": ["+41 44 555 01 03"],
                },
                "is in both `add_home_phones` and `remove_home_phones`",
            ),
        ],
        ids=[
            "list-name-for-address",
            "read-name-for-handle",
            "update-name-for-handle",
            "update-nothing",
            "update-bad-address",
            "update-repeated-address",
            "update-address-in-both-lists",
            "update-phone-in-both-lists",
        ],
    )
    async def test_it_refuses_the_call_before_it_asks_microsoft(
        self, graph: MockRouter, tool: str, arguments: dict[str, object], told: str
    ) -> None:
        advice = await refusal_of(tool, arguments)

        assert told in advice
        assert graph.calls.call_count == 0


class TestAContactIsReadAsMicrosoftHoldsIt:
    async def test_it_reads_a_contact_that_holds_no_postal_address_as_having_none(
        self, graph: MockRouter
    ) -> None:
        _ = Contact(graph)

        read = await call("outlook_read_contact", uri=TOM)

        assert (read["business_address"], read["home_address"], read["other_address"]) == (
            None,
            None,
            None,
        )

    async def test_it_lists_the_contacts_that_hold_one_address(self, graph: MockRouter) -> None:
        listing = graph.get(CONTACTS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": TOM_ID,
                            "displayName": "Tom Berger",
                            "emailAddresses": [{"address": "tom@acme.example"}],
                        }
                    ]
                },
            )
        )

        listed = await call("outlook_list_contacts", address=" tom@o'brien.example ")

        asked = listing.calls.last.request.url.params["$filter"]
        assert asked == "emailAddresses/any(a:a/address eq 'tom@o''brien.example')"
        assert [row["display_name"] for row in _rows(listed)] == ["Tom Berger"]
