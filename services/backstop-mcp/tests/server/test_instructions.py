"""Server instructions carry the ownership map; field docs live on the tools themselves."""

from backstop_mcp.server.instructions import INSTRUCTIONS


class TestInstructions:
    def test_carry_the_ownership_map(self) -> None:
        assert "get_opportunities" in INSTRUCTIONS
        assert "get_time_series" in INSTRUCTIONS
        assert "get_product_investors" in INSTRUCTIONS
        assert "not on get_product_investors" in INSTRUCTIONS
        assert "omit all three selectors" in INSTRUCTIONS
        assert "assets under management" in INSTRUCTIONS
        assert "get_people_for_party" in INSTRUCTIONS
        assert "numberOfEmployees" in INSTRUCTIONS
        assert "search_activities" in INSTRUCTIONS
        assert "get_activity_history" in INSTRUCTIONS
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
        assert "get_opportunities_by_ids" in INSTRUCTIONS
        assert "custom_fields_unavailable" in INSTRUCTIONS
        assert "say Backstop does not record it" in INSTRUCTIONS
        assert "get_capital_flows" in INSTRUCTIONS
        assert "account.id" in INSTRUCTIONS
        assert "get_tasks_for_party" in INSTRUCTIONS
        assert "attachment list" in INSTRUCTIONS
        assert "row's `id`" in INSTRUCTIONS
        assert "log_activity" in INSTRUCTIONS
        assert "attach_file" in INSTRUCTIONS
        assert INSTRUCTIONS.index("log_activity") < INSTRUCTIONS.index("attach_file")
        assert "a file blob never goes on it either" in INSTRUCTIONS
        assert "no email kind on log_activity" in INSTRUCTIONS
        assert "list_activity_tags" in INSTRUCTIONS
        assert "tags are never created" in INSTRUCTIONS
        assert "list_contact_sources" in INSTRUCTIONS
        assert "contact_source_id" in INSTRUCTIONS
        assert "list_contact_categories" in INSTRUCTIONS
        assert "category_ids" in INSTRUCTIONS
        assert "Key employee is read-only" in INSTRUCTIONS
        assert "CRM UI" in INSTRUCTIONS
        assert "delete_activity" in INSTRUCTIONS
        assert "delete_person" in INSTRUCTIONS
        assert "delete_organization" in INSTRUCTIONS
        assert "delete_opportunity" in INSTRUCTIONS
        assert "no recycle bin" in INSTRUCTIONS
        assert "all test records" in INSTRUCTIONS
        assert "search-then-delete" in INSTRUCTIONS
        assert "exact name, short name, or id is one vehicle" in INSTRUCTIONS
        assert "read `source` and `data_caveat`" in INSTRUCTIONS

    def test_state_the_party_identity_model_before_any_tool(self) -> None:
        """`party_id` + `search_type` is the precondition of half the tools; say it once, first."""
        assert "Omission is rejected only on tools that say so" in INSTRUCTIONS
        assert "two separate arguments" in INSTRUCTIONS
        assert "a contacts or employees id is not a people id" in INSTRUCTIONS
        assert "candidates" in INSTRUCTIONS
        assert "not_found" in INSTRUCTIONS
        assert INSTRUCTIONS.index("Omission is rejected only on tools that say so") < (
            INSTRUCTIONS.index("get_person")
        )

    def test_carry_the_write_and_auxiliary_tools(self) -> None:
        for tool in (
            "create_person",
            "create_organization",
            "create_employment",
            "end_employment",
            "update_person",
            "update_organization",
            "create_opportunity",
            "update_opportunity",
            "update_custom_field_values",
            "list_custom_field_groups",
            "run_report",
            "build_backstop_links",
            "parse_backstop_link",
        ):
            assert tool in INSTRUCTIONS, tool
        assert "Stage moves only via update_opportunity" in INSTRUCTIONS
        assert "a repeated call makes a second record" in INSTRUCTIONS
        assert "`records[].status`" in INSTRUCTIONS
        assert "applied_count == total_count" in INSTRUCTIONS
        assert "no endpoint that lists reports" in INSTRUCTIONS
        assert "Never hand-write a Backstop URL" in INSTRUCTIONS
        assert "no tool that loads the account by id" in INSTRUCTIONS
        assert "backfill_opportunity_stage_history" in INSTRUCTIONS
