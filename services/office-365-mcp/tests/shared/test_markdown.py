from office_365_mcp.shared.markdown import body_to_html, html_link_targets, links_in_body


class TestMarkdownBody:
    def test_markdown_becomes_html_and_raw_html_is_escaped(self) -> None:
        assert body_to_html("**Ship** it <b>Friday</b>.", "markdown") == (
            "<p><strong>Ship</strong> it &lt;b&gt;Friday&lt;/b&gt;.</p>"
        )


class TestHtmlBody:
    def test_passes_the_html_through_unchanged(self) -> None:
        styled = (
            '<table style="border-collapse: collapse"><tr><td style="color: #c00">Q3</td></tr>'
            + '</table><img src="https://example.com/logo.png"><a href="/relative">x</a>'
            + "<script>run()</script>"
        )

        assert body_to_html(styled, "html") == styled


class TestHtmlLinkTargets:
    def test_lists_every_link_once_in_document_order(self) -> None:
        body = (
            '<p><a href="https://b.example">b</a> <a href="mailto:a@example.com">a</a>'
            + ' <a href="https://b.example">again</a> <a>no target</a></p>'
        )

        assert html_link_targets(body) == ("https://b.example", "mailto:a@example.com")

    def test_finds_a_link_that_only_desktop_outlook_shows(self) -> None:
        body = (
            '<a href="https://web.example">web</a>'
            + '<!--[if mso]><a href="https://desktop.example">desktop</a><![endif]-->'
        )

        assert html_link_targets(body) == ("https://web.example", "https://desktop.example")

    def test_finds_the_link_of_a_desktop_outlook_shape_once_in_document_order(self) -> None:
        body = (
            '<a href="https://first.example">first</a>'
            + '<!--[if mso]><v:roundrect href="https://button.example" arcsize="10%">'
            + "<center>Open</center></v:roundrect><![endif]-->"
            + '<!--[if !mso]><!--><a href="https://button.example">Open</a><!--<![endif]-->'
        )

        assert html_link_targets(body) == ("https://first.example", "https://button.example")

    def test_finds_the_link_of_an_image_map_area(self) -> None:
        body = (
            '<map name="m"><area shape="rect" coords="0,0,9,9" href="https://area.example"></map>'
        )

        assert html_link_targets(body) == ("https://area.example",)

    def test_ignores_a_link_in_an_ordinary_comment(self) -> None:
        body = '<!-- <a href="https://hidden.example">old</a> --><p>Hi</p>'

        assert html_link_targets(body) == ()

    def test_finds_the_links_a_markdown_body_renders_to(self) -> None:
        rendered = body_to_html(
            "See [the plan](https://plan.example) and <https://raw.example>.", "markdown"
        )

        assert html_link_targets(rendered) == ("https://plan.example", "https://raw.example")


class TestLinksInBody:
    def test_names_every_link_for_a_question(self) -> None:
        body = '<a href="https://a.example">x</a><a href="https://b.example">y</a>'

        assert links_in_body(body) == " It links to 'https://a.example', 'https://b.example'."

    def test_says_nothing_when_the_body_has_no_link(self) -> None:
        assert links_in_body("<p>No links.</p>") == ""
