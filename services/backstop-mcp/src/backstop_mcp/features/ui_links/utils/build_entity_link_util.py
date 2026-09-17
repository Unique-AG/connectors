from collections.abc import Sequence
from urllib.parse import urlencode

from backstop_mcp.features.ui_links.activity_kinds import TARGET_KIND_TO_JSP_SLUG
from backstop_mcp.features.ui_links.entity_types import (
    LAYOUT_QUERY_ORDER,
    PAGE_SPECS,
    TAB_LABELS,
    BackstopUiPage,
    UiPageSpec,
)
from backstop_mcp.features.ui_links.internal_dto import BackstopLinkTargetDto
from backstop_mcp.features.ui_links.responses import (
    BackstopLabeledUrlResponse,
    BackstopLinkResponse,
    BuildEntityLinkResult,
    UiBaseUrlNotConfiguredResponse,
)


class BuildEntityLinkUtil:
    """Build labeled CRM UI URLs from a discriminated target and an optional tab/layout."""

    def run(
        self,
        *,
        target: BackstopLinkTargetDto,
        ui_base_url: str | None,
        tabs: Sequence[str] | None = None,
        layout_name: str | None = None,
        view_entity_type: str | None = None,
    ) -> BuildEntityLinkResult:
        if ui_base_url is None:
            return UiBaseUrlNotConfiguredResponse()

        page, entity_id, activity_slug = self._page_id_and_slug(target)
        spec = PAGE_SPECS[page]
        assert spec.buildable, f"page {page} is parser-only"

        links = [
            BackstopLabeledUrlResponse(label=label, url=url)
            for label, url in self._tab_links(
                spec=spec,
                ui_base_url=ui_base_url,
                entity_id=entity_id,
                activity_slug=activity_slug,
                tabs=tabs,
            )
        ]
        layout_link = self._layout_link(
            spec=spec,
            ui_base_url=ui_base_url,
            entity_id=entity_id,
            layout_name=layout_name,
            view_entity_type=view_entity_type,
        )
        if layout_link is not None:
            links = [*links, layout_link]
        return BackstopLinkResponse(links=links)

    def _page_id_and_slug(
        self, target: BackstopLinkTargetDto
    ) -> tuple[BackstopUiPage, str, str | None]:
        match target.kind:
            case "organization":
                return BackstopUiPage.ORGANIZATION, target.party_id, None
            case "person":
                return BackstopUiPage.PERSON, target.party_id, None
            case "account":
                return BackstopUiPage.ACCOUNT, target.entity_id, None
            case "product":
                return BackstopUiPage.PRODUCT, target.entity_id, None
            case "opportunity":
                return BackstopUiPage.OPPORTUNITY, target.entity_id, None
            case "task":
                return BackstopUiPage.TASK, target.task_id, None
            case "email":
                return BackstopUiPage.EMAIL, target.entity_activity_details_id, None
            case "call" | "meeting" | "note" | "document":
                return (
                    BackstopUiPage.ACTIVITY,
                    target.entity_activity_details_id,
                    TARGET_KIND_TO_JSP_SLUG[target.kind],
                )

    def _tab_links(
        self,
        *,
        spec: UiPageSpec,
        ui_base_url: str,
        entity_id: str,
        activity_slug: str | None,
        tabs: Sequence[str] | None,
    ) -> list[tuple[str, str]]:
        requested = None if tabs is None else tuple(tabs)
        summary_as_omission = (
            spec.summary_by_omission and requested is not None and "summary" in requested
        )
        include_canonical = requested is None or requested == () or summary_as_omission
        include_tabs = (
            spec.tabs if requested is None else tuple(tab for tab in requested if tab in spec.tabs)
        )

        links: list[tuple[str, str]] = []
        if include_canonical:
            links.append(
                (
                    spec.canonical_label,
                    self._format_url(
                        spec=spec,
                        ui_base_url=ui_base_url,
                        entity_id=entity_id,
                        activity_slug=activity_slug,
                        tab=None,
                    ),
                )
            )
        for tab in include_tabs:
            assert tab != "summary" or not spec.summary_by_omission, (
                "product summary is omission; viewType=summary must not be emitted"
            )
            links.append(
                (
                    TAB_LABELS.get(tab, tab),
                    self._format_url(
                        spec=spec,
                        ui_base_url=ui_base_url,
                        entity_id=entity_id,
                        activity_slug=activity_slug,
                        tab=tab,
                    ),
                )
            )
        return links

    def _layout_link(
        self,
        *,
        spec: UiPageSpec,
        ui_base_url: str,
        entity_id: str,
        layout_name: str | None,
        view_entity_type: str | None,
    ) -> BackstopLabeledUrlResponse | None:
        if not spec.supports_layout or not layout_name or not view_entity_type:
            return None
        query = [
            ("display", ""),
            ("viewEntityType", view_entity_type),
            ("entityId", entity_id),
            ("layoutName", layout_name),
        ]
        assert [name for name, _value in query] == list(LAYOUT_QUERY_ORDER)
        return BackstopLabeledUrlResponse(
            label=layout_name,
            url=self._join(spec.template.format(ui_base=ui_base_url), query),
        )

    def _format_url(
        self,
        *,
        spec: UiPageSpec,
        ui_base_url: str,
        entity_id: str,
        activity_slug: str | None,
        tab: str | None,
    ) -> str:
        if spec.page == BackstopUiPage.ACTIVITY:
            assert activity_slug is not None, "activity links need a jsp kind slug"
            return spec.template.format(ui_base=ui_base_url, kind=activity_slug, id=entity_id)

        values: dict[str, str] = {}
        if spec.uses_display:
            values["display"] = ""
        if spec.id_param is not None:
            values[spec.id_param] = entity_id
        for key, value in spec.extra_query:
            values[key] = value
        if tab is not None:
            assert spec.tab_param is not None, f"{spec.page} has no tab param"
            assert not (spec.summary_by_omission and tab == "summary")
            values[spec.tab_param] = tab
        query = [(name, values[name]) for name in spec.query_param_order if name in values]
        return self._join(spec.template.format(ui_base=ui_base_url), query)

    def _join(self, base: str, query: Sequence[tuple[str, str]]) -> str:
        encoded = urlencode(list(query))
        return f"{base}?{encoded}" if encoded else base
