from backstop_mcp.utils import presence_flags


class TestPresenceFlags:
    def test_flags_each_named_argument_by_whether_it_is_set(self) -> None:
        arguments = {"name": "West", "email": None, "cursor": "", "limit": 5}

        assert presence_flags(arguments, "name", "email", "cursor") == {
            "has_name": True,
            "has_email": False,
            "has_cursor": True,
        }

    def test_never_carries_the_filter_value(self) -> None:
        flags = presence_flags({"name": "West"}, "name")

        assert "West" not in str(flags)
