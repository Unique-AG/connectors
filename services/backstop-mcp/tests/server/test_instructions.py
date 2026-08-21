"""Server instructions carry the ownership map; field docs live on the tools themselves."""

from backstop_mcp.server.instructions import INSTRUCTIONS


class TestInstructions:
    def test_carry_the_ownership_map(self) -> None:
        assert "get_opportunities" in INSTRUCTIONS
        assert "get_time_series" in INSTRUCTIONS
        assert "get_product_investors" in INSTRUCTIONS
        assert "not on get_product_investors" in INSTRUCTIONS
        assert "get_product (`search`" in INSTRUCTIONS
        assert "assets under management" in INSTRUCTIONS
        assert "get_people_for_party" in INSTRUCTIONS
        assert "numberOfEmployees" in INSTRUCTIONS
        assert "search_activities" in INSTRUCTIONS
        assert "get_activity_history" in INSTRUCTIONS
        assert "filtered search" in INSTRUCTIONS
        assert "one year before end_date" in INSTRUCTIONS
        assert "always start with search_activities" in INSTRUCTIONS
        assert "do not start with it" in INSTRUCTIONS
        assert "get_activity_detail" in INSTRUCTIONS
        history = INSTRUCTIONS.index("get_activity_history")
        assert INSTRUCTIONS.index("search_activities") < history
        assert history < INSTRUCTIONS.index("get_activity_detail")
        assert "representative" in INSTRUCTIONS
        assert "list_custom_fields" in INSTRUCTIONS
        assert "describe_data_model" not in INSTRUCTIONS
        assert "get_accounts_for_party" in INSTRUCTIONS
        assert INSTRUCTIONS.index("get_accounts_for_party") < INSTRUCTIONS.index("get_time_series")
        assert "Do not iterate every account in a fund" in INSTRUCTIONS
        assert "list_system_users" in INSTRUCTIONS
        assert "search_opportunities" in INSTRUCTIONS
        assert INSTRUCTIONS.index("list_system_users") < INSTRUCTIONS.index("search_opportunities")
        assert "takes that login, not a display name" in INSTRUCTIONS
        assert "get_capital_flows" in INSTRUCTIONS
        assert "account.id" in INSTRUCTIONS
        assert "get_tasks_for_party" in INSTRUCTIONS
        assert "not on get_people_for_party" in INSTRUCTIONS
        assert "attachment list" in INSTRUCTIONS
        assert "row's `id`" in INSTRUCTIONS
        assert "falls back internally" in INSTRUCTIONS
