from urllib.parse import parse_qsl, urlparse

from backstop_mcp.features.ui_links.activity_kinds import ACTIVITY_JSP_SLUG_TO_KIND
from backstop_mcp.features.ui_links.entity_types import (
    IGNORED_QUERY_PARAMS,
    LANDING_RESOURCE_TYPE_TOOLS,
    PAGE_SPECS,
    BackstopUiPage,
    UiPageSpec,
)
from backstop_mcp.features.ui_links.internal_dto import BackstopLinkTargetDto
from backstop_mcp.features.ui_links.responses import (
    ParsedBackstopLinkResponse,
    ParseEntityLinkResult,
    UnrecognizedBackstopUrlResponse,
)


class ParseEntityLinkUtil:
    """Parse a pasted CRM UI URL into page, id, tab, and layout. Does not raise."""

    _BACKSTOP_PREFIX = "/backstop/"

    def run(self, *, url: str, ui_base_url: str | None = None) -> ParseEntityLinkResult:
        parsed = urlparse(url)
        rel_path = self._relative_backstop_path(parsed.path)
        if rel_path is None:
            return UnrecognizedBackstopUrlResponse()

        query = self._query_params(parsed.query, parsed.fragment)
        matched = self._match_page(rel_path)
        if matched is None:
            return UnrecognizedBackstopUrlResponse()

        page, activity_slug, activity_id = matched
        spec = PAGE_SPECS[page]
        if page == BackstopUiPage.ACTIVITY:
            return self._parse_activity(
                spec=spec,
                activity_slug=activity_slug,
                activity_id=activity_id,
                pasted_url=url,
                ui_base_url=ui_base_url,
            )
        if page == BackstopUiPage.LANDING:
            return self._parse_landing(
                spec=spec,
                query=query,
                pasted_url=url,
                ui_base_url=ui_base_url,
            )
        return self._parse_action(
            spec=spec,
            query=query,
            pasted_url=url,
            ui_base_url=ui_base_url,
        )

    def _relative_backstop_path(self, path: str) -> str | None:
        index = path.find(self._BACKSTOP_PREFIX)
        if index == -1:
            return None
        return path[index + len(self._BACKSTOP_PREFIX) :].rstrip("/")

    def _query_params(self, query: str, fragment: str) -> dict[str, str]:
        pairs = list(parse_qsl(query, keep_blank_values=True))
        if fragment:
            pairs.extend(parse_qsl(fragment, keep_blank_values=True))
        return {key: value for key, value in pairs if key not in IGNORED_QUERY_PARAMS}

    def _match_page(self, rel_path: str) -> tuple[BackstopUiPage, str | None, str | None] | None:
        activity = BackstopUiPage.ACTIVITY.value
        if rel_path == activity or rel_path.startswith(f"{activity}/"):
            parts = rel_path.split("/")
            slug = parts[1] if len(parts) > 1 and parts[1] else None
            entity_id = parts[2] if len(parts) > 2 and parts[2] else None
            return BackstopUiPage.ACTIVITY, slug, entity_id

        for page in sorted(BackstopUiPage, key=lambda item: -len(item.value)):
            if page == BackstopUiPage.ACTIVITY:
                continue
            if rel_path == page.value:
                return page, None, None
        return None

    def _parse_activity(
        self,
        *,
        spec: UiPageSpec,
        activity_slug: str | None,
        activity_id: str | None,
        pasted_url: str,
        ui_base_url: str | None,
    ) -> ParseEntityLinkResult:
        if activity_slug is None or activity_id is None:
            return UnrecognizedBackstopUrlResponse()
        entity_kind = ACTIVITY_JSP_SLUG_TO_KIND.get(activity_slug)
        if entity_kind is None:
            return UnrecognizedBackstopUrlResponse()
        return self._parsed(
            BackstopLinkTargetDto(
                page=spec.page,
                entity_id=activity_id,
                entity_kind=entity_kind,
                activity_slug=activity_slug,
            ),
            pasted_url=pasted_url,
            ui_base_url=ui_base_url,
            suggested_tool=spec.suggested_tool,
            suggested_note=spec.suggested_note,
        )

    def _parse_landing(
        self,
        *,
        spec: UiPageSpec,
        query: dict[str, str],
        pasted_url: str,
        ui_base_url: str | None,
    ) -> ParseEntityLinkResult:
        entity_id = query.get("entityId")
        if not entity_id:
            return UnrecognizedBackstopUrlResponse()
        resource_type = query.get("resourceType")
        lookup = (
            LANDING_RESOURCE_TYPE_TOOLS.get(resource_type) if resource_type is not None else None
        )
        return self._parsed(
            BackstopLinkTargetDto(
                page=spec.page,
                entity_id=entity_id,
                resource_type=resource_type,
            ),
            pasted_url=pasted_url,
            ui_base_url=ui_base_url,
            suggested_tool=lookup.tool if lookup is not None else None,
            suggested_note=lookup.note if lookup is not None else None,
        )

    def _parse_action(
        self,
        *,
        spec: UiPageSpec,
        query: dict[str, str],
        pasted_url: str,
        ui_base_url: str | None,
    ) -> ParseEntityLinkResult:
        layout_name = query.get("layoutName")
        view_entity_type = query.get("viewEntityType")
        if layout_name is not None and spec.supports_layout:
            entity_id = query.get("entityId")
        else:
            assert spec.id_param is not None, f"{spec.page} is missing an id param"
            entity_id = query.get(spec.id_param)
        if not entity_id:
            return UnrecognizedBackstopUrlResponse()

        tab: str | None = None
        if spec.tab_param is not None and not layout_name:
            tab = query.get(spec.tab_param)

        view_only: bool | None = None
        workflow_task_id: str | None = None
        if spec.page == BackstopUiPage.TASK:
            if "viewOnly" in query:
                view_only = query["viewOnly"].casefold() == "true"
            if "workflowTaskId" in query:
                workflow_task_id = query["workflowTaskId"]

        return self._parsed(
            BackstopLinkTargetDto(
                page=spec.page,
                entity_id=entity_id,
                entity_kind=spec.entity_kind,
                tab=tab,
                layout_name=layout_name if spec.supports_layout else None,
                view_entity_type=view_entity_type if spec.supports_layout and layout_name else None,
                view_only=view_only,
                workflow_task_id=workflow_task_id,
            ),
            pasted_url=pasted_url,
            ui_base_url=ui_base_url,
            suggested_tool=spec.suggested_tool,
            suggested_note=spec.suggested_note,
        )

    def _parsed(
        self,
        dto: BackstopLinkTargetDto,
        *,
        pasted_url: str,
        ui_base_url: str | None,
        suggested_tool: str | None,
        suggested_note: str | None,
    ) -> ParsedBackstopLinkResponse:
        return ParsedBackstopLinkResponse.from_dto(
            dto,
            host_mismatch=self._host_mismatch(pasted_url, ui_base_url),
            suggested_tool=suggested_tool,
            suggested_note=suggested_note,
        )

    def _host_mismatch(self, pasted_url: str, ui_base_url: str | None) -> bool:
        if ui_base_url is None:
            return False
        pasted_host = urlparse(pasted_url).hostname
        configured_host = urlparse(ui_base_url).hostname
        if pasted_host is None or configured_host is None:
            return False
        return pasted_host.casefold() != configured_host.casefold()
