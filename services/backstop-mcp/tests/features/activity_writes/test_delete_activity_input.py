"""`delete_activity` input: kind plus activity id."""

from backstop_mcp.features.activity_writes import DeleteActivityInput


def test_accepts_kind_and_activity_id() -> None:
    parsed = DeleteActivityInput.model_validate({"kind": "document", "activity_id": "88002233"})

    assert parsed.kind == "document"
    assert parsed.activity_id == "88002233"
