"""`delete_opportunity` input: opportunity id."""

from backstop_mcp.features.opportunity_writes import DeleteOpportunityInput


def test_accepts_opportunity_id() -> None:
    parsed = DeleteOpportunityInput.model_validate({"opportunity_id": "5755101"})

    assert parsed.opportunity_id == "5755101"
