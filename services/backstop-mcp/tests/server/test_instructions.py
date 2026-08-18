"""Server instructions carry the ownership map; field docs live on the tools themselves."""

from backstop_mcp.server.instructions import INSTRUCTIONS


class TestInstructions:
    def test_carry_the_ownership_map(self) -> None:
        assert "get_opportunities" in INSTRUCTIONS
        assert "get_product_positions" in INSTRUCTIONS
        assert "assets under management" in INSTRUCTIONS
        assert "get_people_for_party" in INSTRUCTIONS
        assert "numberOfEmployees" in INSTRUCTIONS
        assert "get_activity_history" in INSTRUCTIONS
        assert "representative" in INSTRUCTIONS
        assert "list_custom_fields" in INSTRUCTIONS
        assert "describe_data_model" not in INSTRUCTIONS
