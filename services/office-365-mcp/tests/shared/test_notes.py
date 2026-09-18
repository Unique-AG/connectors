from datetime import UTC, datetime

from msgraph.generated.models.external_link import ExternalLink
from msgraph.generated.models.notebook import Notebook
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.onenote_section import OnenoteSection
from msgraph.generated.models.page_links import PageLinks
from msgraph.generated.models.section_links import SectionLinks

from office_365_mcp.shared import notes
from office_365_mcp.shared.handles import OnenotePageHandle, OnenoteSectionHandle

_PAGE_ID = "0-33333333-3333-4333-8333-333333333333!101-44444444-4444-4444-8444-444444444444"
_SECTION_ID = "1-11111111-1111-4111-8111-111111111111!100-22222222-2222-4222-8222-222222222222"

_CREATED_AT = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)
_MODIFIED_AT = datetime(2026, 3, 12, 14, 45, tzinfo=UTC)

_LINKS = PageLinks(
    one_note_web_url=ExternalLink(href="https://onenote.invalid/web/page"),
    one_note_client_url=ExternalLink(href="onenote:https://onenote.invalid/client/page"),
)
_SECTION = OnenoteSection(id=_SECTION_ID, display_name="Team Standups")
_NOTEBOOK = Notebook(display_name="Engineering")


def _page(
    *,
    page_id: str | None = _PAGE_ID,
    title: str | None = "Weekly sync notes",
    created_at: datetime | None = _CREATED_AT,
    modified_at: datetime | None = _MODIFIED_AT,
    links: PageLinks | None = _LINKS,
    section: OnenoteSection | None = _SECTION,
    notebook: Notebook | None = _NOTEBOOK,
) -> OnenotePage:
    return OnenotePage(
        id=page_id,
        title=title,
        created_date_time=created_at,
        last_modified_date_time=modified_at,
        links=links,
        parent_section=section,
        parent_notebook=notebook,
    )


class TestFromPage:
    def test_it_mints_the_page_and_section_handles(self) -> None:
        summary = notes.PageSummary.from_page(_page())

        assert summary is not None
        assert summary.uri == OnenotePageHandle(_PAGE_ID).uri
        assert summary.section_uri == OnenoteSectionHandle(_SECTION_ID).uri

    def test_it_maps_every_other_field(self) -> None:
        summary = notes.PageSummary.from_page(_page())

        assert summary is not None
        assert summary.title == "Weekly sync notes"
        assert summary.created_at == _CREATED_AT
        assert summary.last_modified_at == _MODIFIED_AT
        assert summary.web_url == "https://onenote.invalid/web/page"
        assert summary.client_url == "onenote:https://onenote.invalid/client/page"
        assert summary.section_name == "Team Standups"
        assert summary.notebook_name == "Engineering"

    def test_a_page_with_no_id_answers_none(self) -> None:
        assert notes.PageSummary.from_page(_page(page_id=None)) is None

    def test_a_page_with_no_links_answers_null_urls(self) -> None:
        summary = notes.PageSummary.from_page(_page(links=None))

        assert summary is not None
        assert summary.web_url is None
        assert summary.client_url is None

    def test_a_page_with_no_parent_section_answers_a_null_section(self) -> None:
        summary = notes.PageSummary.from_page(_page(section=None))

        assert summary is not None
        assert summary.section_uri is None
        assert summary.section_name is None

    def test_a_page_with_no_parent_notebook_answers_a_null_notebook_name(self) -> None:
        summary = notes.PageSummary.from_page(_page(notebook=None))

        assert summary is not None
        assert summary.notebook_name is None

    def test_a_parent_section_with_no_id_leaves_the_section_uri_null(self) -> None:
        summary = notes.PageSummary.from_page(
            _page(section=OnenoteSection(display_name="Untitled"))
        )

        assert summary is not None
        assert summary.section_uri is None
        assert summary.section_name == "Untitled"


class TestTheLinksProtocol:
    def test_web_url_of_none_is_none(self) -> None:
        assert notes.web_url_of(None) is None

    def test_client_url_of_none_is_none(self) -> None:
        assert notes.client_url_of(None) is None

    def test_it_reads_a_section_links_instance_too(self) -> None:
        links = SectionLinks(
            one_note_web_url=ExternalLink(href="https://onenote.invalid/web/section"),
            one_note_client_url=ExternalLink(href="onenote:https://onenote.invalid/client/section"),
        )

        assert notes.web_url_of(links) == "https://onenote.invalid/web/section"
        assert notes.client_url_of(links) == "onenote:https://onenote.invalid/client/section"

    def test_a_links_object_with_no_href_answers_none(self) -> None:
        links = SectionLinks(one_note_web_url=None, one_note_client_url=None)

        assert notes.web_url_of(links) is None
        assert notes.client_url_of(links) is None
