from office_365_mcp.shared.body_html import html_link_targets, links_in_body


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


class TestLinksInBody:
    def test_names_every_link_for_a_question(self) -> None:
        body = '<a href="https://a.example">x</a><a href="https://b.example">y</a>'

        assert links_in_body(body) == " It links to 'https://a.example', 'https://b.example'."

    def test_says_nothing_when_the_body_has_no_link(self) -> None:
        assert links_in_body("<p>No links.</p>") == ""
