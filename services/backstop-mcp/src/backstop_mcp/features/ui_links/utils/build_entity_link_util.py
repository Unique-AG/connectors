from collections.abc import Sequence
from urllib.parse import urlencode

from backstop_mcp.features.ui_links.entity_types import (
    LAYOUT_QUERY_ORDER,
    PAGE_SPECS,
    TAB_LABELS,
    BackstopUiPage,
    UiPageSpec,
)
from backstop_mcp.features.ui_links.inputs import BackstopLinkTarget
from backstop_mcp.features.ui_links.internal_dto import BackstopLinkTargetDto
from backstop_mcp.features.ui_links.responses import (
    BackstopLinkResponse,
    BackstopLinksResponse,
    BuildEntityLinkResult,
    UiBaseUrlNotConfiguredResponse,
)


class BuildEntityLinkUtil:
    """Build labeled CRM UI URLs from a discriminated target and an optional tab/layout."""

    def __init__(self, *, ui_base_url: str | None) -> None:
        self._ui_base_url: str | None = ui_base_url

    def run(
        self,
        *,
        target: BackstopLinkTarget,
        tabs: Sequence[str] | None = None,
        layout_name: str | None = None,
        view_entity_type: str | None = None,
    ) -> BuildEntityLinkResult:
        if self._ui_base_url is None:
            return UiBaseUrlNotConfiguredResponse()

        resolved = BackstopLinkTargetDto.from_input(target)
        spec = PAGE_SPECS[resolved.page]
        assert spec.buildable, f"page {resolved.page} is parser-only"

        links = [
            BackstopLinkResponse(label=label, url=url)
            for label, url in self._tab_links(
                spec=spec,
                entity_id=resolved.entity_id,
                activity_slug=resolved.activity_slug,
                tabs=tabs,
            )
        ]
        layout_link = self._layout_link(
            spec=spec,
            entity_id=resolved.entity_id,
            layout_name=layout_name,
            view_entity_type=view_entity_type,
        )
        if layout_link is not None:
            links = [*links, layout_link]
        return BackstopLinksResponse(
            links=links,
            unrecognized_tabs=self._unrecognized_tabs(spec=spec, tabs=tabs),
        )

    def canonical_url(self, *, target: BackstopLinkTarget) -> str | None:
        """The no-tab 'open this record' URL, or None when this deployment has no UI origin."""
        if self._ui_base_url is None:
            return None
        resolved = BackstopLinkTargetDto.from_input(target)
        spec = PAGE_SPECS[resolved.page]
        if not spec.buildable:
            return None
        return self._format_url(
            spec=spec,
            entity_id=resolved.entity_id,
            activity_slug=resolved.activity_slug,
            tab=None,
        )

    def _unrecognized_tabs(self, *, spec: UiPageSpec, tabs: Sequence[str] | None) -> list[str]:
        """Requested tabs this page has no URL for, so the caller is not left guessing.

        `summary` on a summary-by-omission page is recognized — it becomes the canonical URL.
        """
        if tabs is None:
            return []
        return [
            tab
            for tab in tabs
            if tab not in spec.tabs and not (spec.summary_by_omission and tab == "summary")
        ]

    def _tab_links(
        self,
        *,
        spec: UiPageSpec,
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
        entity_id: str,
        layout_name: str | None,
        view_entity_type: str | None,
    ) -> BackstopLinkResponse | None:
        if not spec.supports_layout or not layout_name or not view_entity_type:
            return None
        assert self._ui_base_url is not None
        values = {
            "display": "",
            "viewEntityType": view_entity_type,
            "entityId": entity_id,
            "layoutName": layout_name,
        }
        assert set(values) == set(LAYOUT_QUERY_ORDER)
        query = [(name, values[name]) for name in LAYOUT_QUERY_ORDER]
        return BackstopLinkResponse(
            label=layout_name,
            url=self._join(spec.template.format(ui_base=self._ui_base_url), query),
        )

    def _format_url(
        self,
        *,
        spec: UiPageSpec,
        entity_id: str,
        activity_slug: str | None,
        tab: str | None,
    ) -> str:
        assert self._ui_base_url is not None
        if spec.page == BackstopUiPage.ACTIVITY:
            assert activity_slug is not None, "activity links need a jsp kind slug"
            return spec.template.format(ui_base=self._ui_base_url, kind=activity_slug, id=entity_id)

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
        return self._join(spec.template.format(ui_base=self._ui_base_url), query)

    def _join(self, base: str, query: Sequence[tuple[str, str]]) -> str:
        encoded = urlencode(list(query))
        return f"{base}?{encoded}" if encoded else base
