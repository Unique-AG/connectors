"""`extract_gist_from_html`: HTML→Markdown conversion, squeeze, and word-boundary truncation.

Each test targets one behaviour called out in the design: table rows survive as Markdown pipe
rows while markdownify's synthetic empty header is squeezed out, entities decode, blank-line
runs collapse, short input is left alone, long input truncates on a real word boundary and
reports the correct pre-truncation length, and the `max_chars` boundary itself is exact.
"""

from backstop_mcp.features.activity_history import Gist, extract_gist_from_html


class TestTableConversion:
    """A `<th>`-less layout table is markdownify's exact use case for this feature (see the
    module's design doc): it renders pipe rows instead of flattening firm/person pairs into a
    run-on line, but it also invents a blank header + separator row that must not survive.
    """

    def test_td_only_table_rows_survive_as_markdown_pipe_rows(self) -> None:
        html = (
            "<table>"
            "<tr><td>Allstate Investment Management</td><td>Aaron</td><td>Lemner</td></tr>"
            "<tr><td>Efficient Capital Management</td><td>Bruce</td><td>Aulie</td></tr>"
            "</table>"
        )

        gist = extract_gist_from_html(html, max_chars=300)

        assert gist == Gist(
            text=(
                "| Allstate Investment Management | Aaron | Lemner |\n"
                "| Efficient Capital Management | Bruce | Aulie |"
            ),
            truncated=False,
            full_length=len(gist.text),
        )

    def test_synthetic_empty_header_and_separator_are_dropped(self) -> None:
        html = "<table><tr><td>A</td><td>B</td></tr></table>"

        gist = extract_gist_from_html(html, max_chars=300)

        assert "---" not in gist.text
        assert "|  |" not in gist.text
        assert gist.text == "| A | B |"

    def test_a_real_th_header_is_not_mistaken_for_the_synthetic_one(self) -> None:
        html = (
            "<table>"
            "<tr><th>Firm</th><th>First</th></tr>"
            "<tr><td>Allstate Investment Management</td><td>Aaron</td></tr>"
            "</table>"
        )

        gist = extract_gist_from_html(html, max_chars=300)

        assert gist.text.splitlines()[0] == "| Firm | First |"

    def test_a_genuine_blank_spacer_row_deeper_in_a_th_table_survives(self) -> None:
        # A blank-cells row is markdownify's synthetic-header *shape*, but it's only the
        # synthetic artifact when it's the first row of the table block. Here it's the second
        # data row of a `<th>`-headered table, so it must survive.
        html = (
            "<table>"
            "<tr><th>Firm</th><th>Status</th></tr>"
            "<tr><td></td><td></td></tr>"
            "<tr><td>Real Corp</td><td>Active</td></tr>"
            "</table>"
        )

        gist = extract_gist_from_html(html, max_chars=300)

        assert gist.text == ("| Firm | Status |\n| --- | --- |\n|  |  |\n| Real Corp | Active |")

    def test_a_dash_placeholder_row_deeper_in_a_th_table_survives(self) -> None:
        # A row of `-` cells (an "N/A" placeholder) is shaped like a separator row, but only the
        # first two lines of a table block are ever markdownify's synthetic artifact.
        html = (
            "<table>"
            "<tr><th>Firm</th><th>Status</th></tr>"
            "<tr><td>-</td><td>-</td></tr>"
            "<tr><td>Real Corp</td><td>Active</td></tr>"
            "</table>"
        )

        gist = extract_gist_from_html(html, max_chars=300)

        assert gist.text == ("| Firm | Status |\n| --- | --- |\n| - | - |\n| Real Corp | Active |")

    def test_blank_spacer_and_dash_placeholder_rows_both_survive_together(self) -> None:
        # The exact reproduction from the bug report: both a genuine blank spacer row and a
        # dash-placeholder row sit between the real header and the real data row.
        html = (
            "<table>"
            "<tr><th>Firm</th><th>Status</th></tr>"
            "<tr><td></td><td></td></tr>"
            "<tr><td>-</td><td>-</td></tr>"
            "<tr><td>Real Corp</td><td>Active</td></tr>"
            "</table>"
        )

        gist = extract_gist_from_html(html, max_chars=300)

        assert gist.text == (
            "| Firm | Status |\n| --- | --- |\n|  |  |\n| - | - |\n| Real Corp | Active |"
        )

    def test_two_consecutive_td_only_tables_each_get_their_own_header_stripped(self) -> None:
        html = (
            "<table><tr><td>A</td><td>B</td></tr></table>"
            "<table><tr><td>C</td><td>D</td></tr></table>"
        )

        gist = extract_gist_from_html(html, max_chars=300)

        assert gist.text == "| A | B |\n\n| C | D |"

    def test_td_only_table_not_first_in_document_still_gets_header_stripped(self) -> None:
        html = "<p>Some intro text.</p><table><tr><td>A</td><td>B</td></tr></table>"

        gist = extract_gist_from_html(html, max_chars=300)

        assert gist.text == "Some intro text.\n\n| A | B |"


class TestEntityDecoding:
    def test_ampersand_and_numeric_entities_decode(self) -> None:
        gist = extract_gist_from_html("<p>Bell &amp; Howell &#39;n Co&#39;</p>", max_chars=300)

        assert gist.text == "Bell & Howell 'n Co'"


class TestBlankLineSqueeze:
    def test_runs_of_blank_lines_collapse_to_one(self) -> None:
        # `<br>` repeated four times produces several markdownify-emitted whitespace-only lines
        # between the two paragraphs, not just literal "\n\n\n" — the squeeze must catch both.
        html = "<p>A</p><br><br><br><br><p>B</p>"

        gist = extract_gist_from_html(html, max_chars=300)

        assert gist.text == "A\n\nB"
        assert "\n\n\n" not in gist.text


class TestShortInputIsUntouched:
    def test_short_input_is_not_truncated(self) -> None:
        gist = extract_gist_from_html("<p>short</p>", max_chars=300)

        assert gist == Gist(text="short", truncated=False, full_length=5)

    def test_empty_html_produces_an_empty_gist(self) -> None:
        gist = extract_gist_from_html("", max_chars=300)

        assert gist == Gist(text="", truncated=False, full_length=0)

    def test_whitespace_only_html_produces_an_empty_gist(self) -> None:
        gist = extract_gist_from_html("<div>   </div>", max_chars=300)

        assert gist == Gist(text="", truncated=False, full_length=0)

    def test_no_text_html_produces_an_empty_gist(self) -> None:
        gist = extract_gist_from_html("<p>&nbsp;</p>", max_chars=300)

        assert gist == Gist(text="", truncated=False, full_length=0)


class TestTruncation:
    def test_long_input_truncates_at_a_word_boundary_and_reports_full_length(self) -> None:
        words = " ".join(f"word{i}" for i in range(100))
        html = f"<p>{words}</p>"
        full_markdown_length = len(words)

        gist = extract_gist_from_html(html, max_chars=50)

        assert gist.truncated is True
        assert gist.full_length == full_markdown_length
        assert len(gist.text) <= 50
        # Landed on a real word boundary: the text is a clean prefix ending right before a space.
        assert words.startswith(gist.text)
        assert words[len(gist.text)] == " "
        assert not gist.text.endswith(" ")

    def test_exactly_at_the_limit_is_not_truncated(self) -> None:
        html = "<p>abcde fghij klmno</p>"  # 17 characters once converted

        gist = extract_gist_from_html(html, max_chars=17)

        assert gist == Gist(text="abcde fghij klmno", truncated=False, full_length=17)

    def test_one_char_over_the_limit_truncates_to_the_prior_word_boundary(self) -> None:
        html = "<p>abcde fghij klmno</p>"  # 17 characters once converted

        gist = extract_gist_from_html(html, max_chars=16)

        assert gist == Gist(text="abcde fghij", truncated=True, full_length=17)

    def test_truncation_counts_characters_not_bytes(self) -> None:
        # Each "café" repeat is 4 characters but 5 UTF-8 bytes (the "é" is 2 bytes) — if
        # `full_length`/truncation counted bytes instead of characters, the reported length and
        # the cut point would both be wrong for this input.
        words = " ".join(["café"] * 20)
        html = f"<p>{words}</p>"

        gist = extract_gist_from_html(html, max_chars=10)

        assert gist.truncated is True
        assert gist.full_length == len(words)
        assert gist.full_length != len(words.encode())
        assert gist.text == "café café"
        assert len(gist.text) == 9

    def test_truncation_never_lands_mid_word(self) -> None:
        words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
        full_text = " ".join(words)
        html = f"<p>{full_text}</p>"

        for max_chars in range(1, len(full_text)):
            gist = extract_gist_from_html(html, max_chars=max_chars)
            if " " in gist.text:
                # Cut on a real boundary: every token but is a complete word.
                assert all(token in words for token in gist.text.split(" "))
            else:
                # No whitespace fit in the truncation window at all (`max_chars` smaller than
                # the first word) — the documented fallback is a hard cut, so this is at most
                # a prefix of "alpha", never a boundary-respecting cut of anything longer.
                assert words[0].startswith(gist.text)
