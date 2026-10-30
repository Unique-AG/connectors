from world_check_mcp.contexts.groups.models import GroupSettings
from world_check_mcp.contexts.groups.models import ResolutionOption
from world_check_mcp.contexts.groups.models import ResolutionToolkit
from world_check_mcp.contexts.groups.models import SecondaryField
from world_check_mcp.contexts.groups.summary import group_from_summary
from world_check_mcp.upstream import CaseTemplateResponse
from world_check_mcp.upstream import GET_CASE_TEMPLATE_FOR_GROUP
from world_check_mcp.upstream import GET_GROUP_BY_ID
from world_check_mcp.upstream import GET_RESOLUTION_TOOLKITS_FOR_GROUP
from world_check_mcp.upstream import ResolutionField
from world_check_mcp.upstream import ResolutionToolkitResponse
from world_check_mcp.upstream import StatusResolutionField
from world_check_mcp.upstream import Upstream


async def get_group_settings(*, upstream: Upstream, group_id: str) -> GroupSettings:
    """The group's template and the resolution choices its matches accept."""
    group = await upstream.call(GET_GROUP_BY_ID, groupId=group_id)
    template = await upstream.call(GET_CASE_TEMPLATE_FOR_GROUP, groupId=group_id)
    toolkits = await upstream.call(GET_RESOLUTION_TOOLKITS_FOR_GROUP, groupId=group_id)
    return GroupSettings(
        group=group_from_summary(summary=group),
        screening_type=template.group_screening_type,
        mandatory_provider_types=template.mandatory_provider_types or [],
        secondary_fields=_secondary_fields(template=template),
        toolkits=[_toolkit(toolkit=toolkit) for toolkit in toolkits.root.values()],
    )


def _secondary_fields(*, template: CaseTemplateResponse) -> list[SecondaryField]:
    by_provider = template.secondary_fields_by_provider or {}
    return [
        SecondaryField(
            provider=provider,
            entity_type=entity_type,
            type_id=field.type_id,
            label=field.label,
            value_type=field.field_value_type,
            required=bool(field.field_required),
        )
        for provider, by_entity in by_provider.items()
        for entity_type, fields in by_entity.secondary_fields_by_entity.items()
        for field in fields
    ]


def _toolkit(*, toolkit: ResolutionToolkitResponse) -> ResolutionToolkit:
    fields = toolkit.resolution_fields
    return ResolutionToolkit(
        provider_type=toolkit.provider_type or "",
        statuses=_statuses(fields=fields.statuses) if fields else [],
        risks=_options(fields=fields.risks) if fields else [],
        reasons=_options(fields=fields.reasons) if fields else [],
    )


def _options(*, fields: list[ResolutionField]) -> list[ResolutionOption]:
    return [ResolutionOption(id=field.id, label=field.label) for field in fields]


def _statuses(*, fields: list[StatusResolutionField]) -> list[ResolutionOption]:
    return [
        ResolutionOption(id=field.id, label=field.label, status_type=field.type) for field in fields
    ]
