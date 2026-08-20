"""Server instructions carry the ownership map; field docs live on the tools themselves."""

from backstop_mcp.server.instructions import INSTRUCTIONS


class TestInstructions:
    def test_carry_the_ownership_map(self) -> None:
        assert "get_opportunities" in INSTRUCTIONS
        assert "get_time_series" in INSTRUCTIONS
        assert "get_product_investors" in INSTRUCTIONS
        assert "assets under management" in INSTRUCTIONS
        assert "get_people_for_party" in INSTRUCTIONS
        assert "numberOfEmployees" in INSTRUCTIONS
        assert "search_activities" in INSTRUCTIONS
        assert "get_activity_history" in INSTRUCTIONS
        assert "get_activity_detail" in INSTRUCTIONS
        history = INSTRUCTIONS.index("get_activity_history")
        assert INSTRUCTIONS.index("search_activities") < history
        assert history < INSTRUCTIONS.index("get_activity_detail")
        assert "representative" in INSTRUCTIONS
        assert "list_custom_fields" in INSTRUCTIONS
        assert "describe_data_model" not in INSTRUCTIONS
