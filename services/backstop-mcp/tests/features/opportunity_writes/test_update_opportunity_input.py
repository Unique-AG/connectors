"""`UpdateOpportunityInput`: at least one change field; stage date requires stage."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.opportunity_writes import UpdateOpportunityInput

_ADAPTER: TypeAdapter[UpdateOpportunityInput] = TypeAdapter(UpdateOpportunityInput)


def test_accepts_a_stage_patch() -> None:
    parsed = _ADAPTER.validate_python({"opportunity_id": "5755101", "stage": "IDD"})

    assert parsed.opportunity_id == "5755101"
    assert parsed.stage == "IDD"


def test_rejects_an_update_with_no_change_fields() -> None:
    with pytest.raises(ValidationError, match="Pass at least one field to change"):
        _ADAPTER.validate_python({"opportunity_id": "5755101"})


def test_empty_replace_users_to_notify_counts_as_a_change() -> None:
    parsed = _ADAPTER.validate_python({"opportunity_id": "5755101", "replace_users_to_notify": []})

    assert parsed.replace_users_to_notify == ()


def test_stage_effective_date_without_stage_is_rejected() -> None:
    with pytest.raises(ValidationError, match="stage_effective_date requires stage"):
        _ADAPTER.validate_python(
            {"opportunity_id": "5755101", "stage_effective_date": "2026-09-14"}
        )


def test_empty_add_users_to_notify_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"opportunity_id": "5755101", "add_users_to_notify": []})


def test_probability_must_be_a_fraction() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"opportunity_id": "5755101", "probability": 30})
    parsed = _ADAPTER.validate_python({"opportunity_id": "5755101", "probability": 0.3})
    assert parsed.probability == 0.3


def test_add_and_replace_users_to_notify_together_are_rejected() -> None:
    with pytest.raises(ValidationError, match="not both"):
        _ADAPTER.validate_python(
            {
                "opportunity_id": "5755101",
                "add_users_to_notify": ["jdoe"],
                "replace_users_to_notify": ["jdoe"],
            }
        )
