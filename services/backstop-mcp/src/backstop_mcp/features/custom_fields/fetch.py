from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.lov import (
    LovEntryIndex,
    allowed_values_for,
    fetch_lov_entry_index,
)
from backstop_mcp.features.custom_fields.overrides import (
    FieldOverride,
    OverrideIndex,
    index_overrides,
)
from backstop_mcp.features.custom_fields.types import (
    LOV_SET_RELATIONSHIP,
    CustomFieldDefinition,
    CustomFieldDefinitionAttributes,
)

_DEFINITIONS_PATH = "/custom-field-definitions"

type DefinitionResource = BackstopApiResource[CustomFieldDefinitionAttributes]


def definition_from_resource(
    resource: DefinitionResource,
    overrides: OverrideIndex,
    *,
    lov_index: LovEntryIndex,
    included: list[dict[str, object]],
) -> CustomFieldDefinition | None:
    """Merge one CRM definition with its human override and allowed values.

    Returns None for a definition with no usable name or entity type — neither is recoverable,
    and an unnameable field can't be resolved by name anyway.
    """
    attrs = resource.attributes
    # `name` / `entity_type` are already stripped by `CustomFieldDefinitionAttributes`.
    crm_name = attrs.name
    if not crm_name:
        return None

    entity_raw = attrs.entity_type
    if not entity_raw:
        return None
    entity_type = normalize_entity_type(entity_raw)
    if entity_type is None:
        return None

    override = overrides.get((entity_type, crm_name))

    display_name = (
        override.display_name.strip()
        if override is not None and override.display_name
        else crm_name
    )
    aliases = tuple(
        a.strip() for a in (override.aliases if override is not None else ()) if a.strip()
    )
    description = (
        override.description if override is not None and override.description else attrs.description
    )

    lov_set_ids = resource.related_ids(LOV_SET_RELATIONSHIP)
    lov_set_id = lov_set_ids[0] if lov_set_ids else None

    return CustomFieldDefinition(
        definition_id=resource.id,
        entity_type=entity_type,
        crm_name=crm_name,
        display_name=display_name,
        aliases=aliases,
        description=description,
        field_type=attrs.field_type,
        field_type_display=attrs.field_type_display,
        is_time_series=bool(attrs.is_time_series),
        allowed_values=allowed_values_for(
            lov_set_id=lov_set_id,
            lov_index=lov_index,
            included=included,
            inline_lov_set=attrs.lov_set,
            inline_select_options=attrs.select_options,
        ),
        lov_set_id=lov_set_id,
        raw={
            "id": resource.id,
            "type": resource.type,
            "attributes": attrs.model_dump(by_alias=True, exclude_none=True),
        },
    )


async def fetch_custom_field_definitions(
    client: BackstopClient,
    overrides: dict[str, FieldOverride],
) -> list[CustomFieldDefinition]:
    """Fetch the instance's full custom-field schema, allowed values included.

    Two paginated calls, not one per field: the definitions (with `?include=lovSet`, so the
    side-loaded sets arrive in `included`), and every LOV entry, indexed by set id. See `lov.py`
    for why the entries need their own call.
    """
    lov_index = await fetch_lov_entry_index(client)

    page = await client.paginate(
        _DEFINITIONS_PATH,
        params={"include": LOV_SET_RELATIONSHIP},
        max_records=None,
        schema=BackstopApiResource[CustomFieldDefinitionAttributes],
    )

    override_index = index_overrides(overrides)
    definitions: list[CustomFieldDefinition] = []
    for resource in page.items:
        definition = definition_from_resource(
            resource, override_index, lov_index=lov_index, included=page.included
        )
        if definition is not None:
            definitions.append(definition)
    return definitions
