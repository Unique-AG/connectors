from office_365_mcp.shared import prose


class TestBodyOpening:
    def test_tags_are_stripped(self) -> None:
        assert prose.body_opening("<p>Hello <b>world</b></p>") == "Hello world"

    def test_an_escaped_tag_reads_as_text_not_a_tag(self) -> None:
        assert prose.body_opening("<p>&lt;p&gt;not a tag&lt;/p&gt;</p>") == "<p>not a tag</p>"

    def test_whitespace_is_collapsed(self) -> None:
        opened = prose.body_opening("<p>Line one\n\n  Line   two</p>")

        assert opened == "Line one Line two"

    def test_a_long_body_is_cut_at_120_characters_with_an_ellipsis(self) -> None:
        opened = prose.body_opening(f"<p>{'word ' * 40}</p>")

        assert len(opened) == 121
        assert opened.endswith("…")

    def test_a_short_body_is_returned_whole(self) -> None:
        assert prose.body_opening("<p>Short body</p>") == "Short body"

    def test_an_empty_body_is_returned_empty(self) -> None:
        assert prose.body_opening("") == ""
