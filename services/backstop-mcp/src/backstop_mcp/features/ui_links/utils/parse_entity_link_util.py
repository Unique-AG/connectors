from urllib.parse import parse_qsl, urlparse

from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.ui_links.activity_kinds import ACTIVITY_JSP_SLUG_TO_KIND
from backstop_mcp.features.ui_links.entity_types import (
    ACTIVITY_SEARCH_BEAN_TOOLS,
    IGNORED_QUERY_PARAMS,
    LANDING_RESOURCE_TYPE_TOOLS,
    PAGE_SPECS,
    BackstopUiPage,
    UiPageSpec,
)
from backstop_mcp.features.ui_links.internal_dto import (
    ActivitySearchRelatedDto,
    BackstopLinkTargetDto,
)
from backstop_mcp.features.ui_links.responses import (
    ParsedBackstopLinkResponse,
    ParseEntityLinkResult,
    UnrecognizedBackstopUrlResponse,
)

_ACTIVITY_SEARCH_RELATED: TypeAdapter[list[ActivitySearchRelatedDto]] = TypeAdapter(
    list[ActivitySearchRelatedDto]
)


class ParseEntityLinkUtil:
    """Parse a pasted CRM UI URL into page, id, tab, and layout. Does not raise."""

    def __init__(self, *, ui_base_url: str | None) -> None:
        self._ui_base_url: str | None = ui_base_url

    def run(self, *, url: str) -> ParseEntityLinkResult:
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
            )
        if page == BackstopUiPage.LANDING:
            return self._parse_landing(spec=spec, query=query, pasted_url=url)
        if page == BackstopUiPage.ACTIVITY_SEARCH:
            return self._parse_activity_search(spec=spec, query=query, pasted_url=url)
        return self._parse_action(spec=spec, query=query, pasted_url=url)

    def _relative_backstop_path(self, path: str) -> str | None:
        backstop_prefix = "/backstop/"
        index = path.find(backstop_prefix)
        if index == -1:
            return None
        return path[index + len(backstop_prefix) :].rstrip("/")

    def _query_params(self, query: str, fragment: str) -> dict[str, str]:
        pairs = list(parse_qsl(query, keep_blank_values=True))
        if fragment:
            pairs.extend(parse_qsl(self._fragment_query(fragment), keep_blank_values=True))
        return {key: value for key, value in pairs if key not in IGNORED_QUERY_PARAMS}

    def _fragment_query(self, fragment: str) -> str:
        if fragment.startswith("/?"):
            return fragment[2:]
        if fragment.startswith("?"):
            return fragment[1:]
        return fragment

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
            suggested_tool=spec.suggested_tool,
            suggested_note=spec.suggested_note,
        )

    def _parse_activity_search(
        self,
        *,
        spec: UiPageSpec,
        query: dict[str, str],
        pasted_url: str,
    ) -> ParseEntityLinkResult:
        related = self._activity_search_related(query.get("selectedRelatedToUrl"))
        if related is None:
            return UnrecognizedBackstopUrlResponse()
        bean = related.type or related.first_system_defined_type
        lookup = ACTIVITY_SEARCH_BEAN_TOOLS.get(bean) if bean is not None else None
        return self._parsed(
            BackstopLinkTargetDto(
                page=spec.page,
                entity_id=related.id,
                entity_kind=None if lookup is None else lookup.entity_kind,
            ),
            pasted_url=pasted_url,
            suggested_tool=None if lookup is None else lookup.tool,
            suggested_note=None,
        )

    def _activity_search_related(self, raw: str | None) -> ActivitySearchRelatedDto | None:
        if raw is None or raw == "":
            return None
        try:
            rows = _ACTIVITY_SEARCH_RELATED.validate_json(raw)
        except ValidationError:
            return None
        return rows[0] if rows else None

    def _parse_landing(
        self,
        *,
        spec: UiPageSpec,
        query: dict[str, str],
        pasted_url: str,
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
            suggested_tool=lookup.tool if lookup is not None else None,
            suggested_note=lookup.note if lookup is not None else None,
        )

    def _parse_action(
        self,
        *,
        spec: UiPageSpec,
        query: dict[str, str],
        pasted_url: str,
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
            suggested_tool=spec.suggested_tool,
            suggested_note=spec.suggested_note,
        )

    def _parsed(
        self,
        dto: BackstopLinkTargetDto,
        *,
        pasted_url: str,
        suggested_tool: str | None,
        suggested_note: str | None,
    ) -> ParsedBackstopLinkResponse:
        return ParsedBackstopLinkResponse.from_dto(
            dto,
            host_mismatch=self._host_mismatch(pasted_url),
            suggested_tool=suggested_tool,
            suggested_note=suggested_note,
        )

    def _host_mismatch(self, pasted_url: str) -> bool:
        if self._ui_base_url is None:
            return False
        pasted_host = urlparse(pasted_url).hostname
        configured_host = urlparse(self._ui_base_url).hostname
        if pasted_host is None or configured_host is None:
            return False
        return pasted_host.casefold() != configured_host.casefold()
