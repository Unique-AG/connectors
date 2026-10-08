import json

import pytest
from kiota_serialization_json.json_parse_node_factory import JsonParseNodeFactory
from msgraph.generated.models.inference_classification_override import (
    InferenceClassificationOverride,
)

from office_365_mcp.shared.focused_inbox import FocusedOverride


def _parsed(payload: dict[str, object]) -> InferenceClassificationOverride:
    node = JsonParseNodeFactory().get_root_parse_node(
        "application/json", json.dumps(payload).encode()
    )
    override = node.get_object_value(InferenceClassificationOverride)
    assert override is not None
    return override


def _payload(
    *,
    classify_as: str | None = "focused",
    sender: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": "98f5bdef-576a-404d-a2ea-07a3cf11a9b9",
        "classifyAs": classify_as,
        "senderEmailAddress": (
            {"name": "Grace Hopper", "address": "grace@example.invalid"}
            if sender is None
            else sender
        ),
    }


def test_a_row_carries_the_address_the_name_and_the_tab_that_graph_reported() -> None:
    row = FocusedOverride.from_override(_parsed(_payload(classify_as="other")))

    assert row == FocusedOverride(
        sender_address="grace@example.invalid", sender_name="Grace Hopper", classify_as="other"
    )


def test_the_sender_address_names_the_tool_that_takes_it_only_after_a_guard() -> None:
    described = FocusedOverride.model_fields["sender_address"].description or ""

    assert (
        "If this deployment exposes outlook_set_focused_override, use this value as `sender` "
        "in that tool."
    ) in described


@pytest.mark.parametrize("tab", ["focused", "other"])
def test_each_tab_reads_as_its_wire_value(tab: str) -> None:
    row = FocusedOverride.from_override(_parsed(_payload(classify_as=tab)))

    assert row.classify_as == tab


def test_a_sender_with_no_stored_name_reads_a_null_name() -> None:
    row = FocusedOverride.from_override(
        _parsed(_payload(sender={"address": "grace@example.invalid"}))
    )

    assert row.sender_name is None
    assert row.sender_address == "grace@example.invalid"


def test_a_tab_that_this_service_does_not_know_reads_null() -> None:
    row = FocusedOverride.from_override(_parsed(_payload(classify_as="somethingNew")))

    assert row.classify_as is None


def test_a_row_with_no_tab_reads_null() -> None:
    row = FocusedOverride.from_override(_parsed(_payload(classify_as=None)))

    assert row.classify_as is None


def test_a_row_with_a_name_and_no_sender_address_is_a_programming_error() -> None:
    with pytest.raises(AssertionError, match="no sender address"):
        _ = FocusedOverride.from_override(_parsed(_payload(sender={"name": "Grace Hopper"})))


def test_a_row_with_no_sender_at_all_is_a_programming_error() -> None:
    payload = _payload()
    del payload["senderEmailAddress"]

    with pytest.raises(AssertionError, match="no sender address"):
        _ = FocusedOverride.from_override(_parsed(payload))
