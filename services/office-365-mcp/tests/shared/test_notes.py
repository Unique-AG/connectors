import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import get_args
from urllib.parse import unquote

import httpx
import pytest
import respx
from msgraph.generated.models.external_link import ExternalLink
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.notebook import Notebook
from msgraph.generated.models.onenote_operation import OnenoteOperation
from msgraph.generated.models.onenote_operation_error import OnenoteOperationError
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.onenote_section import OnenoteSection
from msgraph.generated.models.operation_status import OperationStatus
from msgraph.generated.models.page_links import PageLinks
from msgraph.generated.models.section_group import SectionGroup
from msgraph.generated.models.section_links import SectionLinks
from msgraph.generated.users.item.onenote.sections.item import (
    onenote_section_item_request_builder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel

from office_365_mcp.graph_client import FetchedResponse, GraphNotFound
from office_365_mcp.shared import notes
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteOperationHandle,
    OnenoteOwner,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)

from .conftest import GRAPH_V1

_PAGE_ID = "0-33333333-3333-4333-8333-333333333333!101-44444444-4444-4444-8444-444444444444"
_SECTION_ID = "1-11111111-1111-4111-8111-111111111111!100-22222222-2222-4222-8222-222222222222"

_APP_ID = "WLID-000000004C12821A"

_CREATED_AT = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)
_MODIFIED_AT = datetime(2026, 3, 12, 14, 45, tzinfo=UTC)

_LINKS = PageLinks(
    one_note_web_url=ExternalLink(href="https://onenote.invalid/web/page"),
    one_note_client_url=ExternalLink(href="onenote:https://onenote.invalid/client/page"),
)
_SECTION = OnenoteSection(id=_SECTION_ID, display_name="Team Standups")
_NOTEBOOK = Notebook(display_name="Engineering")

_GROUP_ID = "5c6b7a81-2f0d-4a24-9b1e-8a9c3c470f9e"
_GROUP = OnenoteOwner("groups", _GROUP_ID)
_GROUP_REASON = "which belongs to a Microsoft 365 group"
_SITE_ID = (
    "contoso.sharepoint.invalid,0d1e2f3a-0000-4000-8000-000000000001,"
    + "4b5c6d7e-0000-4000-8000-000000000002"
)
_SITE = OnenoteOwner("sites", _SITE_ID)
_SITE_REASON = "which belongs to a SharePoint site"


def _page(
    *,
    page_id: str | None = _PAGE_ID,
    title: str | None = "Weekly sync notes",
    created_at: datetime | None = _CREATED_AT,
    modified_at: datetime | None = _MODIFIED_AT,
    links: PageLinks | None = _LINKS,
    section: OnenoteSection | None = _SECTION,
    notebook: Notebook | None = _NOTEBOOK,
    level: int | None = None,
    order: int | None = None,
    created_by_app_id: str | None = _APP_ID,
) -> OnenotePage:
    return OnenotePage(
        id=page_id,
        title=title,
        created_date_time=created_at,
        last_modified_date_time=modified_at,
        links=links,
        parent_section=section,
        parent_notebook=notebook,
        level=level,
        order=order,
        created_by_app_id=created_by_app_id,
    )


class TestFromPage:
    def test_it_mints_the_page_and_section_handles(self) -> None:
        summary = notes.PageSummary.from_page(_page())

        assert summary is not None
        assert summary.uri == OnenotePageHandle(_PAGE_ID).uri
        assert summary.section_uri == OnenoteSectionHandle(_SECTION_ID).uri

    def test_a_group_page_mints_the_group_page_and_section_handles(self) -> None:
        summary = notes.PageSummary.from_page(_page(), owner=_GROUP)

        assert summary is not None
        assert summary.uri == OnenotePageHandle(_PAGE_ID, owner=_GROUP).uri
        assert summary.section_uri == OnenoteSectionHandle(_SECTION_ID, owner=_GROUP).uri

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
        assert summary.created_by_app_id == _APP_ID

    def test_a_page_with_no_creating_app_answers_a_null_app_id(self) -> None:
        summary = notes.PageSummary.from_page(_page(created_by_app_id=None))

        assert summary is not None
        assert summary.created_by_app_id is None

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

    def test_level_and_order_are_null_by_default(self) -> None:
        summary = notes.PageSummary.from_page(_page())

        assert summary is not None
        assert summary.level is None
        assert summary.order is None

    def test_level_and_order_are_mapped_when_graph_sends_them(self) -> None:
        summary = notes.PageSummary.from_page(_page(level=1, order=3))

        assert summary is not None
        assert summary.level == 1
        assert summary.order == 3


class TestTheHandleFieldsNameTheGroupShape:
    @pytest.mark.parametrize(
        ("model", "field"),
        [
            (notes.PageSummary, "uri"),
            (notes.PageSummary, "section_uri"),
            (notes.OperationSummary, "uri"),
        ],
    )
    def test_a_handle_field_says_how_a_group_or_site_handle_starts(
        self, model: type[BaseModel], field: str
    ) -> None:
        described = model.model_fields[field].description or ""

        assert (
            "A handle from a group or site notebook starts with onenote:///groups/{group}/ "
            + "or onenote:///sites/{site}/ instead."
            in described
        )


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


class TestContainerOrderClauses:
    def test_every_order_the_tools_offer_has_a_clause(self) -> None:
        assert set(notes.CONTAINER_ORDER_CLAUSES) == set(get_args(notes.ContainerOrderBy))

    @pytest.mark.parametrize(
        ("order_by", "clause"),
        [
            ("name_asc", "displayName asc"),
            ("name_desc", "displayName desc"),
            ("created_desc", "createdDateTime desc"),
            ("created_asc", "createdDateTime asc"),
            ("last_modified_desc", "lastModifiedDateTime desc"),
            ("last_modified_asc", "lastModifiedDateTime asc"),
        ],
    )
    def test_an_order_maps_to_the_graph_property_and_direction(
        self, order_by: notes.ContainerOrderBy, clause: str
    ) -> None:
        assert notes.CONTAINER_ORDER_CLAUSES[order_by] == clause


def _created_by(*, user: str | None = None, application: str | None = None) -> IdentitySet:
    return IdentitySet(
        user=None if user is None else Identity(display_name=user),
        application=None if application is None else Identity(display_name=application),
    )


class TestCreatorNameOf:
    def test_no_identity_set_has_no_name(self) -> None:
        assert notes.creator_name_of(None) is None

    def test_it_reads_the_display_name_of_the_user(self) -> None:
        assert notes.creator_name_of(_created_by(user="Ada Lovelace")) == "Ada Lovelace"

    def test_an_identity_set_with_no_user_has_no_name(self) -> None:
        assert notes.creator_name_of(_created_by(application="Import Bot")) is None

    def test_a_user_with_no_display_name_has_no_name(self) -> None:
        assert notes.creator_name_of(IdentitySet(user=Identity(display_name=None))) is None


class TestCreatedByContains:
    def test_it_matches_a_fragment_of_the_creator_name(self) -> None:
        keeps = notes.created_by_contains("lovelace")

        assert keeps(Notebook(created_by=_created_by(user="Ada Lovelace"))) is True

    def test_it_compares_without_regard_to_case(self) -> None:
        keeps = notes.created_by_contains("ADA LOVE")

        assert keeps(OnenoteSection(created_by=_created_by(user="ada lovelace"))) is True

    def test_it_uses_casefold_so_a_sharp_s_matches_a_double_s(self) -> None:
        keeps = notes.created_by_contains("strasse")

        assert keeps(SectionGroup(created_by=_created_by(user="Hans Straße"))) is True

    def test_a_fragment_the_name_lacks_does_not_match(self) -> None:
        keeps = notes.created_by_contains("turing")

        assert keeps(Notebook(created_by=_created_by(user="Ada Lovelace"))) is False

    def test_an_item_with_no_creator_never_matches(self) -> None:
        keeps = notes.created_by_contains("a")

        assert keeps(Notebook(created_by=None)) is False

    def test_an_item_made_by_an_application_never_matches(self) -> None:
        keeps = notes.created_by_contains("bot")

        assert keeps(Notebook(created_by=_created_by(application="Import Bot"))) is False


_AUDIENCE_NOTEBOOK_ID = "1-99999999-9999-4999-8999-999999999999!100"
_AUDIENCE_SECTION_ID = "1-88888888-8888-4888-8888-888888888888!101"

_NOTEBOOK_A = "1-AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA!100"
_NOTEBOOK_B = "1-BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB!100"
_NOTEBOOK_C = "1-CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC!100"


def _notebook_payload(
    notebook_id: str,
    *,
    display_name: str | None = "Engineering",
    is_default: bool | None = False,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
) -> dict[str, object]:
    return {
        "id": notebook_id,
        "displayName": display_name,
        "isDefault": is_default,
        "isShared": is_shared,
        "userRole": user_role,
    }


def _collection(*items: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(items)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


class TestReachesOthers:
    @pytest.mark.parametrize(
        ("is_shared", "user_role", "expected"),
        [
            (False, "Owner", False),
            (True, "Owner", True),
            (False, "Contributor", True),
            (None, "Owner", True),
            (False, None, True),
            (None, None, True),
        ],
    )
    def test_the_truth_table(
        self, is_shared: bool | None, user_role: str | None, expected: bool
    ) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook", name="A notebook", is_shared=is_shared, user_role=user_role
        )

        assert audience.reaches_others is expected


class TestReason:
    def test_a_shared_notebook_names_sharing(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook", name="A notebook", is_shared=True, user_role="Owner"
        )

        assert audience.reason == "which is shared with other people"

    def test_a_non_owner_role_names_the_role(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook", name="A notebook", is_shared=False, user_role="Contributor"
        )

        assert audience.reason == "which belongs to somebody else (you are Contributor)"

    def test_no_sharing_fields_at_all_says_microsoft_did_not_report(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook", name="A notebook", is_shared=None, user_role=None
        )

        assert audience.reason == "whose sharing Microsoft did not report"

    def test_being_shared_wins_over_the_role(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook", name="A notebook", is_shared=True, user_role="Contributor"
        )

        assert audience.reason == "which is shared with other people"

    def test_an_owner_role_with_sharing_unreported_says_microsoft_did_not_report(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook", name="A notebook", is_shared=None, user_role="Owner"
        )

        assert audience.reason == "whose sharing Microsoft did not report"


class TestAGroupAudience:
    def test_an_unshared_group_notebook_the_user_owns_still_reaches_others(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook",
            name="A notebook",
            is_shared=False,
            user_role="Owner",
            owner=_GROUP,
        )

        assert audience.reaches_others is True
        assert audience.reason == _GROUP_REASON

    def test_the_group_reason_wins_over_sharing_and_the_role(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook",
            name="A notebook",
            is_shared=True,
            user_role="Contributor",
            owner=_GROUP,
        )

        assert audience.reason == _GROUP_REASON

    def test_a_notebook_is_not_in_a_group_by_default(self) -> None:
        audience = notes.audience_of(Notebook(id="a-notebook", is_shared=False))

        assert audience.owner is None


class TestASiteAudience:
    def test_an_unshared_site_notebook_the_user_owns_still_reaches_others(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook",
            name="A notebook",
            is_shared=False,
            user_role="Owner",
            owner=_SITE,
        )

        assert audience.reaches_others is True
        assert audience.reason == _SITE_REASON

    def test_the_site_reason_wins_over_sharing_and_the_role(self) -> None:
        audience = notes.NotebookAudience(
            notebook_id="a-notebook",
            name="A notebook",
            is_shared=True,
            user_role="Contributor",
            owner=_SITE,
        )

        assert audience.reason == _SITE_REASON


class TestOwnerNamed:
    def test_a_group_names_a_group_owner(self) -> None:
        assert notes.owner_named(group=_GROUP_ID, site=None) == _GROUP

    def test_a_site_names_a_site_owner(self) -> None:
        assert notes.owner_named(group=None, site=_SITE_ID) == _SITE

    def test_neither_names_no_owner(self) -> None:
        assert notes.owner_named(group=None, site=None) is None

    def test_both_break_the_invariant(self) -> None:
        with pytest.raises(AssertionError):
            _ = notes.owner_named(group=_GROUP_ID, site=_SITE_ID)


class TestNotebookAudience:
    async def test_it_sends_the_exact_select(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        _ = await notes.notebook_audience(client, _AUDIENCE_NOTEBOOK_ID)

        assert route.call_count == 1
        params = route.calls.last.request.url.params
        assert params["$select"] == "id,displayName,isShared,userRole"
        assert "$expand" not in params

    async def test_it_maps_the_role_enum_to_its_string(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(
                200,
                json=_notebook_payload(
                    _AUDIENCE_NOTEBOOK_ID, display_name="Engineering", user_role="Owner"
                ),
            )
        )

        audience = await notes.notebook_audience(client, _AUDIENCE_NOTEBOOK_ID)

        assert audience.notebook_id == _AUDIENCE_NOTEBOOK_ID
        assert audience.name == "Engineering"
        assert audience.user_role == "Owner"


class TestDefaultNotebookAudience:
    async def test_it_picks_the_notebook_marked_default_among_several(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onenote/notebooks").mock(
            return_value=_collection(
                _notebook_payload(_NOTEBOOK_A, display_name="Personal", is_default=False),
                _notebook_payload(_NOTEBOOK_B, display_name="Work", is_default=True),
                _notebook_payload(_NOTEBOOK_C, display_name="Archive", is_default=False),
            )
        )

        audience = await notes.default_notebook_audience(client)

        assert audience is not None
        assert audience.notebook_id == _NOTEBOOK_B
        assert audience.name == "Work"

    async def test_two_non_default_notebooks_answer_an_unknown_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onenote/notebooks").mock(
            return_value=_collection(
                _notebook_payload(_NOTEBOOK_A, display_name="Personal", is_default=False),
                _notebook_payload(_NOTEBOOK_B, display_name="Work", is_default=False),
            )
        )

        audience = await notes.default_notebook_audience(client)

        assert audience is not None
        assert audience.notebook_id is None
        assert audience.name is None
        assert audience.is_shared is None
        assert audience.user_role is None

    async def test_one_non_default_notebook_is_chosen_as_the_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onenote/notebooks").mock(
            return_value=_collection(
                _notebook_payload(_NOTEBOOK_A, display_name="Personal", is_default=False)
            )
        )

        audience = await notes.default_notebook_audience(client)

        assert audience is not None
        assert audience.notebook_id == _NOTEBOOK_A

    async def test_an_empty_collection_answers_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onenote/notebooks").mock(return_value=_collection())

        assert await notes.default_notebook_audience(client) is None

    async def test_a_capped_walk_with_no_default_seen_answers_an_unknown_audience(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(notes, "MAX_SCANNED_ITEMS", 1)
        _ = graph.get("/me/onenote/notebooks").mock(
            return_value=_collection(
                _notebook_payload(_NOTEBOOK_A, display_name="Personal", is_default=False),
                _notebook_payload(_NOTEBOOK_B, display_name="Work", is_default=False),
            )
        )

        audience = await notes.default_notebook_audience(client)

        assert audience is not None
        assert audience.notebook_id is None

    async def test_it_follows_a_next_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/onenote/notebooks", params={"$skiptoken": "second"}).mock(
            return_value=_collection(
                _notebook_payload(_NOTEBOOK_C, display_name="Archive", is_default=True)
            )
        )
        graph.get("/me/onenote/notebooks").mock(
            return_value=_collection(
                _notebook_payload(_NOTEBOOK_A, display_name="Personal", is_default=False),
                next_link=f"{GRAPH_V1}/me/onenote/notebooks?$skiptoken=second",
            )
        )

        audience = await notes.default_notebook_audience(client)

        assert audience is not None
        assert audience.notebook_id == _NOTEBOOK_C


_AUDIENCE_SECTION_GROUP_ID = "1-77777777-7777-4777-8777-777777777777!101"


class TestSectionAudience:
    async def test_it_reads_the_parent_notebooks_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/sections/{_AUDIENCE_SECTION_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _AUDIENCE_SECTION_ID,
                    "parentNotebook": {"id": _AUDIENCE_NOTEBOOK_ID},
                },
            )
        )
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        audience = await notes.section_audience(client, _AUDIENCE_SECTION_ID)

        assert audience.notebook_id == _AUDIENCE_NOTEBOOK_ID

    async def test_a_section_with_no_parent_notebook_answers_an_unknown_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/sections/{_AUDIENCE_SECTION_ID}").mock(
            return_value=httpx.Response(200, json={"id": _AUDIENCE_SECTION_ID})
        )

        audience = await notes.section_audience(client, _AUDIENCE_SECTION_ID)

        assert audience == notes.UNKNOWN_AUDIENCE


class TestSectionContainer:
    async def test_it_reads_the_section_name_and_the_parent_notebooks_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/sections/{_AUDIENCE_SECTION_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _AUDIENCE_SECTION_ID,
                    "displayName": "Team Standups",
                    "parentNotebook": {"id": _AUDIENCE_NOTEBOOK_ID},
                },
            )
        )
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        container = await notes.section_container(client, _AUDIENCE_SECTION_ID)

        assert container.name == "Team Standups"
        assert container.notebook.notebook_id == _AUDIENCE_NOTEBOOK_ID

    async def test_a_section_with_no_parent_notebook_answers_an_unknown_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/sections/{_AUDIENCE_SECTION_ID}").mock(
            return_value=httpx.Response(
                200, json={"id": _AUDIENCE_SECTION_ID, "displayName": "Team Standups"}
            )
        )

        container = await notes.section_container(client, _AUDIENCE_SECTION_ID)

        assert container.name == "Team Standups"
        assert container.notebook == notes.UNKNOWN_AUDIENCE


class TestSectionGroupContainer:
    async def test_it_reads_the_section_group_name_and_the_parent_notebooks_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/sectionGroups/{_AUDIENCE_SECTION_GROUP_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _AUDIENCE_SECTION_GROUP_ID,
                    "displayName": "Projects",
                    "parentNotebook": {"id": _AUDIENCE_NOTEBOOK_ID},
                },
            )
        )
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        container = await notes.section_group_container(client, _AUDIENCE_SECTION_GROUP_ID)

        assert container.name == "Projects"
        assert container.notebook.notebook_id == _AUDIENCE_NOTEBOOK_ID

    async def test_a_section_group_with_no_parent_notebook_answers_an_unknown_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/sectionGroups/{_AUDIENCE_SECTION_GROUP_ID}").mock(
            return_value=httpx.Response(
                200, json={"id": _AUDIENCE_SECTION_GROUP_ID, "displayName": "Projects"}
            )
        )

        container = await notes.section_group_container(client, _AUDIENCE_SECTION_GROUP_ID)

        assert container.name == "Projects"
        assert container.notebook == notes.UNKNOWN_AUDIENCE


class TestContainerAudience:
    async def test_a_notebook_handle_uses_the_notebooks_own_name_and_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(
                200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID, display_name="Engineering")
            )
        )

        container = await notes.container_audience(
            client, OnenoteNotebookHandle(_AUDIENCE_NOTEBOOK_ID)
        )

        assert container.name == "Engineering"
        assert container.notebook.notebook_id == _AUDIENCE_NOTEBOOK_ID
        assert container.notebook.name == "Engineering"

    async def test_a_notebook_handle_makes_exactly_one_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        _ = await notes.container_audience(client, OnenoteNotebookHandle(_AUDIENCE_NOTEBOOK_ID))

        assert len(graph.calls) == 1

    async def test_a_section_group_handle_reads_the_groups_name_and_the_parent_notebooks_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/sectionGroups/{_AUDIENCE_SECTION_GROUP_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _AUDIENCE_SECTION_GROUP_ID,
                    "displayName": "Projects",
                    "parentNotebook": {"id": _AUDIENCE_NOTEBOOK_ID},
                },
            )
        )
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        container = await notes.container_audience(
            client, OnenoteSectionGroupHandle(_AUDIENCE_SECTION_GROUP_ID)
        )

        assert container.name == "Projects"
        assert container.notebook.notebook_id == _AUDIENCE_NOTEBOOK_ID

    async def test_a_section_group_handle_with_no_parent_notebook_answers_an_unknown_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/sectionGroups/{_AUDIENCE_SECTION_GROUP_ID}").mock(
            return_value=httpx.Response(
                200, json={"id": _AUDIENCE_SECTION_GROUP_ID, "displayName": "Projects"}
            )
        )

        container = await notes.container_audience(
            client, OnenoteSectionGroupHandle(_AUDIENCE_SECTION_GROUP_ID)
        )

        assert container.name == "Projects"
        assert container.notebook == notes.UNKNOWN_AUDIENCE


class TestPageForAQuestion:
    async def test_it_reads_the_page_and_the_parent_notebooks_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/pages/{_PAGE_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _PAGE_ID,
                    "title": "Weekly sync notes",
                    "parentNotebook": {"id": _AUDIENCE_NOTEBOOK_ID},
                    "parentSection": {"id": _AUDIENCE_SECTION_ID, "displayName": "Team Standups"},
                },
            )
        )
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        result = await notes.page_for_a_question(client, _PAGE_ID)

        assert result.page.title == "Weekly sync notes"
        assert result.audience.notebook_id == _AUDIENCE_NOTEBOOK_ID

    async def test_a_page_with_no_parent_notebook_answers_an_unknown_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/pages/{_PAGE_ID}").mock(
            return_value=httpx.Response(200, json={"id": _PAGE_ID, "title": "Weekly sync notes"})
        )

        result = await notes.page_for_a_question(client, _PAGE_ID)

        assert result.audience == notes.UNKNOWN_AUDIENCE

    async def test_a_404_propagates(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/pages/{_PAGE_ID}").mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            await notes.page_for_a_question(client, _PAGE_ID)


class TestPageSummaryReRead:
    async def test_it_maps_the_re_read_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/pages/{_PAGE_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _PAGE_ID,
                    "title": "Weekly sync notes",
                    "parentSection": {"id": _AUDIENCE_SECTION_ID, "displayName": "Team Standups"},
                    "parentNotebook": {"displayName": "Engineering"},
                },
            )
        )

        summary = await notes.page_summary(client, _PAGE_ID)

        assert summary.uri == OnenotePageHandle(_PAGE_ID).uri
        assert summary.title == "Weekly sync notes"
        assert summary.section_name == "Team Standups"
        assert summary.notebook_name == "Engineering"

    async def test_a_404_propagates(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/pages/{_PAGE_ID}").mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            await notes.page_summary(client, _PAGE_ID)


type _Read = Callable[[GraphServiceClient, OnenoteOwner | None], Awaitable[object]]

_ROUTED_READS: Mapping[str, _Read] = {
    "page_summary": lambda client, owner: notes.page_summary(client, _PAGE_ID, owner=owner),
    "notebook_audience": lambda client, owner: notes.notebook_audience(
        client, _AUDIENCE_NOTEBOOK_ID, owner=owner
    ),
    "section_container": lambda client, owner: notes.section_container(
        client, _AUDIENCE_SECTION_ID, owner=owner
    ),
    "section_group_container": lambda client, owner: notes.section_group_container(
        client, _AUDIENCE_SECTION_GROUP_ID, owner=owner
    ),
    "section_audience": lambda client, owner: notes.section_audience(
        client, _AUDIENCE_SECTION_ID, owner=owner
    ),
    "container_audience_of_a_notebook": lambda client, owner: notes.container_audience(
        client, OnenoteNotebookHandle(_AUDIENCE_NOTEBOOK_ID, owner=owner)
    ),
    "container_audience_of_a_section_group": lambda client, owner: notes.container_audience(
        client, OnenoteSectionGroupHandle(_AUDIENCE_SECTION_GROUP_ID, owner=owner)
    ),
    "page_for_a_question": lambda client, owner: notes.page_for_a_question(
        client, _PAGE_ID, owner=owner
    ),
}

_PARENTED = {"parentNotebook": {"id": _AUDIENCE_NOTEBOOK_ID}}


def _reads_under(graph: respx.MockRouter, root: str) -> list[respx.Route]:
    return [
        graph.get(f"{root}/onenote/pages/{_PAGE_ID}").mock(
            return_value=httpx.Response(200, json={"id": _PAGE_ID, **_PARENTED})
        ),
        graph.get(f"{root}/onenote/sections/{_AUDIENCE_SECTION_ID}").mock(
            return_value=httpx.Response(200, json={"id": _AUDIENCE_SECTION_ID, **_PARENTED})
        ),
        graph.get(f"{root}/onenote/sectionGroups/{_AUDIENCE_SECTION_GROUP_ID}").mock(
            return_value=httpx.Response(200, json={"id": _AUDIENCE_SECTION_GROUP_ID, **_PARENTED})
        ),
        graph.get(f"{root}/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        ),
    ]


def _queries(routes: list[respx.Route]) -> list[tuple[int, bytes | None]]:
    return [
        (route.call_count, route.calls.last.request.url.query if route.called else None)
        for route in routes
    ]


class TestGroupRouting:
    @pytest.mark.parametrize("name", list(_ROUTED_READS))
    async def test_a_group_read_asks_the_group_what_the_same_read_asks_me(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        me = _reads_under(graph, "/me")
        group = _reads_under(graph, f"/groups/{_GROUP_ID}")

        _ = await _ROUTED_READS[name](client, None)
        _ = await _ROUTED_READS[name](client, _GROUP)

        assert any(route.called for route in group)
        assert _queries(group) == _queries(me)

    async def test_a_group_page_re_read_mints_group_handles(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/groups/{_GROUP_ID}/onenote/pages/{_PAGE_ID}").mock(
            return_value=httpx.Response(
                200,
                json={"id": _PAGE_ID, "parentSection": {"id": _AUDIENCE_SECTION_ID}},
            )
        )

        summary = await notes.page_summary(client, _PAGE_ID, owner=_GROUP)

        assert summary.uri == OnenotePageHandle(_PAGE_ID, owner=_GROUP).uri
        assert summary.section_uri == OnenoteSectionHandle(_AUDIENCE_SECTION_ID, owner=_GROUP).uri

    async def test_a_group_notebook_reaches_others_and_gives_the_group_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/groups/{_GROUP_ID}/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        audience = await notes.notebook_audience(client, _AUDIENCE_NOTEBOOK_ID, owner=_GROUP)

        assert audience.owner == _GROUP
        assert audience.reaches_others is True
        assert audience.reason == _GROUP_REASON

    async def test_the_same_notebook_under_me_is_not_a_group_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        audience = await notes.notebook_audience(client, _AUDIENCE_NOTEBOOK_ID)

        assert audience.owner is None
        assert audience.reaches_others is False

    async def test_a_group_section_with_no_parent_notebook_still_gives_the_group_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/groups/{_GROUP_ID}/onenote/sections/{_AUDIENCE_SECTION_ID}").mock(
            return_value=httpx.Response(200, json={"id": _AUDIENCE_SECTION_ID})
        )

        audience = await notes.section_audience(client, _AUDIENCE_SECTION_ID, owner=_GROUP)

        assert audience.notebook_id is None
        assert audience.reaches_others is True
        assert audience.reason == _GROUP_REASON

    async def test_a_group_section_group_handle_reads_under_its_group(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        section_group = graph.get(
            f"/groups/{_GROUP_ID}/onenote/sectionGroups/{_AUDIENCE_SECTION_GROUP_ID}"
        ).mock(
            return_value=httpx.Response(
                200, json={"id": _AUDIENCE_SECTION_GROUP_ID, "displayName": "Projects"}
            )
        )

        container = await notes.container_audience(
            client, OnenoteSectionGroupHandle(_AUDIENCE_SECTION_GROUP_ID, owner=_GROUP)
        )

        assert section_group.call_count == 1
        assert container.name == "Projects"
        assert container.notebook.owner == _GROUP


class TestSiteRouting:
    @pytest.mark.parametrize("name", list(_ROUTED_READS))
    async def test_a_site_read_asks_the_site_what_the_same_read_asks_me(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        me = _reads_under(graph, "/me")
        site = _reads_under(graph, f"/sites/{_SITE_ID}")

        _ = await _ROUTED_READS[name](client, None)
        _ = await _ROUTED_READS[name](client, _SITE)

        assert any(route.called for route in site)
        assert _queries(site) == _queries(me)

    async def test_a_site_notebook_reaches_others_and_gives_the_site_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/sites/{_SITE_ID}/onenote/notebooks/{_AUDIENCE_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook_payload(_AUDIENCE_NOTEBOOK_ID))
        )

        audience = await notes.notebook_audience(client, _AUDIENCE_NOTEBOOK_ID, owner=_SITE)

        assert audience.owner == _SITE
        assert audience.reaches_others is True
        assert audience.reason == _SITE_REASON

    def test_the_site_root_addresses_the_site_onenote(self, client: GraphServiceClient) -> None:
        builder = notes.onenote_root(client, _SITE).pages.by_onenote_page_id(_PAGE_ID)

        url = builder.to_get_request_information().url

        assert unquote(url).endswith(f"/sites/{_SITE_ID}/onenote/pages/{_PAGE_ID}")


_SectionItemBuilder = onenote_section_item_request_builder.OnenoteSectionItemRequestBuilder
_SectionQuery = _SectionItemBuilder.OnenoteSectionItemRequestBuilderGetQueryParameters


class TestGetWithQuery:
    async def test_a_group_builder_sends_the_typed_query_of_the_user_builder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(f"/groups/{_GROUP_ID}/onenote/sections/{_AUDIENCE_SECTION_ID}").mock(
            return_value=httpx.Response(
                200, json={"id": _AUDIENCE_SECTION_ID, "displayName": "Team Standups"}
            )
        )
        builder = notes.onenote_root(client, _GROUP).sections.by_onenote_section_id(
            _AUDIENCE_SECTION_ID
        )

        found = await notes.get_with_query(
            client,
            builder,
            _SectionQuery(select=["id", "displayName"], expand=["parentNotebook"]),
            OnenoteSection,
        )

        assert found is not None
        assert found.display_name == "Team Standups"
        params = route.calls.last.request.url.params
        assert params["$select"] == "id,displayName"
        assert params["$expand"] == "parentNotebook"

    async def test_no_group_reads_under_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(f"/me/onenote/sections/{_AUDIENCE_SECTION_ID}").mock(
            return_value=httpx.Response(200, json={"id": _AUDIENCE_SECTION_ID})
        )

        _ = await notes.get_with_query(
            client,
            notes.onenote_root(client, None).sections.by_onenote_section_id(_AUDIENCE_SECTION_ID),
            _SectionQuery(select=["id"]),
            OnenoteSection,
        )

        assert route.call_count == 1


_RESULT_PAGE_ID = "0-55555555-5555-4555-8555-555555555555!101-66666666-6666-4666-8666-666666666666"
_RESULT_SECTION_ID = (
    "1-77777777-7777-4777-8777-777777777777!100-88888888-8888-4888-8888-888888888888"
)
_RESULT_NOTEBOOK_ID = "1-99999999-9999-4999-8999-999999999999!100"


class TestResourceHandleOf:
    def test_a_page_location_mints_a_page_handle(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/users('u')/onenote/pages/{_RESULT_PAGE_ID}", None
        )

        assert result == (OnenotePageHandle(_RESULT_PAGE_ID).uri, "page")

    def test_a_section_location_mints_a_section_handle(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/users('u')/onenote/sections/{_RESULT_SECTION_ID}",
            None,
        )

        assert result == (OnenoteSectionHandle(_RESULT_SECTION_ID).uri, "section")

    def test_a_notebook_location_mints_a_notebook_handle(self) -> None:
        result = notes.resource_handle_of(
            "https://graph.microsoft.com/v1.0/users('u')/onenote/notebooks/"
            + f"{_RESULT_NOTEBOOK_ID}",
            None,
        )

        assert result == (OnenoteNotebookHandle(_RESULT_NOTEBOOK_ID).uri, "notebook")

    def test_resource_id_is_preferred_over_the_id_in_the_location(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/users('u')/onenote/pages/{_RESULT_PAGE_ID}",
            _RESULT_PAGE_ID,
        )

        assert result == (OnenotePageHandle(_RESULT_PAGE_ID).uri, "page")

    def test_a_location_with_a_trailing_query_string_still_mints_a_handle(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/users('u')/onenote/pages/{_RESULT_PAGE_ID}"
            + "?$select=id",
            None,
        )

        assert result == (OnenotePageHandle(_RESULT_PAGE_ID).uri, "page")

    def test_a_location_with_a_trailing_fragment_still_mints_a_handle(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/users('u')/onenote/pages/{_RESULT_PAGE_ID}#frag",
            None,
        )

        assert result == (OnenotePageHandle(_RESULT_PAGE_ID).uri, "page")

    def test_a_section_group_location_answers_none(self) -> None:
        result = notes.resource_handle_of(
            "https://graph.microsoft.com/v1.0/users('u')/onenote/sectionGroups/sg-1", None
        )

        assert result is None

    def test_a_section_group_location_with_a_query_string_still_answers_none(self) -> None:
        result = notes.resource_handle_of(
            "https://graph.microsoft.com/v1.0/users('u')/onenote/sectionGroups/sg-1?$select=id",
            None,
        )

        assert result is None

    def test_no_location_answers_none(self) -> None:
        assert notes.resource_handle_of(None, "some-id") is None

    def test_an_unrecognised_location_answers_none(self) -> None:
        assert notes.resource_handle_of("https://example.invalid/nothing/here", None) is None

    def test_a_group_page_location_mints_a_group_page_handle(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/groups/{_GROUP_ID}/onenote/pages/{_RESULT_PAGE_ID}",
            None,
        )

        assert result == (OnenotePageHandle(_RESULT_PAGE_ID, owner=_GROUP).uri, "page")

    def test_a_group_section_location_in_key_syntax_mints_a_group_section_handle(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/groups('{_GROUP_ID}')/onenote/sections/"
            + _RESULT_SECTION_ID,
            None,
        )

        assert result == (
            OnenoteSectionHandle(_RESULT_SECTION_ID, owner=_GROUP).uri,
            "section",
        )

    def test_a_group_notebook_location_mints_a_group_notebook_handle(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/groups/{_GROUP_ID}/onenote/notebooks/"
            + f"{_RESULT_NOTEBOOK_ID}?$select=id",
            _RESULT_NOTEBOOK_ID,
        )

        assert result == (
            OnenoteNotebookHandle(_RESULT_NOTEBOOK_ID, owner=_GROUP).uri,
            "notebook",
        )

    def test_a_site_page_location_mints_a_site_page_handle(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/sites/{_SITE_ID}/onenote/pages/{_RESULT_PAGE_ID}",
            None,
        )

        assert result == (OnenotePageHandle(_RESULT_PAGE_ID, owner=_SITE).uri, "page")

    def test_a_user_location_mints_a_handle_with_no_group(self) -> None:
        result = notes.resource_handle_of(
            f"https://graph.microsoft.com/v1.0/users('u')/onenote/pages/{_RESULT_PAGE_ID}", None
        )

        assert result is not None
        assert result[0] == f"onenote:///pages/{_RESULT_PAGE_ID.replace('!', '%21')}"


class TestOwnerOfGraphUrl:
    @pytest.mark.parametrize(
        "url",
        [
            f"https://graph.microsoft.com/v1.0/groups/{_GROUP_ID}/onenote/resources/res-1/$value",
            f"https://graph.microsoft.com/v1.0/groups('{_GROUP_ID}')/onenote/resources/res-1/content",
            f"https://graph.microsoft.com/v1.0/groups/{_GROUP_ID}/onenote/pages/p-1?$select=id",
            f"https://graph.microsoft.com/v1.0/groups/{_GROUP_ID}/onenote/operations/op-1#frag",
        ],
    )
    def test_it_reads_the_group_before_onenote(self, url: str) -> None:
        assert notes.owner_of_graph_url(url) == _GROUP

    def test_it_decodes_a_percent_encoded_group(self) -> None:
        url = "https://graph.microsoft.com/v1.0/groups/a%3Ab/onenote/resources/res-1/$value"

        assert notes.owner_of_graph_url(url) == OnenoteOwner("groups", "a:b")

    @pytest.mark.parametrize(
        "url",
        [
            f"https://graph.microsoft.com/v1.0/sites/{_SITE_ID}/onenote/resources/res-1/$value",
            f"https://graph.microsoft.com/v1.0/sites('{_SITE_ID}')/onenote/resources/res-1/content",
            f"https://graph.microsoft.com/v1.0/sites/{_SITE_ID}/onenote/pages/p-1?$select=id",
            f"https://graph.microsoft.com/v1.0/sites/{_SITE_ID}/onenote/operations/op-1#frag",
        ],
    )
    def test_it_reads_the_site_before_onenote(self, url: str) -> None:
        assert notes.owner_of_graph_url(url) == _SITE

    def test_a_site_resource_address_answers_a_site_owner(self) -> None:
        url = "https://graph.microsoft.com/v1.0/sites/s-1/onenote/resources/res-1/$value"

        assert notes.owner_of_graph_url(url) == OnenoteOwner("sites", "s-1")

    def test_it_decodes_a_percent_encoded_site(self) -> None:
        url = "https://graph.microsoft.com/v1.0/sites/a%2Cb%2Cc/onenote/resources/res-1/$value"

        assert notes.owner_of_graph_url(url) == OnenoteOwner("sites", "a,b,c")

    @pytest.mark.parametrize(
        "url",
        [
            "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1/$value",
            "https://graph.microsoft.com/v1.0/users('u')/onenote/resources/res-1/$value",
            f"https://graph.microsoft.com/v1.0/groups/{_GROUP_ID}/drive/items/item-1",
            "https://graph.microsoft.com/v1.0/sites/s-1/drive/items/item-1",
            "https://graph.microsoft.com/v1.0/sites/%20/onenote/pages/p-1",
            "https://graph.microsoft.com/v1.0/sites//onenote/pages/p-1",
            "https://graph.microsoft.com/v1.0/teams/t-1/onenote/pages/p-1",
            f"https://graph.microsoft.com/v1.0/groups/{_GROUP_ID}/team/onenote/pages/p-1",
            "https://graph.microsoft.com/v1.0/groups/%20/onenote/pages/p-1",
            "https://graph.microsoft.com/v1.0/groups//onenote/pages/p-1",
            "not a url at all",
            "",
        ],
    )
    def test_it_answers_none_without_a_group_or_a_site_before_onenote(self, url: str) -> None:
        assert notes.owner_of_graph_url(url) is None


class TestResourceIdInUrl:
    def test_a_dollar_value_suffix_is_stripped(self) -> None:
        found = notes.resource_id_in(
            "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1%21A/$value"
        )

        assert found == "res-1!A"

    def test_a_content_suffix_is_stripped(self) -> None:
        found = notes.resource_id_in(
            "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1%21A/content"
        )

        assert found == "res-1!A"

    def test_a_bare_resource_url_is_accepted(self) -> None:
        found = notes.resource_id_in(
            "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1%21A"
        )

        assert found == "res-1!A"

    def test_a_non_resource_url_answers_none(self) -> None:
        assert notes.resource_id_in("https://graph.microsoft.com/v1.0/me/onenote/pages/p-1") is None
        assert notes.resource_id_in("not a url at all") is None

    def test_a_content_suffix_with_a_query_string_is_accepted(self) -> None:
        found = notes.resource_id_in(
            "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1%21A/content"
            + "?publicAuth=true&mimeType=image/png"
        )

        assert found == "res-1!A"

    def test_a_dollar_value_suffix_with_a_query_string_is_accepted(self) -> None:
        found = notes.resource_id_in(
            "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1%21A/$value"
            + "?mimeType=image/png"
        )

        assert found == "res-1!A"

    def test_a_bare_resource_url_with_a_fragment_is_accepted(self) -> None:
        found = notes.resource_id_in(
            "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1%21A#frag"
        )

        assert found == "res-1!A"

    def test_an_unrelated_suffix_after_the_id_is_still_refused(self) -> None:
        found = notes.resource_id_in(
            "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1/somethingelse"
        )

        assert found is None


class TestOperationIdInUrl:
    def test_a_bare_operation_location_is_accepted(self) -> None:
        found = notes.operation_id_in(
            "https://graph.microsoft.com/v1.0/users('u')/onenote/operations/1-OP%21A"
        )

        assert found == "1-OP!A"

    def test_a_query_string_is_tolerated(self) -> None:
        found = notes.operation_id_in(
            "https://graph.microsoft.com/v1.0/users('u')/onenote/operations/1-OP%21A?$select=id"
        )

        assert found == "1-OP!A"

    def test_a_fragment_is_tolerated(self) -> None:
        found = notes.operation_id_in(
            "https://graph.microsoft.com/v1.0/users('u')/onenote/operations/1-OP%21A#frag"
        )

        assert found == "1-OP!A"

    def test_none_answers_none(self) -> None:
        assert notes.operation_id_in(None) is None

    def test_an_unrelated_url_answers_none(self) -> None:
        assert notes.operation_id_in("https://example.invalid/nothing/here") is None


class TestOperationSummaryFromOperation:
    def test_a_completed_copy_carries_the_result_page_handle(self) -> None:
        op = OnenoteOperation(
            id="op-1",
            status=OperationStatus.Completed,
            percent_complete="100",
            resource_location=(
                "https://graph.microsoft.com/v1.0/users('u')/onenote/pages/" + _RESULT_PAGE_ID
            ),
            resource_id=_RESULT_PAGE_ID,
        )

        summary = notes.OperationSummary.from_operation(op)

        assert summary.uri == OnenoteOperationHandle("op-1").uri
        assert summary.status == "Completed"
        assert summary.percent_complete == "100"
        assert summary.result_uri == OnenotePageHandle(_RESULT_PAGE_ID).uri
        assert summary.result_kind == "page"
        assert summary.error_code is None
        assert summary.error_message is None

    def test_a_failed_copy_carries_the_error(self) -> None:
        op = OnenoteOperation(
            id="op-2",
            status=OperationStatus.Failed,
            error=OnenoteOperationError(code="20166", message="Something went wrong"),
        )

        summary = notes.OperationSummary.from_operation(op)

        assert summary.status == "Failed"
        assert summary.error_code == "20166"
        assert summary.error_message == "Something went wrong"
        assert summary.result_uri is None
        assert summary.result_kind is None

    def test_an_id_less_operation_raises(self) -> None:
        op = OnenoteOperation(id=None, status=OperationStatus.Running)

        with pytest.raises(AssertionError):
            notes.OperationSummary.from_operation(op)

    def test_a_group_operation_mints_a_group_operation_handle(self) -> None:
        op = OnenoteOperation(id="op-3", status=OperationStatus.Running)

        summary = notes.OperationSummary.from_operation(op, owner=_GROUP)

        assert summary.uri == OnenoteOperationHandle("op-3", owner=_GROUP).uri

    def test_the_result_handle_takes_its_group_from_the_resource_location(self) -> None:
        op = OnenoteOperation(
            id="op-4",
            status=OperationStatus.Completed,
            resource_location=(
                f"https://graph.microsoft.com/v1.0/groups/{_GROUP_ID}/onenote/pages/"
                + _RESULT_PAGE_ID
            ),
        )

        summary = notes.OperationSummary.from_operation(op)

        assert summary.uri == OnenoteOperationHandle("op-4").uri
        assert summary.result_uri == OnenotePageHandle(_RESULT_PAGE_ID, owner=_GROUP).uri


class TestOperationSummaryAccepted:
    def test_it_mints_the_handle_with_every_other_field_null(self) -> None:
        summary = notes.OperationSummary.accepted("op-9")

        assert summary.uri == OnenoteOperationHandle("op-9").uri
        assert summary.status is None
        assert summary.percent_complete is None
        assert summary.created_at is None
        assert summary.last_action_at is None
        assert summary.result_uri is None
        assert summary.result_kind is None
        assert summary.error_code is None
        assert summary.error_message is None

    def test_a_group_copy_mints_a_group_operation_handle(self) -> None:
        summary = notes.OperationSummary.accepted("op-9", owner=_GROUP)

        assert summary.uri == OnenoteOperationHandle("op-9", owner=_GROUP).uri


_ACCEPTED_OPERATION_LOCATION = (
    "https://graph.microsoft.com/v1.0/users('u')/onenote/operations/op-header"
)


class TestAcceptedOperation:
    def test_a_header_only_response_mints_a_summary_from_the_operation_location(self) -> None:
        fetched = FetchedResponse(
            status_code=202,
            headers={"operation-location": _ACCEPTED_OPERATION_LOCATION},
            content=b"",
        )

        summary = notes.accepted_operation(fetched)

        assert summary is not None
        assert summary.uri == OnenoteOperationHandle("op-header").uri
        assert summary.status is None

    def test_a_body_only_response_is_parsed_into_a_full_summary(self) -> None:
        body = json.dumps({"id": "op-body", "status": "Running"}).encode()
        fetched = FetchedResponse(
            status_code=202,
            headers={"content-type": "application/json;odata.metadata=minimal"},
            content=body,
        )

        summary = notes.accepted_operation(fetched)

        assert summary is not None
        assert summary.uri == OnenoteOperationHandle("op-body").uri
        assert summary.status == "Running"

    def test_a_body_wins_over_a_header(self) -> None:
        body = json.dumps({"id": "op-body-wins", "status": "Completed"}).encode()
        fetched = FetchedResponse(
            status_code=202,
            headers={
                "operation-location": _ACCEPTED_OPERATION_LOCATION,
                "content-type": "application/json",
            },
            content=body,
        )

        summary = notes.accepted_operation(fetched)

        assert summary is not None
        assert summary.uri == OnenoteOperationHandle("op-body-wins").uri
        assert summary.status == "Completed"

    def test_a_body_that_is_not_json_is_left_alone_and_the_header_answers(self) -> None:
        fetched = FetchedResponse(
            status_code=202,
            headers={
                "operation-location": _ACCEPTED_OPERATION_LOCATION,
                "content-type": "text/plain",
            },
            content=b"Accepted",
        )

        summary = notes.accepted_operation(fetched)

        assert summary is not None
        assert summary.uri == OnenoteOperationHandle("op-header").uri
        assert summary.status is None

    def test_neither_a_body_nor_a_header_answers_none(self) -> None:
        fetched = FetchedResponse(status_code=202, headers={}, content=b"")

        assert notes.accepted_operation(fetched) is None

    def test_a_group_copy_header_mints_a_group_operation_handle(self) -> None:
        fetched = FetchedResponse(
            status_code=202,
            headers={"operation-location": _ACCEPTED_OPERATION_LOCATION},
            content=b"",
        )

        summary = notes.accepted_operation(fetched, owner=_GROUP)

        assert summary is not None
        assert summary.uri == OnenoteOperationHandle("op-header", owner=_GROUP).uri

    def test_a_group_copy_body_mints_a_group_operation_handle(self) -> None:
        body = json.dumps({"id": "op-body", "status": "Running"}).encode()
        fetched = FetchedResponse(
            status_code=202, headers={"content-type": "application/json"}, content=body
        )

        summary = notes.accepted_operation(fetched, owner=_GROUP)

        assert summary is not None
        assert summary.uri == OnenoteOperationHandle("op-body", owner=_GROUP).uri


class TestWriteStateFor:
    def test_it_is_deterministic(self) -> None:
        assert notes.write_state_for("create", "section-1", "Title") == notes.write_state_for(
            "create", "section-1", "Title"
        )

    def test_the_order_of_parts_matters(self) -> None:
        assert notes.write_state_for("a", "b") != notes.write_state_for("b", "a")

    def test_a_changed_part_changes_the_digest(self) -> None:
        assert notes.write_state_for("create", "section-1", "Title") != notes.write_state_for(
            "create", "section-1", "Different title"
        )

    def test_parts_shifted_across_the_separator_do_not_collide(self) -> None:
        assert notes.write_state_for("ab", "c") != notes.write_state_for("a", "bc")
