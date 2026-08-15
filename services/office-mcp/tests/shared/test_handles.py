"""The `teams:///` grammar: what round-trips, and what is not a handle of a given family.

The families are separate because the tools and the permissions behind them are, so the assertions
that matter most here are the negative ones — anything that is not this family's shape has to come
back as no handle rather than as a handle with a strange id in it. Every id below is invented.
"""

import pytest

from office_mcp.shared import handles

# A join URL shaped like the ones Graph actually stores: `%3a` and `%40` already percent-escaped, a
# `?context=` query with `%7b`/`%22` in its value, and an `&` parameter after it. Every one of those
# is a character a handle has to carry through one path segment and hand back byte-identical.
JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)


class TestTheHandleGrammar:
    def test_a_meeting_handle_survives_the_join_url_it_carries(self) -> None:
        """A join URL is full of `:`, `/`, `?`, `&` and `%` and must come back byte-identical:
        Graph matches it against what it stored, character for character."""
        uri = handles.meeting_uri_for(JOIN_WEB_URL)
        assert uri is not None

        parsed = handles.meeting_handle(uri)

        assert parsed is not None
        assert parsed.join_web_url == JOIN_WEB_URL
        assert "/" not in uri.removeprefix("teams:///meetings/"), (
            "the join URL is one path segment; an unencoded slash would make it several"
        )

    @pytest.mark.parametrize(
        "uri",
        [
            # Another family's shape, which is the negative that matters: the first segment is what
            # tells the families apart, and a parser that ignored it would answer for all of them.
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "teams:///meetings/",
            "teams:///meetings/%20",
            "teams:///meetings/a/b",
            # The handle a model re-spelled by hand: the slashes in a raw join URL make it several
            # path segments. Refusing it is the point — half of it, carried as if it were the whole,
            # is a lookup Graph answers nothing for and a "no such meeting" nobody could explain.
            f"teams:///meetings/{JOIN_WEB_URL}",
            # The schemes a polymorphic reader would advertise and this connector cannot serve.
            "mail:///messages/AAMkAGI2",
            "site:///sites/contoso/pages/1",
            # The bare URL, which is what a model reaches for when it has no handle at all.
            JOIN_WEB_URL,
            "",
        ],
    )
    def test_what_is_not_a_meeting_handle(self, uri: str) -> None:
        assert handles.meeting_handle(uri) is None

    @pytest.mark.parametrize("join_web_url", [None, "", "   "])
    def test_no_join_url_means_no_handle_rather_than_an_empty_one(
        self, join_web_url: str | None
    ) -> None:
        """The case the design has to survive: Graph gives a meeting chat no join URL, so there is
        no route to its meeting and nothing may pretend otherwise."""
        assert handles.meeting_uri_for(join_web_url) is None
