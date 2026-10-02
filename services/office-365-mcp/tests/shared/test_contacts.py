import json

import pytest
from kiota_serialization_json.json_parse_node_factory import JsonParseNodeFactory
from msgraph.generated.models.contact import Contact
from pydantic import TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

from office_365_mcp.shared.contacts import (
    SUMMARY_FIELDS,
    ContactEmailAddress,
    ContactSummary,
    PhoneNumber,
    not_one_address,
    repeated_entry,
)
from office_365_mcp.shared.handles import ContactHandle, contact_handle

_CONTACT_ID = "AAMkAGI2SYNTHETIC-contact-0001="

_SAME_FAILURE = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)


def _parsed(payload: dict[str, object]) -> Contact:
    node = JsonParseNodeFactory().get_root_parse_node(
        "application/json", json.dumps(payload).encode()
    )
    contact = node.get_object_value(Contact)
    assert contact is not None
    return contact


def test_a_row_carries_what_graph_reported_and_the_handle_that_reads_it() -> None:
    contact = _parsed(
        {
            "id": _CONTACT_ID,
            "displayName": "Alex Wilber",
            "givenName": "Alex",
            "surname": "Wilber",
            "emailAddresses": [
                {"name": "Alex Wilber", "address": "alexw@example.invalid"},
                {"name": "Alex Wilber", "address": "alex.wilber@example.invalid"},
            ],
            "businessPhones": ["+1 425 555 0109"],
            "homePhones": [],
            "mobilePhone": "+1 425 555 0110",
            "companyName": "Contoso",
            "jobTitle": "Web Marketing Manager",
            "personalNotes": "a note that only the full read returns",
        }
    )

    row = ContactSummary.from_contact(contact)

    assert row == ContactSummary(
        uri=ContactHandle(_CONTACT_ID).uri,
        display_name="Alex Wilber",
        given_name="Alex",
        surname="Wilber",
        email_addresses=[
            ContactEmailAddress(name="Alex Wilber", address="alexw@example.invalid"),
            ContactEmailAddress(name="Alex Wilber", address="alex.wilber@example.invalid"),
        ],
        business_phones=["+1 425 555 0109"],
        home_phones=[],
        mobile_phone="+1 425 555 0110",
        company_name="Contoso",
        job_title="Web Marketing Manager",
    )
    assert contact_handle(row.uri) == ContactHandle(_CONTACT_ID)


def test_the_selected_fields_are_the_id_and_one_property_for_each_field_of_a_row() -> None:
    expected = ("id", *(to_camel(name) for name in ContactSummary.model_fields if name != "uri"))

    assert expected == SUMMARY_FIELDS


def test_every_selected_field_is_a_property_of_a_graph_contact() -> None:
    assert set(SUMMARY_FIELDS) <= set(Contact().get_field_deserializers())


def test_a_contact_with_nothing_but_an_id_answers_nulls_and_empty_lists() -> None:
    row = ContactSummary.from_contact(_parsed({"id": _CONTACT_ID}))

    assert row.display_name is None
    assert row.given_name is None
    assert row.surname is None
    assert row.email_addresses == []
    assert row.business_phones == []
    assert row.home_phones == []
    assert row.mobile_phone is None
    assert row.company_name is None
    assert row.job_title is None


def test_an_address_with_no_name_keeps_the_address() -> None:
    row = ContactSummary.from_contact(
        _parsed({"id": _CONTACT_ID, "emailAddresses": [{"address": "alexw@example.invalid"}]})
    )

    assert row.email_addresses == [ContactEmailAddress(name=None, address="alexw@example.invalid")]


def test_a_contact_with_no_id_is_a_broken_graph_answer() -> None:
    with pytest.raises(AssertionError, match="no id"):
        _ = ContactSummary.from_contact(_parsed({"displayName": "Alex Wilber"}))


def test_the_refusal_names_the_entry_and_what_did_not_happen() -> None:
    refusal = not_one_address("Alex Wilber", nothing_happened="No contact was created.")

    assert "must be one SMTP address" in refusal
    assert "'Alex Wilber'" in refusal
    assert "No contact was created." in refusal


def test_the_refusal_of_an_entry_ends_with_the_canonical_retry_sentence() -> None:
    refusal = not_one_address("alexw@", nothing_happened="Nothing was changed.")

    assert refusal.endswith(_SAME_FAILURE)


def test_the_refusal_of_a_repeat_names_the_entry_and_the_case_rule() -> None:
    refusal = repeated_entry("ALEXW@example.invalid", nothing_happened="Nothing was changed.")

    assert "'ALEXW@example.invalid'" in refusal
    assert "A change of case does not make a second address." in refusal
    assert "Nothing was changed." in refusal


def test_the_refusal_of_a_repeat_ends_with_the_canonical_retry_sentence() -> None:
    refusal = repeated_entry("alexw@example.invalid", nothing_happened="No contact was created.")

    assert refusal.endswith(_SAME_FAILURE)


class TestThePhoneNumber:
    def test_a_list_of_numbers_is_accepted(self) -> None:
        assert TypeAdapter(list[PhoneNumber]).validate_python(["+1 425 555 0109"]) == [
            "+1 425 555 0109"
        ]

    def test_a_number_with_spaces_around_a_visible_character_is_kept_as_given(self) -> None:
        assert TypeAdapter(list[PhoneNumber]).validate_python([" +1 425 555 0109 "]) == [
            " +1 425 555 0109 "
        ]

    @pytest.mark.parametrize("number", ["", "  ", "\t"], ids=["empty", "spaces", "tab"])
    def test_a_number_with_no_visible_character_is_refused(self, number: str) -> None:
        with pytest.raises(ValidationError):
            _ = TypeAdapter(list[PhoneNumber]).validate_python([number])

    def test_the_schema_inlines_a_minimum_length_of_one_and_a_visible_character(self) -> None:
        schema = TypeAdapter(list[PhoneNumber]).json_schema()

        assert schema["items"]["minLength"] == 1
        assert schema["items"]["pattern"] == "\\S"
        assert "$ref" not in json.dumps(schema)
